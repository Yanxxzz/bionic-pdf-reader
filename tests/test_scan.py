from pathlib import Path
import shutil

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, RectangleObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from bionic_pdf import make_pdf


def scan_sample(folder, *, rotated=False, hidden_text=False, lines=('Reading together', 'the readers'),
                background='white', foreground='black', transcript=()):
    image = Image.new('RGB', (1200, 440), background)
    font = ImageFont.truetype(str(Path(__file__).parent/'assets/fonts/Latin.ttf'), 56)
    draw = ImageDraw.Draw(image)
    for y, line in zip((65, 200), lines):
        draw.text((90, y), line, font=font, fill=foreground)
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
    if transcript:
        text = doc.beginText()
        text.setFont('Helvetica', 16)
        text.setTextRenderMode(3)
        for x, y, line in transcript:
            text.setTextOrigin(x, y)
            text.textLine(line)
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
@pytest.mark.parametrize('background,foreground', [('black','white'), ('white','#1558b0')])
def test_ocr_preserves_light_and_coloured_ink(tmp_path, background, foreground):
    source = scan_sample(tmp_path, background=background, foreground=foreground)
    fixed, off = tmp_path/'fixed.pdf', tmp_path/'off.pdf'
    make_pdf(source, fixed, mode='static', ocr=True)
    make_pdf(source, off, ocr=True)
    prefix = (80, 180, 103, 265)  # The t in "the".
    with pdfium.PdfDocument(source) as src, pdfium.PdfDocument(fixed) as active, pdfium.PdfDocument(off) as disabled:
        old, new, restored = [doc[0].render(scale=3).to_pil().convert('RGB') for doc in (src, active, disabled)]
        assert old.tobytes() == restored.tobytes()
        assert new.crop((111,180,155,265)).tobytes() == old.crop((111,180,155,265)).tobytes()
        def foreground_area(image):
            colors = image.crop(prefix).getcolors(10000)
            if foreground == 'white':
                return sum(n for n,(r,g,b) in colors if min(r,g,b) > 220)
            return sum(n for n,(r,g,b) in colors if b-r > 85 and b-g > 35)
        assert foreground_area(new) > foreground_area(old)
        assert 'the readers' in active[0].get_textpage().get_text_bounded()


@with_tesseract
@pytest.mark.parametrize('position,parsenote', [((27,55,'the readers'), 'the readers'),
                                               ((91,95,'together'), 'together')])
def test_partial_hidden_text_is_completed_in_reading_order(tmp_path, position, parsenote):
    source = scan_sample(tmp_path, transcript=[position])
    target = tmp_path/'copy.pdf'
    assert make_pdf(source, target, ocr=True)['ocr_pages'] == [1]
    with pdfium.PdfDocument(target) as result:
        extracted = result[0].get_textpage().get_text_bounded()
    for text in (extracted, PdfReader(target).pages[0].extract_text()):
        assert parsenote in text
        assert text.split() == ['Reading', 'together', 'the', 'readers']


@with_tesseract
def test_ocr_fills_a_gap_between_authored_lines_in_one_text_object(tmp_path):
    source = scan_sample(tmp_path, transcript=[(27,95,'Reading'), (58,55,'readers')])
    target = tmp_path/'copy.pdf'
    make_pdf(source, target, ocr=True)
    with pdfium.PdfDocument(target) as result:
        assert result[0].get_textpage().get_text_bounded().split() == ['Reading','together','the','readers']
    assert PdfReader(target).pages[0].extract_text().split() == ['Reading','together','the','readers']


@with_tesseract
@pytest.mark.parametrize('tagged', [False, True])
def test_ocr_preserves_the_form_invocation_and_its_structure(tmp_path, tagged):
    # The same captions overlay two different scanned panels. Each needs its own missing words.
    source, target = tmp_path/'panels.pdf', tmp_path/'copy.pdf'
    pdf = Canvas(str(source), pagesize=(360,264), invariant=1)
    pdf.beginForm('Captions', 0, 0, 360, 132)
    old = pdf.beginText()
    old.setFont('Helvetica',16)
    old.setTextRenderMode(3)
    for x,y,word in ((27,95,'Reading'),(58,55,'readers')):
        old.setTextOrigin(x,y)
        old.textLine(word)
    pdf.drawText(old)
    pdf.endForm()
    font = ImageFont.truetype(str(Path(__file__).parent/'assets/fonts/Latin.ttf'), 56)
    panels = [(132, 'together')] if tagged else [(132,'together'), (0,'separately')]
    for offset, next_word in panels:
        image = Image.new('RGB', (1200,440), 'white')
        draw = ImageDraw.Draw(image)
        draw.text((90,65),'Reading '+next_word,font=font,fill='black')
        draw.text((90,200),'the readers',font=font,fill='black')
        pdf.saveState()
        pdf.translate(0,offset)
        pdf.drawImage(ImageReader(image),0,0,360,132)
        pdf.doForm('Captions')
        pdf.restoreState()
    pdf.save()
    if tagged:
        writer=PdfWriter(clone_from=source)
        page=writer.pages[0]
        old=page['/Resources']['/XObject']['/FormXob.Captions']
        form=DecodedStreamObject()
        form.set_data(b'/Span <</MCID 0>> BDC\n'+old.get_data()+b'\nEMC')
        for key,value in old.items():
            if key not in ('/Length','/Filter','/DecodeParms'):
                form[key]=value
        form[NameObject('/StructParents')]=NumberObject(0)
        ref=writer._add_object(form)
        page['/Resources']['/XObject'][NameObject('/FormXob.Captions')]=ref
        root=DictionaryObject({NameObject('/Type'):NameObject('/StructTreeRoot')})
        rootref=writer._add_object(root)
        mcr=DictionaryObject({NameObject('/Type'):NameObject('/MCR'),NameObject('/MCID'):NumberObject(0),
                              NameObject('/Pg'):page.indirect_reference,NameObject('/Stm'):ref})
        elem=writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/StructElem'), NameObject('/S'):NameObject('/P'),
            NameObject('/P'):rootref,NameObject('/Pg'):page.indirect_reference,NameObject('/K'):mcr}))
        root.update({NameObject('/K'):ArrayObject([elem]),NameObject('/ParentTree'):DictionaryObject({
            NameObject('/Nums'):ArrayObject([NumberObject(0),ArrayObject([elem])])})})
        writer.root_object[NameObject('/StructTreeRoot')]=rootref
        source=tmp_path/'tagged.pdf'
        writer.write(source)
    assert make_pdf(source,target,ocr=True)['ocr_pages']==[1]
    expected = [word for _,adj in panels for word in ('Reading',adj,'the','readers')]
    result=PdfReader(target)
    assert result.pages[0].extract_text().split()==expected
    with pdfium.PdfDocument(source) as a, pdfium.PdfDocument(target) as b:
        assert b[0].get_textpage().get_text_bounded().split()==expected
        assert a[0].render(scale=2).to_pil().tobytes()==b[0].render(scale=2).to_pil().tobytes()
    if tagged:
        tree=result.root_object['/StructTreeRoot']
        referenced=tree['/K'][0].get_object()['/K']['/Stm']
        draws=[args[0] for args,op in result.pages[0].get_contents().operations if op==b'Do']
        assert any(result.pages[0]['/Resources']['/XObject'][name] is referenced for name in draws)
        assert '/StructParents' in referenced


@with_tesseract
def test_low_contrast_ocr_keeps_searchable_text_without_painting(tmp_path):
    source = scan_sample(tmp_path, background='#aaaaaa', foreground='#909090')
    target = tmp_path/'fixed.pdf'
    report = make_pdf(source, target, ocr=True, mode='static')
    assert report['ocr_pages'] == report['unemphasized_pages'] == [1]
    with pdfium.PdfDocument(source) as original, pdfium.PdfDocument(target) as result:
        assert original[0].render(scale=3).to_pil().tobytes() == result[0].render(scale=3).to_pil().tobytes()
        assert 'the readers' in result[0].get_textpage().get_text_bounded()


@with_tesseract
def test_number_only_scan_remains_searchable_without_any_emphasis(tmp_path):
    source = scan_sample(tmp_path, lines=('12345', '67890'))
    target = tmp_path/'numbers.pdf'
    report = make_pdf(source, target, ocr=True)
    assert report['glyphs'] == 0
    assert report['ocr_pages'] == report['unemphasized_pages'] == [1]
    with pdfium.PdfDocument(source) as original, pdfium.PdfDocument(target) as result:
        assert result[0].render(scale=2).to_pil().tobytes() == original[0].render(scale=2).to_pil().tobytes()
        assert result[0].get_textpage().get_text_bounded().split() == ['12345', '67890']


@with_tesseract
def test_existing_ocr_text_is_not_duplicated(tmp_path):
    source = scan_sample(tmp_path, transcript=[(27,95,'Reading together'), (27,55,'the readers')])
    target = tmp_path/'result.pdf'
    assert make_pdf(source, target, ocr=True)['ocr_pages'] == [1]
    with pdfium.PdfDocument(target) as result:
        assert result[0].get_textpage().get_text_bounded().split() == ['Reading','together','the','readers']
    assert '/BROcrText' not in PdfReader(target).pages[0]['/Resources']['/XObject']


@with_tesseract
def test_existing_note_outside_the_recognized_lines_keeps_its_position(tmp_path):
    source = scan_sample(tmp_path, hidden_text=True)
    target = tmp_path/'copy.pdf'
    make_pdf(source, target, ocr=True)
    with pdfium.PdfDocument(target) as result:
        assert result[0].get_textpage().get_text_bounded().split() == [
            'Reading','together','Existing','OCR','transcript','the','readers']


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


@with_tesseract
def test_missing_ocr_language_preserves_the_destination(tmp_path, monkeypatch):
    source = scan_sample(tmp_path)
    target = tmp_path/'existing.pdf'
    target.write_bytes(b'previous')
    monkeypatch.setenv('TESSDATA_PREFIX', str(tmp_path))
    with pytest.raises(ValueError, match='fra'):
        make_pdf(source, target, ocr=True, locale='fr')
    assert target.read_bytes() == b'previous'
