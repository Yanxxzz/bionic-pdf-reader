import hashlib
import json
import re
import runpy
from pathlib import Path
import pytest
import pypdfium2 as pdfium
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject as N,ArrayObject as A,DictionaryObject,NumberObject,DecodedStreamObject
from bionic_pdf import make_pdf

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('fixture', ['scaled', 'rotated'])
def test_equivalent_pages_produce_identical_emphasis(tmp_path, fixture):
    from PIL import ImageChops
    from scripts.make_examples import create_rotated_text, create_scaled_text

    create = create_scaled_text if fixture == 'scaled' else create_rotated_text
    source = create(tmp_path/f'{fixture}.pdf')
    def pixels(path):
        with pdfium.PdfDocument(path) as pdf:
            return [page.render(scale=3).to_pil().convert('L') for page in pdf]

    original = pixels(source)
    assert all(image == original[0] for image in original)
    rendered = {}
    for mode in ('static', 'switchable'):
        output = tmp_path/f'{mode}.pdf'
        report = make_pdf(source, output, mode=mode)
        assert report['unemphasized_pages'] == []
        rendered[mode] = pixels(output)
        if fixture == 'rotated' and mode == 'static':
            # PDFium can round a rotated outline edge by one grey level at 3×.
            # Check the exact prefix glyphs and positions as well as the rendered pixels.
            strokes = [tuple(line for line in page.get_contents().get_data().splitlines() if b'/BRGlyph' in line)
                       for page in PdfReader(output).pages]
            assert strokes[0] and len(set(strokes)) == 1
            first = rendered[mode][0]
            assert all(ImageChops.difference(first, image).getextrema()[1] <= 1 for image in rendered[mode])
        else:
            assert all(image == rendered[mode][0] for image in rendered[mode])
    assert all(before != after for before, after in zip(original, rendered['static']))
    assert rendered['switchable'] == original
    writer = PdfWriter(clone_from=tmp_path/'switchable.pdf')
    groups = writer.root_object['/OCProperties']
    groups['/D'][N('/ON')] = groups['/OCGs']
    groups['/D'][N('/OFF')] = A()
    writer.write(tmp_path/'on.pdf')
    assert pixels(tmp_path/'on.pdf') == rendered['static']


@pytest.mark.parametrize(('label_font', 'size'), [('Helvetica', 18), ('Courier', 20)])
def test_switching_from_standard_font_preserves_position(tmp_path, label_font, size):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas

    pdfmetrics.registerFont(TTFont('EmbeddedBody', str(ROOT/'tests/assets/fonts/Latin.ttf')))
    source = tmp_path/'mixed-fonts.pdf'
    pdf = Canvas(str(source), pagesize=(400, 120), invariant=True)
    label = 'Section 12: '
    for absolute in (False, True):
        line = pdf.beginText(30, 58)
        line.setFont(label_font, size)
        line.textOut(label)
        if absolute:
            line.setTextOrigin(30 + pdfmetrics.stringWidth(label, label_font, size), 58)
        line.setFont('EmbeddedBody', size)
        line.textOut('Reading together')
        pdf.drawText(line)
        pdf.showPage()
    pdf.save()

    def pixels(path):
        with pdfium.PdfDocument(path) as doc:
            return [page.render(scale=3).to_pil().tobytes() for page in doc]

    original = pixels(source)
    assert original[0] == original[1]
    static, off = tmp_path/'static.pdf', tmp_path/'off.pdf'
    make_pdf(source, static, mode='static')
    make_pdf(source, off)
    emphasized = pixels(static)
    assert emphasized[0] == emphasized[1] != original[0]
    assert pixels(off) == original

def source_bytes_without_test_layer(page):
    # These fixtures have no source OCG. Remove only our blocks before the real BT operators.
    return re.sub(rb'\n/OC /BRBionic BDC\n.*?\nEMC\n(?=BT)', b'',
                  page.get_contents().get_data(), flags=re.DOTALL)

@pytest.fixture(scope='module')
def converted(tmp_path_factory):
    folder=tmp_path_factory.mktemp('pdf')
    samples=json.loads((ROOT/'examples/languages.json').read_text(encoding='utf-8'))
    generate=runpy.run_path(str(ROOT/'scripts/make_examples.py'))['create_sample']
    source=generate(folder/'source.pdf',samples)
    original=hashlib.sha256(source.read_bytes()).hexdigest()
    switchable,static,on=folder/'switchable.pdf',folder/'static.pdf',folder/'on.pdf'
    report=make_pdf(source,switchable)
    make_pdf(source,static,mode='static')
    writer=PdfWriter(clone_from=switchable)
    props=writer._root_object['/OCProperties'];layer=props['/OCGs'][-1]
    props['/D'][N('/ON')]=A([layer]);props['/D'][N('/OFF')]=A()
    writer.write(on)
    return source,switchable,static,on,report,original,samples

def test_original_bytes_and_structure(converted):
    source,switchable,static,on,report,digest,samples=converted
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
    before,after=PdfReader(source),PdfReader(switchable)
    assert len(before.pages)==len(after.pages)==len(samples)+1
    assert len(before.outline)==len(after.outline)
    for a,b in zip(before.pages,after.pages):
        assert a.mediabox==b.mediabox and a.cropbox==b.cropbox
        assert len(a.get('/Annots',[]))==len(b.get('/Annots',[]))
        if a.get_contents() is not None:
            assert source_bytes_without_test_layer(b) == a.get_contents().get_data()
    assert report['glyphs']>100

def test_text_and_default_pixels_for_all_example_pages(converted):
    source,off,static,on,*_=converted
    docs=[pdfium.PdfDocument(p) for p in (source,off,static,on)]
    for i in range(len(docs[0])):
        text=docs[0][i].get_textpage().get_text_range()
        assert all(d[i].get_textpage().get_text_range()==text for d in docs[1:])
        original=docs[0][i].render(scale=1.3).to_pil().tobytes()
        assert docs[1][i].render(scale=1.3).to_pil().tobytes()==original
        if i<len(docs[0])-1:
            assert docs[2][i].render(scale=1.3).to_pil().tobytes()!=original
            assert docs[2][i].render(scale=1.3).to_pil().tobytes()==docs[3][i].render(scale=1.3).to_pil().tobytes()
    for d in docs:d.close()

def test_vector_layer_has_no_duplicate_text(converted):
    reader=PdfReader(converted[1])
    count=0
    for page in reader.pages:
        for name,ref in page.get('/Resources',{}).get('/XObject',{}).items():
            if name.startswith('/BRGlyph'):
                raw=ref.get_object().get_data();assert b'BT' not in raw and b'Tj' not in raw
                count+=1
    assert count>0
    assert '/OCProperties' not in PdfReader(converted[2]).root_object
    assert PdfReader(converted[2]).metadata.title.endswith(' - Bionic Reading')


def test_document_language_changes_prefixes_and_preserves_original_text(converted, tmp_path):
    from bionic_pdf.words import LANGUAGES
    from pypdf.generic import TextStringObject

    writer = PdfWriter()
    writer.add_page(PdfReader(converted[0]).pages[0])
    writer.root_object[N('/Lang')] = TextStringObject('fr-CA')
    source = tmp_path/'tagged.pdf'
    writer.write(source)
    with pdfium.PdfDocument(source) as original:
        original_text = original[0].get_textpage().get_text_range()
    page_hashes = {}
    for language in ('auto', *LANGUAGES):
        target = tmp_path/f'{language}.pdf'
        make_pdf(source, target, pages=[1], mode='static', locale=language)
        assert PdfReader(target).root_object['/Lang'] == ('fr-CA' if language == 'auto' else language)
        with pdfium.PdfDocument(target) as result:
            assert result[0].get_textpage().get_text_range() == original_text
            pixels = result[0].render(scale=1.5).to_pil().tobytes()
            page_hashes[language] = hashlib.sha256(pixels).digest()
    assert page_hashes['auto'] == page_hashes['en']
    assert page_hashes['fr'] != page_hashes['en']
    assert all(page_hashes[lang] == page_hashes['fr'] for lang in LANGUAGES if lang != 'en')

def test_refuses_original_overwrite_and_repeated_conversion(converted,tmp_path):
    source,switchable,*_=converted
    with pytest.raises(ValueError):make_pdf(source,source)
    with pytest.raises(ValueError):make_pdf(switchable,tmp_path/'twice.pdf')
    with pytest.raises(ValueError):make_pdf(switchable,tmp_path/'slice.pdf',pages=[1])


@pytest.mark.parametrize('pages', [[0], [-1], [1, 99], [1.5], [True], []])
def test_invalid_page_selection_preserves_output(converted, tmp_path, pages):
    target = tmp_path/'existing.pdf'
    target.write_bytes(b'previous output')
    with pytest.raises(ValueError, match='页'):
        make_pdf(converted[0], target, pages=iter(pages))
    assert target.read_bytes() == b'previous output'


def test_page_range_in_cli_and_python_preserves_order_and_labels(converted, tmp_path):
    from bionic_pdf.cli import main

    source = converted[0]
    by_cli, by_api = tmp_path/'cli.pdf', tmp_path/'api.pdf'
    assert main([str(source), str(by_cli), '--pages', '3-2， 1, 1–2']) == 0
    make_pdf(source, by_api, pages='3-2， 1, 1–2')
    original = PdfReader(source)
    expected = [original.pages[i].extract_text() for i in (2, 1, 0, 0, 1)]
    for path in (by_cli, by_api):
        assert [page.extract_text() for page in PdfReader(path).pages] == expected


@pytest.mark.parametrize('spec', ['0,1', '2,,1', '1.5', '2-', '1-999999999', '  '])
def test_invalid_cli_page_range_preserves_output(converted, tmp_path, spec, capsys):
    from bionic_pdf.cli import main

    target = tmp_path/'existing.pdf'
    target.write_bytes(b'previous output')
    with pytest.raises(SystemExit) as error:
        main([str(converted[0]), str(target), '--pages', spec])
    assert error.value.code == 2 and '页码' in capsys.readouterr().err
    assert target.read_bytes() == b'previous output'


def test_selected_pages_keep_requested_order_and_repetitions(converted, tmp_path):
    target = tmp_path/'selected.pdf'
    make_pdf(converted[0], target, pages=iter([2, 1, 2]))
    with pdfium.PdfDocument(converted[0]) as source, pdfium.PdfDocument(target) as result:
        assert [page.get_textpage().get_text_range() for page in result] == [
            source[i].get_textpage().get_text_range() for i in (1, 0, 1)]


def test_source_can_have_a_partial_pdf_filename(converted, tmp_path):
    source = tmp_path/'notes.partial.pdf'
    original = converted[0].read_bytes()
    source.write_bytes(original)
    target = tmp_path/'notes.pdf'
    make_pdf(source, target, pages=[1])
    assert source.read_bytes() == original
    assert len(PdfReader(target).pages) == 1


def test_restoring_graphics_state_places_emphasis_on_the_original_text(converted, tmp_path):
    template = PdfReader(converted[0]).pages[0]
    font = next(key for key, ref in template['/Resources']['/Font'].items()
                if ref.get_object()['/Subtype'] == '/TrueType')
    outer = f'BT {font} 14 Tf 23 TL 1 0 0 1 40 700 Tm (Outer) Tj '
    inner = '0.25 g 1.5 Tc 90 Tz 3 Ts 1 0 0 1 240 600 Tm (Inner) Tj '
    rest = '( Restored) Tj '
    shorthand = "2 1.5 (Following words) \" (Another line) ' ET"
    explicit = '2 Tw 1.5 Tc T* (Following words) Tj T* (Another line) Tj ET'
    # These two pages draw the same text, one using q/Q inside the text object.
    drawings = [outer + 'q ' + inner + 'Q ' + rest + shorthand,
                outer + rest + explicit + f' q BT {font} 14 Tf ' + inner + 'ET Q']
    pixels = []
    for index, drawing in enumerate(drawings):
        writer = PdfWriter()
        page = writer.add_page(template)
        stream = DecodedStreamObject()
        stream.set_data(drawing.encode('ascii'))
        page[N('/Contents')] = writer._add_object(stream)
        source, target = tmp_path/f'source-{index}.pdf', tmp_path/f'bold-{index}.pdf'
        writer.write(source)
        make_pdf(source, target, mode='static')
        with pdfium.PdfDocument(source) as before, pdfium.PdfDocument(target) as after:
            pixels.append((before[0].render(scale=1.5).to_pil().tobytes(),
                           after[0].render(scale=1.5).to_pil().tobytes()))
    assert pixels[0][0] == pixels[1][0]
    assert pixels[0][1] != pixels[0][0]
    assert pixels[0][1] == pixels[1][1]


def test_indirect_font_encoding_draws_the_same_prefix_as_a_direct_encoding(converted, tmp_path):
    pixels = []
    for representation in ('direct', 'indirect'):
        writer = PdfWriter()
        page = writer.add_page(PdfReader(converted[0]).pages[0])
        fonts = page['/Resources']['/Font']
        name = next(name for name in fonts if fonts[name]['/Subtype'] == '/TrueType')
        font = fonts[name]
        embedded = DecodedStreamObject()
        embedded.set_data((ROOT/'tests/assets/fonts/Latin.ttf').read_bytes())
        font['/FontDescriptor'][N('/FontFile2')] = writer._add_object(embedded)
        # Code 65 copies as A via ToUnicode, but the source explicitly draws the B outline.
        encoding = DictionaryObject({N('/Type'): N('/Encoding'), N('/BaseEncoding'): N('/WinAnsiEncoding'),
                                     N('/Differences'): A([NumberObject(65), N('/B')])})
        font[N('/Encoding')] = writer._add_object(encoding) if representation == 'indirect' else encoding
        drawing = DecodedStreamObject()
        drawing.set_data(f'BT {name} 14 Tf 1 0 0 1 20 50 Tm (Alpha readers explore actual glyphs.) Tj ET'.encode())
        page[N('/Contents')] = writer._add_object(drawing)
        source, target = tmp_path/f'{representation}.pdf', tmp_path/f'{representation}-bold.pdf'
        writer.write(source)
        make_pdf(source, target, mode='static')
        with pdfium.PdfDocument(source) as before, pdfium.PdfDocument(target) as after:
            for doc in (before, after):
                assert doc[0].get_textpage().get_text_range() == 'Alpha readers explore actual glyphs.'
            pixels.append(tuple(doc[0].render(scale=2).to_pil().tobytes() for doc in (before, after)))
    assert pixels[0][0] == pixels[1][0]
    assert pixels[0][1] != pixels[0][0]
    assert pixels[0][1] == pixels[1][1]


def test_progress_reports_completed_pages_without_console_output(converted,tmp_path,capsys):
    updates=[]
    result=make_pdf(converted[0],tmp_path/'progress.pdf',pages=[1,2],
        progress=lambda current,total:updates.append((current,total)))
    assert result['pages']==2
    assert updates==[(1,2),(2,2)]
    assert capsys.readouterr().out==''


def test_only_real_text_objects_receive_strokes(converted, tmp_path):
    writer = PdfWriter()
    page = writer.add_page(PdfReader(converted[0]).pages[0])
    fonts = page['/Resources']['/Font']
    name = next(key for key in fonts if fonts[key]['/Subtype'] == '/TrueType')
    # BT also occurs in a comment, the inline RGB image's six data bytes, and a text string.
    data = (b'% BT in a comment\nq 12 0 0 12 40 100 cm BI /W 2 /H 1 /BPC 8 /CS /RGB ID BT)ET/ EI Q\n'
            + f'BT {name} 15 Tf 1 0 0 1 20 50 Tm [(Readers BT) 80 ( ET enjoy words.)] TJ ET'.encode())
    stream = DecodedStreamObject()
    stream.set_data(data)
    page[N('/Contents')] = writer._add_object(stream)
    source, target = tmp_path/'operators.pdf', tmp_path/'operators-off.pdf'
    writer.write(source)
    report = make_pdf(source, target)
    assert report['glyphs'] > 0
    assert source_bytes_without_test_layer(PdfReader(target).pages[0]) == data
    with pdfium.PdfDocument(source) as plain, pdfium.PdfDocument(target) as off:
        assert plain[0].render().to_pil().tobytes() == off[0].render().to_pil().tobytes()


def test_pages_keep_shared_original_content_streams(converted, tmp_path):
    writer = PdfWriter()
    first = writer.add_page(PdfReader(converted[0]).pages[0])
    body = first.raw_get('/Contents')
    comment = DecodedStreamObject()
    comment.set_data(b'% last comment without a newline')
    tail = writer._add_object(comment)
    for contents in (A([body, tail]), writer._add_object(A([body, tail]))):
        page = writer.add_blank_page(first.mediabox.width, first.mediabox.height)
        page[N('/Resources')] = first.raw_get('/Resources')
        page[N('/Contents')] = contents

    # The very same stream can also be painted as a Form on another page.
    body.get_object().update({N('/Type'): N('/XObject'), N('/Subtype'): N('/Form'),
                              N('/BBox'): first.mediabox, N('/Resources'): first.raw_get('/Resources')})
    wrapper = writer.add_blank_page(first.mediabox.width, first.mediabox.height)
    wrapper[N('/Resources')] = DictionaryObject({N('/XObject'): DictionaryObject({N('/Original'): body})})
    use_form = DecodedStreamObject()
    use_form.set_data(b'/Original Do')
    wrapper[N('/Contents')] = writer._add_object(use_form)

    source, target = tmp_path/'shared.pdf', tmp_path/'shared-static.pdf'
    writer.write(source)
    make_pdf(source, target, mode='static')
    output = PdfReader(target)
    streams = [page.get_contents().get_data() for page in output.pages]
    assert streams[1] == streams[2]
    assert streams[1].endswith(comment.get_data() + b'\n')
    original_form = output.pages[3]['/Resources']['/XObject']['/Original']
    assert original_form._data == body.get_object()._data
    with pdfium.PdfDocument(source) as original, pdfium.PdfDocument(target) as updated:
        original_pixels = original[0].render().to_pil().tobytes()
        bold_pixels = updated[0].render().to_pil().tobytes()
        assert bold_pixels != original_pixels
        assert all(updated[i].render().to_pil().tobytes() == bold_pixels for i in (1, 2))
        assert updated[3].render().to_pil().tobytes() == bold_pixels


def test_repeated_nested_forms_use_caller_colour_and_report_physical_output_pages(converted, tmp_path):
    from PIL import ImageChops
    writer = PdfWriter()
    first = writer.add_page(PdfReader(converted[0]).pages[0])
    fonts = first['/Resources']['/Font']
    font = next(name for name in fonts if fonts[name]['/Subtype'] == '/TrueType')

    def form(data, resources):
        stream = DecodedStreamObject()
        stream.set_data(data.encode('ascii'))
        stream.update({N('/Subtype'): N('/Form'), N('/BBox'): A(map(NumberObject, [0, 0, 250, 60])),
                       N('/Resources'): resources})
        return writer._add_object(stream)

    body = form(f'BT {font} 9 Tf 15 16 Td (Reading together) Tj ET', DictionaryObject({N('/Font'): fonts}))
    nested = form('/Text Do', DictionaryObject({N('/XObject'): DictionaryObject({N('/Text'): body})}))
    nested.get_object()[N('/Matrix')] = A(map(NumberObject, (2, 0, 0, 2, 0, 0)))
    transparent = DictionaryObject({N('/ca'): NumberObject(0), N('/CA'): NumberObject(0)})
    resources = DictionaryObject({N('/XObject'): DictionaryObject({N('/Panel'): nested}),
                                  N('/ExtGState'): DictionaryObject({N('/Hidden'): transparent})})
    drawings = ['q 1 0 0 rg /Panel Do Q q 0 0 1 rg 1 0 0 1 300 0 cm /Pa#6Eel % placed again\n Do Q',
                '/Hidden gs /Panel Do', 'q Q', 'q 0 1 -1 0 100 35 cm /Panel Do Q', '/Panel Do']
    for index, drawing in enumerate(drawings):
        page = first if index == 0 else writer.add_blank_page(595, 842)
        if index == 4:  # 9 pt in the stream × 2 in the Form × 2 in page units = 36 pt.
            page[N('/UserUnit')] = NumberObject(2)
        page[N('/Resources')] = resources
        stream = DecodedStreamObject()
        stream.set_data(drawing.encode('ascii'))
        page[N('/Contents')] = writer._add_object(stream)
    source, target = tmp_path/'panels.pdf', tmp_path/'selected-panels.pdf'
    writer.write(source)
    order = [3, 4, 2, 1, 5]
    report = make_pdf(source, target, pages=order, mode='static')
    assert report['unemphasized_pages'] == [1, 3, 5]
    with pdfium.PdfDocument(source) as before, pdfium.PdfDocument(target) as after:
        for i, source_number in enumerate(order):
            old, new = before[source_number - 1], after[i]
            assert old.get_textpage().get_text_bounded() == new.get_textpage().get_text_bounded()
            original, emphasized = [page.render(scale=1.5).to_pil().convert('RGB') for page in (old, new)]
            delta = ImageChops.difference(original, emphasized)
            assert bool(delta.getbbox()) == (i + 1 not in report['unemphasized_pages'])
            if source_number == 1:
                left, right = [delta.crop(box) for box in ((0,0,400,delta.height),(400,0,delta.width,delta.height))]
                # Red text leaves the red channel unchanged on white, blue leaves blue unchanged.
                assert left.getbbox() and left.getchannel('R').getbbox() is None
                assert right.getbbox() and right.getchannel('B').getbbox() is None
    with pytest.raises(ValueError, match='1–2'):
        make_pdf(source, target, pages=[2, 3])
