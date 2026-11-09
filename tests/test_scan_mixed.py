"""Optional OCR should supplement a scanned body without redrawing selectable text."""
from pathlib import Path
import shutil

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, RectangleObject, TextStringObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from bionic_pdf import make_pdf


FONT = Path(__file__).parent/'assets/fonts/Latin.ttf'
with_tesseract = pytest.mark.skipif(not (shutil.which('tesseract') or Path('C:/Program Files/Tesseract-OCR/tesseract.exe').is_file()),
                                     reason='requires local Tesseract with English data')


def mixed_page(folder, *, footer='Document archive', logo=False, rotated=False, inset=False):
    font = ImageFont.truetype(str(FONT), 60)
    raster = Image.new('RGB', (1440, 576), 'white')
    ImageDraw.Draw(raster).text((80, 105), 'Reading together', font=font, fill='black')
    ImageDraw.Draw(raster).text((80, 300), 'the readers', font=font, fill='black')
    path = folder/'source.pdf'
    size = (204, 384) if rotated else (384, 204)
    page = Canvas(str(path), pagesize=(612, 792) if inset else size, invariant=True)
    pdfmetrics.registerFont(TTFont('MixedText', str(FONT)))
    if rotated:
        page.translate(204, 0)
        page.rotate(90)
    # The image lives in a translated Form so tests exercise page-space bounds.
    page.beginForm('scan', 0, 0, 360, 144)
    page.drawImage(ImageReader(raster), 0, 0, 360, 144)
    page.endForm()
    page.saveState()
    if inset:
        page.translate(180, 360)
        page.scale(250/360, 85/144)  # A readable inset on just 4.4% of a Letter page.
    else:
        page.translate(12, 42)
    if logo:
        page.scale(.12, .12)
    page.doForm('scan')
    page.restoreState()
    page.beginForm('labels', 0, 0, 384, 204)
    page.setFont('MixedText', 14)
    page.drawString(18, 26, footer)
    # A native label overlaps the image's bounding rectangle.
    if footer != '1':
        page.drawString(240, 80, 'Native label')
    page.endForm()
    page.doForm('labels')
    page.showPage()
    page.save()
    if rotated:
        document = PdfWriter(clone_from=path)
        document.pages[0].cropbox = RectangleObject((6, 6, 198, 378))
        document.pages[0].rotate(90)
        path = folder/'rotated.pdf'
        document.write(path)
    return path


@with_tesseract
@pytest.mark.parametrize('rotated', [False, True])
def test_mixed_scan_keeps_native_ink_and_completes_raster_text(tmp_path, rotated):
    source = mixed_page(tmp_path, rotated=rotated)
    vector, off, on, fixed = (tmp_path/(name+'.pdf') for name in ('vector', 'off', 'on', 'fixed'))
    native = make_pdf(source, vector, mode='static')
    combined = make_pdf(source, off, ocr=True)
    make_pdf(source, fixed, ocr=True, mode='static')
    assert combined['ocr_pages'] == [1] and combined['unemphasized_pages'] == []
    assert combined['glyphs'] > native['glyphs']
    writer = PdfWriter(clone_from=off)
    oc = writer.root_object['/OCProperties']
    oc['/D'][NameObject('/ON')] = ArrayObject(oc['/OCGs'])
    oc['/D'][NameObject('/OFF')] = ArrayObject()
    writer.write(on)
    images = []
    for path in (source, off, on, fixed, vector):
        with pdfium.PdfDocument(path) as doc:
            pg = doc[0]
            images.append(pg.render(scale=2).to_pil().convert('L'))
            if path in (off, on, fixed):
                words = pg.get_textpage().get_text_bounded().split()
                for word in ('Document', 'archive', 'Native', 'label', 'Reading', 'together', 'the', 'readers'):
                    assert words.count(word) == 1
    original, disabled, active, static, vector = images
    assert original.tobytes() == disabled.tobytes() and active.tobytes() == static.tobytes()
    new_ink = ImageChops.difference(static, vector)
    assert new_ink.getbbox() and new_ink.getbbox()[2] < 400  # No OCR marks on the native label.
    assert new_ink.getbbox()[3] < static.height - 65  # No OCR marks on the footer.


@with_tesseract
@pytest.mark.parametrize('inset', [False, True])
def test_native_page_number_does_not_block_scan_ocr(tmp_path, inset):
    source = mixed_page(tmp_path, footer='1', inset=inset)
    target = tmp_path/'with-page-number.pdf'
    report = make_pdf(source, target, ocr=True, pages='1,1')
    assert report['ocr_pages'] == [1, 2] and report['unemphasized_pages'] == []
    result = PdfReader(target)
    for page in result.pages:
        assert page.extract_text().split() == ['Reading', 'together', 'the', 'readers', '1']


@with_tesseract
def test_raster_word_between_native_glyphs_in_one_text_object(tmp_path):
    source, target = tmp_path/'same-line.pdf', tmp_path/'copy.pdf'
    pdf = Canvas(str(source), pagesize=(360, 144), invariant=True)
    bitmap = Image.new('RGB', (1440, 576), 'white')
    draw = ImageDraw.Draw(bitmap)
    font = ImageFont.truetype(str(FONT), 64)
    draw.text((500, 200), 'together', anchor='ls', font=font, fill='black')
    draw.text((80, 400), 'Research reading', anchor='ls', font=font, fill='black')
    pdf.drawImage(ImageReader(bitmap), 0, 0, 360, 144)
    labels = pdf.beginText(20, 94)
    labels.setFont('Helvetica', 16)
    labels._code.append('[(Left ) -11000 (Right)] TJ')
    pdf.drawText(labels)
    pdf.save()
    assert make_pdf(source, target, ocr=True)['ocr_pages'] == [1]
    with pdfium.PdfDocument(target) as result:
        assert result[0].get_textpage().get_text_bounded().split() == [
            'Left', 'together', 'Right', 'Research', 'reading']


@with_tesseract
def test_mixed_scan_honors_pending_redactions(tmp_path):
    writer = PdfWriter(clone_from=mixed_page(tmp_path))
    rectangle = writer._add_object(RectangleObject((12, 86, 200, 111)))
    writer.add_annotation(0, DictionaryObject({NameObject('/Subtype'): NameObject('/Redact'),
                                               NameObject('/Rect'): rectangle}))
    page = writer.pages[0]
    page[NameObject('/Annots')] = writer._add_object(page['/Annots'])
    marked, result = tmp_path/'marked.pdf', tmp_path/'copy.pdf'
    writer.write(marked)
    assert make_pdf(marked, result, ocr=True)['ocr_pages'] == [1]
    with pdfium.PdfDocument(result) as doc:
        words = doc[0].get_textpage().get_text_bounded().split()
        assert 'Reading' in words and 'together' in words and 'readers' not in words


@with_tesseract
def test_transparent_native_words_do_not_remove_scan_ink(tmp_path):
    raster = Image.new('RGB', (1440, 576), 'white')
    draw = ImageDraw.Draw(raster)
    font = ImageFont.truetype(str(FONT), 64)
    draw.text((80, 190), 'Reading together', anchor='ls', font=font, fill='black')
    draw.text((80, 375), 'Research papers', anchor='ls', font=font, fill='black')
    results = []
    # Identical appearances using invisible text, transparent fill, stroke, or both.
    for mode, fill, stroke in [(3, 1, 1), (0, 0, 1), (1, 1, 0), (2, 0, 0)]:
        source, output = tmp_path/f'alpha-{mode}.pdf', tmp_path/f'copy-{mode}.pdf'
        pdf = Canvas(str(source), pagesize=(360, 144), invariant=True)
        pdf.drawImage(ImageReader(raster), 0, 0, 360, 144)
        pdf.drawString(22, 15, '1')  # A visible footer and an invisible transcript share a mixed page.
        pdf.setFillAlpha(fill)
        pdf.setStrokeAlpha(stroke)
        word = pdf.beginText(20, 144-190/4)
        word.setFont('Helvetica', 16)
        word.setTextRenderMode(mode)
        word.textOut('Reading')
        pdf.drawText(word)
        pdf.save()
        report = make_pdf(source, output, ocr=True, mode='static')
        assert report['ocr_pages'] == [1]
        with pdfium.PdfDocument(output) as result:
            pg = result[0]
            assert pg.get_textpage().get_text_bounded().split().count('Reading') == 1
            results.append((report['glyphs'], pg.render(scale=2).to_pil().tobytes()))
    assert all(item == results[0] for item in results[1:]) and results[0][0] > 0


@pytest.mark.parametrize('case', ['small picture', 'source layer'])
def test_digital_logo_and_existing_optional_layers_avoid_ocr(tmp_path, monkeypatch, case):
    from bionic_pdf import scan

    source = mixed_page(tmp_path, logo=case == 'small picture')
    if case == 'source layer':
        writer = PdfWriter(clone_from=source)
        layer = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/OCG'),
                                                     NameObject('/Name'): TextStringObject('Source language')}))
        writer.pages[0]['/Resources'][NameObject('/Properties')] = DictionaryObject({NameObject('/Original'): layer})
        writer.root_object[NameObject('/OCProperties')] = DictionaryObject({NameObject('/OCGs'): ArrayObject([layer]),
            NameObject('/D'): DictionaryObject({NameObject('/ON'): ArrayObject([layer])})})
        source = tmp_path/'layered.pdf'
        writer.write(source)
    monkeypatch.setattr(scan, '_recognize', lambda *_: pytest.fail('page should not invoke Tesseract'))
    report = make_pdf(source, tmp_path/'copy.pdf', ocr=True)
    assert report['ocr_pages'] == [] and report['glyphs'] > 0 and report['unemphasized_pages'] == []
