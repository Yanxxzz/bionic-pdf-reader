from pathlib import Path
import shutil
import subprocess

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from bionic_pdf import make_pdf
from scripts.make_examples import create_partial_scan


pytestmark = pytest.mark.skipif(not (shutil.which('tesseract') or
                                    Path('C:/Program Files/Tesseract-OCR/tesseract.exe').is_file()),
                                reason='requires local Tesseract with English data')


@pytest.mark.parametrize('layout', ['one-TJ', 'separate-text-objects'])
def test_missing_middle_word_is_searchable_at_its_original_position(tmp_path, layout):
    source = create_partial_scan(tmp_path/'partial.pdf', [layout])
    target = tmp_path/'completed.pdf'
    make_pdf(source, target, ocr=True)
    expected = ['Reading together readers', 'Research papers retain their words.']
    with pdfium.PdfDocument(target) as doc:
        assert doc[0].get_textpage().get_text_bounded().splitlines() == expected
    assert PdfReader(target).pages[0].extract_text().splitlines() == expected


def test_wider_authored_font_keeps_the_space_before_each_missing_word(tmp_path):
    # The image's letters and the two hidden words start at the same points. Helvetica's
    # longer advances leave too little room for readers to infer the next space from geometry.
    body = 'I found a pressed fern between two pages.'
    source = create_partial_scan(tmp_path/'partial.pdf', ['wider-font'])
    target = tmp_path/'completed.pdf'
    make_pdf(source, target, ocr=True)

    with pdfium.PdfDocument(target) as doc:
        native_text = doc[0].get_textpage().get_text_bounded()
    for text in (native_text, PdfReader(target).pages[0].extract_text()):
        assert [line.strip() for line in text.splitlines()] == [body, 'The next line stays separate.', '1']


def test_splicing_visible_word_spaced_text_preserves_the_native_cursor(tmp_path):
    source = tmp_path/'base.pdf'
    font = ImageFont.truetype(str(Path(__file__).parent/'assets/fonts/Latin.ttf'), 64)
    picture = Image.new('RGB', (1920,600), 'white')
    draw = ImageDraw.Draw(picture)
    draw.text((88+font.getlength('Reading '),165), 'together', font=font, fill='black', anchor='ls')
    draw.text((88,340), 'Research papers retain their words.', font=font, fill='black', anchor='ls')
    canvas = Canvas(str(source), pagesize=(480,150), invariant=True)
    canvas.drawImage(ImageReader(picture), 0, 0, 480, 150)
    native = canvas.beginText(22,108.75)
    native.setFont('Helvetica',16)
    # A single visible string has an author-corrected word and a large word space.
    native.setWordSpace(font.getlength('Reading together ')/4 - stringWidth('Rending ', 'Helvetica',16))
    native.textOut('Rending readers')
    native.setWordSpace(0)
    native._code.append('0 -90 Td (Archive) Tj')  # Relative to the original line, not the OCR word.
    canvas.drawText(native)
    canvas.save()
    pdf = PdfWriter(clone_from=source)
    fonts = pdf.pages[0]['/Resources']['/Font']
    fonts[NameObject('/F1')] = DictionaryObject(fonts['/F1'])  # A font can be a direct dictionary.
    source, target = tmp_path/'visible.pdf', tmp_path/'completed.pdf'
    pdf.write(source)
    make_pdf(source, target, ocr=True)

    with pdfium.PdfDocument(source) as before, pdfium.PdfDocument(target) as after:
        old, new = before[0], after[0]
        assert old.render(scale=3).to_pil().tobytes() == new.render(scale=3).to_pil().tobytes()
        baseline, result = old.get_textpage(), new.get_textpage()
        assert result.get_text_bounded().split() == 'Rending together readers Research papers retain their words. Archive'.split()
        for word in ('Rending', 'readers', 'Archive'):
            a, n = baseline.search(word).get_next()
            b, _ = result.search(word).get_next()
            for k in range(n):
                assert result.get_charbox(b+k) == pytest.approx(baseline.get_charbox(a+k), abs=.001)

    if pdftoppm := shutil.which('pdftoppm'):
        def poppler_pixels(path):
            return subprocess.check_output([pdftoppm, '-f', '1', '-l', '1', '-scale-to', '1230',
                                            '-singlefile', str(path)])
        assert poppler_pixels(target) == poppler_pixels(source)
