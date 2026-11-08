"""Recognize a scanned page locally and thicken the ink in its selected letters."""
from contextlib import closing, contextmanager
from functools import partial
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject,
                           DictionaryObject, NameObject, NumberObject)

from .document import bind_resource
from .scan_text import existing_words, place_text, prepare_text
from .words import segment_flags


MODELS = dict(en='eng', fr='fra', de='deu', es='spa', pt='por', it='ita', nl='nld',
              pl='pol', tr='tur', vi='vie', ru='rus', uk='ukr', el='ell')


@contextmanager
def open_scans(source, locale, rule, weight, form_tags):
    try:
        import pypdfium2 as pdfium
        from PIL import Image
    except ImportError as error:
        raise ValueError('本地 OCR 需要额外组件。请安装 bionic-pdf-reader[ocr] 或使用 Windows 便携版。') from error
    model = MODELS.get(locale.lower().replace('_', '-').split('-')[0], 'eng')
    with pdfium.PdfDocument(source) as document:
        yield partial(_scan_page, document, model, rule, weight, form_tags)


def _recognize(image, model, dpi):
    executable = shutil.which('tesseract')
    if not executable and os.name == 'nt':
        standard = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'Tesseract-OCR/tesseract.exe'
        if standard.is_file():
            executable = str(standard)
    if not executable:
        raise ValueError('请先在本机安装 Tesseract 5 和所需语言包，再使用 OCR。')
    with TemporaryDirectory() as folder:
        source, output = Path(folder)/'page.png', Path(folder)/'recognized'
        image.save(source)
        command = [executable, str(source), str(output), '-l', model, '--dpi', str(dpi),
                   '-c', 'hocr_char_boxes=1', '-c', 'tessedit_create_hocr=1',
                   '-c', 'tessedit_create_pdf=1', '-c', 'textonly_pdf=1']
        result = subprocess.run(command, capture_output=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            message = result.stderr.decode('utf-8', 'replace').strip()
            raise ValueError(f'本地 OCR 失败。请确认已安装语言包 {model}。\n{message}')
        hocr = ElementTree.parse(output.with_suffix('.hocr'))
        text_pdf = output.with_suffix('.pdf').read_bytes()
    return hocr, text_pdf


def _character_ink(image, bounds, radius):
    from PIL import Image, ImageDraw, ImageFilter, ImageStat

    pixels = image.crop(bounds)
    gray = pixels.convert('L')
    left, top, right, bottom = bounds
    pad = max(3, gray.height // 8)
    context = image.crop((left, max(0, top-pad), right, min(image.height, bottom+pad))).convert('L')
    border = Image.new('1', context.size)
    draw = ImageDraw.Draw(border)
    for y in (0, context.height-1):
        draw.line((0, y, context.width-1, y), fill=1)
    edge = context.histogram(mask=border)
    background = ImageStat.Stat(context, border).median[0]
    if sum(edge[max(0, background-20):background+21]) < .65 * sum(edge):
        return None
    dark, light = gray.getextrema()
    below, above = background-dark, light-background
    contrast = max(below, above)
    if contrast < 48 or min(below, above) > contrast/2:
        return None
    polarity = 1 if above > below else -1
    distance = [(level - background) * polarity for level in range(256)]
    solid = gray.point([255 if d >= .85 * contrast else 0 for d in distance])
    if solid.histogram()[255] < max(1, gray.width * gray.height * .02):
        return None
    color = tuple(ImageStat.Stat(pixels, solid).median)
    ink = gray.point([255 if d > contrast/2 else 0 for d in distance])
    return ink.filter(ImageFilter.MaxFilter(2*radius+1)), color


def _ink_mask(image, hocr, rule, weight):
    from PIL import Image

    mask = Image.new('1', image.size)
    colors = None  # Monochrome scans need only the one-bit stencil.
    count = 0
    for line in hocr.iter():
        words = []
        for word in line.findall("./*[@class='ocrx_word']"):
            chars = word.findall(".//*[@class='ocrx_cinfo']")
            text = ''.join(''.join(c.itertext()) for c in chars)
            confidence = re.search(r'\bx_wconf (\d+)', word.get('title', ''))
            words.append((text, chars, confidence is not None and int(confidence[1]) >= 50))
        if not words:
            continue
        flags = segment_flags(' '.join(text for text, _, _ in words), rule)
        offset = 0
        for text, chars, confident in words:
            for char in chars:
                end = offset + len(''.join(char.itertext()))
                selected = any(flags[offset:end])
                offset = end
                if not selected or not confident:
                    continue
                box = re.search(r'\bx_bboxes (\d+) (\d+) (\d+) (\d+)', char.get('title', ''))
                if not box:
                    continue
                l, t, r, b = map(int, box.groups())
                radius = min(5, max(1, round((b - t) * weight)))
                bounds = max(0,l-radius), max(0,t-radius), min(image.width,r+radius), min(image.height,b+radius)
                if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                    continue
                sample = _character_ink(image, bounds, radius)
                if sample is None:
                    continue
                expanded, color = sample
                mask.paste(255, bounds, expanded)
                if colors is None and color != (0,0,0):
                    colors = Image.new('RGB', image.size)
                if colors is not None:
                    colors.paste(color, bounds)
                count += 1
            offset += 1  # The word separator in the line passed to segment_flags.
    return (mask, colors) if count else None, count


def _has_source_layers(resources):
    pending = [resources]
    seen = set()
    while pending:
        resources = pending.pop().get_object()
        if id(resources) in seen:
            continue
        seen.add(id(resources))
        properties = resources.get('/Properties', DictionaryObject()).get_object()
        if any(ref.get_object().get('/Type') in ('/OCG', '/OCMD') for ref in properties.values()):
            return True
        for ref in resources.get('/XObject', DictionaryObject()).get_object().values():
            obj = ref.get_object()
            if '/OC' in obj:
                return True
            if '/Resources' in obj:
                pending.append(obj['/Resources'])
    return False


def _add_scan(writer, page, ink, matrix, text, text_groups, layer, form_tags):
    resources = DictionaryObject(page.get('/Resources', DictionaryObject()).get_object())
    for key in ('/XObject', '/Properties'):
        if key in resources:
            resources[NameObject(key)] = DictionaryObject(resources[key])
    page[NameObject('/Resources')] = resources

    def stream(data):
        obj = DecodedStreamObject()
        obj.set_data(data)
        return obj

    placement = ' '.join(f'{n:.8f}' for n in matrix) + ' cm'
    commands = ['Q', 'q', placement]
    if text_groups:
        commands.extend(place_text(writer, page, matrix, text, text_groups, form_tags))
    if ink is not None:
        mask, colors = ink
        image = stream(mask.tobytes())
        image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                      NameObject('/Width'): NumberObject(mask.width), NameObject('/Height'): NumberObject(mask.height),
                      NameObject('/BitsPerComponent'): NumberObject(1), NameObject('/ImageMask'): BooleanObject(True),
                      NameObject('/Interpolate'): BooleanObject(True),
                      NameObject('/Decode'): ArrayObject([NumberObject(1), NumberObject(0)])})
        stencil = writer._add_object(image.flate_encode())
        if colors is not None:
            colored = stream(colors.tobytes())
            for key in ('/Type', '/Subtype', '/Width', '/Height', '/Interpolate'):
                colored[NameObject(key)] = image[key]
            colored.update({NameObject('/BitsPerComponent'): NumberObject(8), NameObject('/ColorSpace'): NameObject('/DeviceRGB'),
                            NameObject('/Mask'): stencil})
            stencil = writer._add_object(colored.flate_encode())
        name = bind_resource(resources, '/XObject', NameObject('/BROcrInk'), stencil)
        commands.append('/Artifact BMC')
        if layer is not None:
            group = bind_resource(resources, '/Properties', NameObject('/BRBionic'), layer)
            commands.append(f'/OC {group} BDC')
        commands.append(f'0 g {name} Do')
        if layer is not None:
            commands.append('EMC')
        commands.append('EMC')
    commands.append('Q')
    old = page.raw_get('/Contents')
    contents = old.get_object()
    originals = contents if isinstance(contents, ArrayObject) else [old]
    page[NameObject('/Contents')] = ArrayObject([writer._add_object(stream(b'q\n')), *originals,
        writer._add_object(stream(('\n'+'\n'.join(commands)+'\n').encode('ascii')))])


def _scan_page(document, model, rule, weight, form_tags, index, writer, target, layer):
    from PIL import ImageDraw
    from pypdfium2 import raw

    # A raster cannot identify which source OCG owns each pixel.
    if _has_source_layers(target.get('/Resources', DictionaryObject())):
        return None
    with closing(document[index]) as page:
        objects = list(page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE, raw.FPDF_PAGEOBJ_TEXT]))
        if not any(obj.type == raw.FPDF_PAGEOBJ_IMAGE for obj in objects):
            return None
        if any(obj.type == raw.FPDF_PAGEOBJ_TEXT and raw.FPDFTextObj_GetTextRenderMode(obj.raw) != 3 for obj in objects):
            return None
        scale = min(300/72, 4200/max(page.get_size()))
        with closing(page.render(scale=scale, draw_annots=True)) as bitmap:
            image = bitmap.to_pil().convert('RGB')
            coords = bitmap.get_posconv(page)
            existing = existing_words(page, coords)
            x, y = coords.to_page(0, image.height)
            right = coords.to_page(image.width, image.height)
            top = coords.to_page(0, 0)
            # Exclude annotation rectangles from recognition, including pending redactions.
            draw = ImageDraw.Draw(image)
            for ref in target.get('/Annots', []):
                rect = ref.get_object().get('/Rect')
                if rect is not None and len(rect) == 4:
                    ax, ay = coords.to_bitmap(float(rect[0]), float(rect[1]))
                    bx, by = coords.to_bitmap(float(rect[2]), float(rect[3]))
                    draw.rectangle((min(ax,bx), min(ay,by), max(ax,bx), max(ay,by)), fill='white')
        hocr, text_pdf = _recognize(image, model, max(1, round(scale*72)))
        ink, count = _ink_mask(image, hocr, rule, weight)
        text, text_groups = prepare_text(text_pdf, hocr, target, existing)
        # Numbers and short labels may be searchable even when no letter should be thickened.
        if not count and not text_groups:
            return None
        matrix = (right[0]-x, right[1]-y, top[0]-x, top[1]-y, x, y)
        _add_scan(writer, target, ink, matrix, text, text_groups, layer, form_tags)
        return count
