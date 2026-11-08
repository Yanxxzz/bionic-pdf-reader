from pathlib import Path
import shutil

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont
import pypdfium2 as pdfium
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, RectangleObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from bionic_pdf import make_pdf


def scan_sample(folder, *, rotated=False, hidden_text=False):
    image = Image.new('RGB', (1200, 440), 'white')
    font = ImageFont.truetype(str(Path(__file__).parent/'assets/fonts/Latin.ttf'), 56)
    draw = ImageDraw.Draw(image)
    draw.text((90, 65), 'Reading together', font=font, fill='black')
    draw.text((90, 200), 'the readers', font=font, fill='black')
    path = folder/'scan.pdf'
    width, height = (132, 360) if rotated else (360, 132)
    margin = 18 if rotated else 0
    doc = Canvas(str(path), pagesize=(width+2*margin, height+2*margin), invariant=1)
    if rotated:
        image = image.transpose(Image.Transpose.ROTATE_90)
    doc.drawImage(ImageReader(image), margin, margin, width, height)
    if hidden_text:
        text = doc.beginText(20, 68)
        text.setTextRenderMode(3)
        text.textLine('Existing OCR transcript')
        doc.drawText(text)
    doc.showPage()
    doc.save()
    if rotated:
        writer = PdfWriter(clone_from=path)
        writer.pages[0].cropbox = RectangleObject((margin, margin, width+margin, height+margin))
        writer.pages[0].rotate(90)
        path = folder/'cropped-scan.pdf'
        writer.write(path)
    return path


def test_scan_stays_opt_in(tmp_path):
    source = scan_sample(tmp_path)
    target = tmp_path/'copy.pdf'
    target.write_bytes(b'previous')
    with pytest.raises(ValueError, match='OCR'):
        make_pdf(source, target)
    assert target.read_bytes() == b'previous'


with_tesseract = pytest.mark.skipif(not (shutil.which('tesseract') or Path('C:/Program Files/Tesseract-OCR/tesseract.exe').is_file()),
                                     reason='requires a local Tesseract installation with English data')


@with_tesseract
def test_local_ocr_restores_scan_pixels_and_adds_one_searchable_layer(tmp_path):
    source = scan_sample(tmp_path)
    off, on, static = (tmp_path/(name+'.pdf') for name in ('off', 'on', 'static'))
    original_bytes = source.read_bytes()
    report = make_pdf(source, off, ocr=True)
    assert report['ocr_pages'] == [1] and report['glyphs'] > 0
    make_pdf(source, static, ocr=True, mode='static')
    enabled = PdfWriter(clone_from=off)
    groups = enabled.root_object['/OCProperties']
    groups['/D'][NameObject('/OFF')] = ArrayObject()
    groups['/D'][NameObject('/ON')] = ArrayObject(groups['/OCGs'])
    enabled.write(on)
    pictures = []
    for path in (source, off, on, static):
        with pdfium.PdfDocument(path) as doc:
            page = doc[0]
            text = page.get_textpage().get_text_bounded()
            if path != source:
                assert text.lower().count('reading together') == text.lower().count('the readers') == 1
            pictures.append(page.render(scale=3).to_pil().convert('L'))
    original, disabled, active, fixed = pictures
    assert original.tobytes() == disabled.tobytes()
    assert active.tobytes() == fixed.tobytes()
    difference = ImageChops.difference(active, original)
    assert difference.crop((80, 180, 103, 265)).getbbox()  # The t in "the".
    assert difference.crop((111, 180, 155, 265)).getbbox() is None  # Its h and e.
    assert source.read_bytes() == original_bytes


@with_tesseract
def test_rotated_and_cropped_scan_keeps_the_same_highlight_positions(tmp_path):
    original = scan_sample(tmp_path)
    reference = tmp_path/'normal.pdf'
    make_pdf(original, reference, mode='static', ocr=True)
    def picture(path):
        with pdfium.PdfDocument(path) as doc:
            return doc[0].render(scale=3).to_pil().convert('L')

    reference_ink = ImageChops.difference(picture(original), picture(reference))
    rotated = scan_sample(tmp_path, rotated=True)
    target, off = tmp_path/'result.pdf', tmp_path/'off.pdf'
    make_pdf(rotated, target, pages='1,1', mode='static', ocr=True)
    make_pdf(rotated, off, ocr=True)
    baseline = picture(rotated)
    assert baseline.tobytes() == picture(off).tobytes()
    with pdfium.PdfDocument(target) as after:
        assert len(after) == 2
        for page in after:
            ink = ImageChops.difference(page.render(scale=3).to_pil().convert('L'), baseline)
            assert ink.getbbox() == reference_ink.getbbox()
            assert ink.crop((80, 180, 103, 265)).getbbox()
            assert ink.crop((111, 180, 155, 265)).getbbox() is None
            assert 'the readers' in page.get_textpage().get_text_bounded()


@with_tesseract
def test_existing_ocr_text_is_not_duplicated(tmp_path):
    source = scan_sample(tmp_path, hidden_text=True)
    target = tmp_path/'result.pdf'
    assert make_pdf(source, target, ocr=True)['ocr_pages'] == [1]
    with pdfium.PdfDocument(target) as result:
        assert result[0].get_textpage().get_text_bounded().strip() == 'Existing OCR transcript'


@with_tesseract
def test_ocr_does_not_expose_a_redacted_region(tmp_path):
    writer = PdfWriter(clone_from=scan_sample(tmp_path))
    writer.add_annotation(0, DictionaryObject({NameObject('/Subtype'): NameObject('/Redact'),
        NameObject('/Rect'): RectangleObject((0, 0, 360, 77))}))
    marked, target = tmp_path/'marked.pdf', tmp_path/'result.pdf'
    writer.write(marked)
    make_pdf(marked, target, ocr=True)
    with pdfium.PdfDocument(target) as result:
        text = result[0].get_textpage().get_text_bounded().lower()
        assert 'reading together' in text and 'readers' not in text
