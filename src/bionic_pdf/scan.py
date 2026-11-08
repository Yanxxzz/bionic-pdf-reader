"""Recognize a scanned page locally and thicken the ink in its selected letters."""
from contextlib import closing, contextmanager
from functools import partial
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject,
                           NameObject, NumberObject)

from .document import bind_resource
from .words import segment_flags


MODELS = dict(en='eng', fr='fra', de='deu', es='spa', pt='por', it='ita', nl='nld',
              pl='pol', tr='tur', vi='vie', ru='rus', uk='ukr', el='ell')


@contextmanager
def open_scans(source, locale, rule, weight):
    try:
        import pypdfium2 as pdfium
        from PIL import Image
    except ImportError as error:
        raise ValueError('本地 OCR 需要额外组件。请安装 bionic-pdf-reader[ocr] 或使用 Windows 便携版。') from error
    model = MODELS.get(locale.lower().replace('_', '-').split('-')[0], 'eng')
    with pdfium.PdfDocument(source) as document:
        yield partial(_scan_page, document, model, rule, weight)


def _recognize(image, model, dpi, need_text):
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
                   '-c', 'hocr_char_boxes=1', '-c', 'tessedit_create_hocr=1']
        if need_text:
            command.extend(['-c', 'tessedit_create_pdf=1', '-c', 'textonly_pdf=1'])
        result = subprocess.run(command, capture_output=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            message = result.stderr.decode('utf-8', 'replace').strip()
            raise ValueError(f'本地 OCR 失败。请确认已安装语言包 {model}。\n{message}')
        hocr = ElementTree.parse(output.with_suffix('.hocr'))
        text_pdf = output.with_suffix('.pdf').read_bytes() if need_text else None
    return hocr, text_pdf


def _ink_mask(image, hocr, rule, weight):
    from PIL import Image, ImageFilter

    mask = Image.new('1', image.size)
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
                pixels = image.crop(bounds)
                dark, light = pixels.getextrema()
                if light - dark < 48:
                    continue
                ink = pixels.point(lambda v: 255 if v < (dark+light)/2 else 0)
                expanded = ink.filter(ImageFilter.MaxFilter(2*radius+1))
                if expanded.getbbox():
                    mask.paste(255, bounds, expanded)
                    count += 1
            offset += 1  # The word separator in the line passed to segment_flags.
    return mask, count


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


def _add_scan(writer, page, mask, matrix, text_pdf, layer):
    resources = DictionaryObject(page.get('/Resources', DictionaryObject()).get_object())
    for key in ('/XObject', '/Properties'):
        if key in resources:
            resources[NameObject(key)] = DictionaryObject(resources[key])
    page[NameObject('/Resources')] = resources

    def stream(data):
        obj = DecodedStreamObject()
        obj.set_data(data)
        return obj

    commands = ['Q', 'q', ' '.join(f'{n:.8f}' for n in matrix) + ' cm']
    if text_pdf:
        text = PdfReader(BytesIO(text_pdf)).pages[0]
        # Tesseract can exit successfully with an unresolved pdf.ttf symlink on Windows.
        for font in text['/Resources']['/Font'].values():
            for child in font.get_object().get('/DescendantFonts', ()):
                descriptor = child.get_object().get('/FontDescriptor')
                if descriptor and '/FontFile2' in descriptor.get_object():
                    data = descriptor.get_object()['/FontFile2'].get_data()
                    if data[:4] not in (b'\x00\x01\x00\x00', b'true', b'ttcf'):
                        raise ValueError('Tesseract 的 pdf.ttf 无效。请恢复语言数据目录里的实际字体文件后再导出。')
        form = stream(text.get_contents().get_data())
        form.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                     NameObject('/BBox'): text.mediabox.clone(writer),
                     NameObject('/Resources'): text['/Resources'].clone(writer)})
        name = bind_resource(resources, '/XObject', NameObject('/BROcrText'), writer._add_object(form.flate_encode()))
        commands.append(f'q {1/float(text.mediabox.width):.10f} 0 0 {1/float(text.mediabox.height):.10f} 0 0 cm {name} Do Q')
    if mask is not None:
        image = stream(mask.tobytes())
        image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                      NameObject('/Width'): NumberObject(mask.width), NameObject('/Height'): NumberObject(mask.height),
                      NameObject('/BitsPerComponent'): NumberObject(1), NameObject('/ImageMask'): BooleanObject(True),
                      NameObject('/Interpolate'): BooleanObject(True),
                      NameObject('/Decode'): ArrayObject([NumberObject(1), NumberObject(0)])})
        name = bind_resource(resources, '/XObject', NameObject('/BROcrInk'), writer._add_object(image.flate_encode()))
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


def _scan_page(document, model, rule, weight, index, writer, target, layer):
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
        with closing(page.get_textpage()) as text:
            need_text = not text.get_text_bounded().strip()
        scale = min(300/72, 4200/max(page.get_size()))
        with closing(page.render(scale=scale, grayscale=True, draw_annots=True)) as bitmap:
            image = bitmap.to_pil().convert('L')
            coords = bitmap.get_posconv(page)
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
                    draw.rectangle((min(ax,bx), min(ay,by), max(ax,bx), max(ay,by)), fill=255)
        hocr, text_pdf = _recognize(image, model, max(1, round(scale*72)), need_text)
        mask, count = _ink_mask(image, hocr, rule, weight)
        # Numbers and short labels may be searchable even when no letter should be thickened.
        if not count and not (text_pdf and hocr.find(".//*[@class='ocrx_word']") is not None):
            return None
        matrix = (right[0]-x, right[1]-y, top[0]-x, top[1]-y, x, y)
        _add_scan(writer, target, mask if count else None, matrix, text_pdf, layer)
        return count
