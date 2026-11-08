"""Regression cases for protected inputs, damaged PDFs and painted-over text."""
import subprocess
import sys
from pathlib import Path

import pypdfium2 as pdfium
import pytest
import reportlab
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.constants import UserAccessPermissions
from pypdf.generic import ArrayObject, ByteStringObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from bionic_pdf import make_pdf
from bionic_pdf.document import SignatureLossError


@pytest.fixture
def source(tmp_path):
    source = tmp_path / "visibility.pdf"
    font_path = Path(__file__).parent / "assets/fonts/Latin.ttf"
    pdfmetrics.registerFont(TTFont("VisibilityTest", str(font_path)))
    page = Canvas(str(source), pagesize=(280, 160), invariant=True)
    for case in ("cover", "clip"):
        page.setFillColorRGB(1, 1, 1)
        page.rect(0, 0, 280, 160, stroke=0, fill=1)
        page.setFillColorRGB(0, 0, 0)
        page.setFont("VisibilityTest", 15)
        page.saveState()
        # Apply the same partial visibility using two different PDF mechanisms.
        page.translate(10, 0)
        if case == "clip":
            clip = page.beginPath()
            clip.rect(0, 96, 85, 40)
            page.clipPath(clip, stroke=0, fill=0)
        page.drawString(10, 110, "Visible hidden sample words")
        page.restoreState()
        if case == "cover":
            page.setFillColorRGB(1, 1, 1)
            page.rect(95, 96, 185, 40, stroke=0, fill=1)
        page.setFillColorRGB(0, 0, 0)
        page.drawString(20, 45, "Visible control words")
        page.showPage()
    page.save()
    return source


def test_damaged_xref_fails_promptly_and_preserves_target(tmp_path):
    source = tmp_path / "damaged.pdf"
    # A truncated xref with a forward startxref, from the upstream 6.21.4 regression.
    source.write_bytes(b"%PDF-1.4\nstartxref\n28\n%%EOF\nxref\n1 0\naaa")
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"keep existing output")
    result = subprocess.run(
        [sys.executable, "-m", "bionic_pdf", str(source), str(target)],
        capture_output=True, timeout=8,
    )
    assert result.returncode == 1 and result.stderr
    assert b"Traceback" not in result.stderr
    assert target.read_bytes() == b"keep existing output"


@pytest.mark.parametrize("mode", ["switchable", "static"])
@pytest.mark.parametrize("open_password", ["", "open-password"], ids=["owner-only", "open-password"])
def test_protected_inputs_never_create_an_unprotected_copy(source, tmp_path, mode, open_password):
    protected = tmp_path / "protected.pdf"
    writer = PdfWriter(clone_from=source)
    writer.encrypt(open_password, "owner-password", permissions_flag=UserAccessPermissions.PRINT)
    writer.write(protected)
    original = protected.read_bytes()
    target = tmp_path / "output.pdf"
    with pytest.raises(ValueError, match="加密"):
        make_pdf(protected, target, mode=mode)
    assert not target.exists()
    target.write_bytes(b"previous copy")
    with pytest.raises(ValueError, match="加密"):
        make_pdf(protected, target, pages=[1], mode=mode)
    assert protected.read_bytes() == original
    assert target.read_bytes() == b"previous copy"


@pytest.mark.parametrize('location', ['nested-field', 'certification'])
def test_signed_pdf_requires_consent_before_processing(source, tmp_path, location):
    writer = PdfWriter(clone_from=source)
    sig = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Sig'), NameObject('/Contents'): ByteStringObject(b'signature'),
        NameObject('/ByteRange'): ArrayObject(map(NumberObject, [0, 50, 100, 20])),
    }))
    if location == 'certification':
        writer.root_object[NameObject('/Perms')] = DictionaryObject({NameObject('/DocMDP'): sig})
    else:
        field = DictionaryObject({NameObject('/FT'): NameObject('/Sig'), NameObject('/V'): sig})
        parent = DictionaryObject({NameObject('/Kids'): ArrayObject([writer._add_object(field)])})
        writer.root_object[NameObject('/AcroForm')] = DictionaryObject({NameObject('/Fields'): ArrayObject([parent])})
    signed, target = tmp_path/'signed.pdf', tmp_path/'existing.pdf'
    writer.write(signed)
    original = signed.read_bytes()
    target.write_bytes(b'previous copy')
    for mode in ('static', 'switchable'):
        with pytest.raises(SignatureLossError, match='签名失效'):
            make_pdf(signed, target, mode=mode, progress=lambda *_: pytest.fail('started before consent'))
        assert target.read_bytes() == b'previous copy'
    make_pdf(signed, target, allow_signature_loss=True)
    assert len(PdfReader(target).pages) == 2 and signed.read_bytes() == original


def test_empty_signature_field_can_be_exported(source, tmp_path):
    writer = PdfWriter(clone_from=source)
    field = DictionaryObject({NameObject('/FT'): NameObject('/Sig')})
    writer.root_object[NameObject('/AcroForm')] = DictionaryObject({NameObject('/Fields'): ArrayObject([field])})
    blank = tmp_path/'empty-signature.pdf'
    writer.write(blank)
    assert make_pdf(blank, tmp_path/'reading.pdf')['pages'] == 2


def test_selected_pages_preserve_labels_bookmarks_and_internal_links(source, tmp_path):
    writer = PdfWriter(clone_from=source)
    writer.add_outline_item('First', 0)
    writer.add_outline_item('Second', 1)
    writer.set_page_label(0, 1, style='/r', prefix='Sec-')
    writer.add_annotation(1, Link(rect=(20, 30, 100, 45), target_page_index=0))
    chapters, output = tmp_path/'chapters.pdf', tmp_path/'selected.pdf'
    writer.write(chapters)
    make_pdf(chapters, output, pages=[2, 1, 2])
    copied = PdfReader(output)
    assert copied.page_labels == ['Sec-ii', 'Sec-i', 'Sec-ii']
    bookmarks = {item.title: copied.get_destination_page_number(item) for item in copied.outline}
    assert bookmarks['First'] == 1 and bookmarks['Second'] in (0, 2)
    for i in (0, 2):
        link = copied.pages[i]['/Annots'][0].get_object()
        assert link['/Dest'][0] == copied.pages[1].indirect_reference
    make_pdf(chapters, output, pages=[2])
    copied = PdfReader(output)
    assert [b.title for b in copied.outline] == ['Second']
    assert not copied.pages[0].get('/Annots')


def test_embedded_postscript_type1_uses_the_original_word_positions(tmp_path):
    fonts = Path(reportlab.__file__).parent/'fonts'
    face = pdfmetrics.EmbeddedType1Face(str(fonts/'DarkGardenMK.afm'), str(fonts/'DarkGardenMK.pfb'))
    pdfmetrics.registerTypeFace(face)
    font = pdfmetrics.Font('Type1OutlineTest', face.name, 'WinAnsiEncoding')
    pdfmetrics.registerFont(font)
    source, target = tmp_path/'type1.pdf', tmp_path/'type1-emphasis.pdf'
    canvas = Canvas(str(source), pagesize=(280, 120), invariant=True)
    canvas.setFont(font.fontName, 18)
    canvas.drawString(30, 55, 'Reading values')
    canvas.save()
    assert make_pdf(source, target, mode='static', locale='en')['glyphs'] == 8
    with pdfium.PdfDocument(source) as original, pdfium.PdfDocument(target) as copy:
        before, after = [doc[0].render(scale=3).to_pil() for doc in (original, copy)]
        boundary = int((30 + pdfmetrics.stringWidth('Read', font.fontName, 18)) * 3)
        end = int((30 + pdfmetrics.stringWidth('Reading', font.fontName, 18)) * 3)
        assert before.crop((90, 80, boundary-6, 270)).tobytes() != after.crop((90, 80, boundary-6, 270)).tobytes()
        assert before.crop((boundary+8, 80, end-5, 270)).tobytes() == after.crop((boundary+8, 80, end-5, 270)).tobytes()


def test_strokes_keep_paint_order_and_partial_clips(source, tmp_path):
    off, on, static = [tmp_path / f"{name}.pdf" for name in ("off", "on", "static")]
    make_pdf(source, off)
    make_pdf(source, static, mode="static")
    writer = PdfWriter(clone_from=off)
    properties = writer.root_object["/OCProperties"]
    properties["/D"][NameObject("/ON")] = ArrayObject(properties["/OCGs"])
    properties["/D"][NameObject("/OFF")] = ArrayObject()
    writer.write(on)
    with (pdfium.PdfDocument(source) as original, pdfium.PdfDocument(off) as disabled,
          pdfium.PdfDocument(on) as enabled, pdfium.PdfDocument(static) as permanent):
        for number in range(len(original)):
            pages = [doc[number] for doc in (original, disabled, enabled, permanent)]
            text = pages[0].get_textpage().get_text_range()
            assert all(page.get_textpage().get_text_range() == text for page in pages[1:])
            before, off_image, on_image, static_image = [page.render(scale=2).to_pil() for page in pages]
            assert before.tobytes() == off_image.tobytes()
            assert on_image.tobytes() == static_image.tobytes()
            hidden = (191, 48, 555, 130)
            assert before.crop(hidden).convert("L").getextrema() == (255, 255)
            assert on_image.crop(hidden).tobytes() == before.crop(hidden).tobytes()
            for visible in ((32, 48, 180, 130), (32, 191, 500, 252)):
                assert on_image.crop(visible).tobytes() != before.crop(visible).tobytes()


def test_strokes_cannot_escape_a_soft_mask_inside_a_text_object(source, tmp_path):
    writer = PdfWriter()
    page = writer.add_page(PdfReader(source).pages[0])
    resources = page['/Resources']
    font = next(name for name, ref in resources['/Font'].items()
                if ref.get_object()['/Subtype'] == '/TrueType')
    mask = DecodedStreamObject()
    mask.set_data(b'0 g 0 0 280 160 re f')
    mask.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                 NameObject('/BBox'): page.mediabox, NameObject('/Resources'): DictionaryObject(),
                 NameObject('/Group'): DictionaryObject({NameObject('/S'): NameObject('/Transparency'),
                                                         NameObject('/CS'): NameObject('/DeviceGray')})})
    soft_mask = DictionaryObject({NameObject('/S'): NameObject('/Luminosity'),
                                  NameObject('/G'): writer._add_object(mask)})
    resources[NameObject('/ExtGState')] = DictionaryObject({
        NameObject('/Hide'): DictionaryObject({NameObject('/SMask'): soft_mask})})
    text = DecodedStreamObject()
    text.set_data((f'BT {font} 15 Tf q /Hide gs 1 0 0 1 20 110 Tm (Hidden sample words) Tj Q '
                   '1 0 0 1 20 45 Tm (Visible control words) Tj ET').encode())
    page[NameObject('/Contents')] = writer._add_object(text)
    original, target = tmp_path/'masked.pdf', tmp_path/'masked-static.pdf'
    writer.write(original)
    make_pdf(original, target, mode='static')
    with pdfium.PdfDocument(original) as plain, pdfium.PdfDocument(target) as bold:
        before, after = [doc[0].render(scale=2).to_pil() for doc in (plain, bold)]
        hidden = (32, 48, 555, 130)
        assert before.crop(hidden).convert("L").getextrema() == (255, 255)
        assert before.crop(hidden).tobytes() == after.crop(hidden).tobytes()
        assert before.tobytes() != after.tobytes()
