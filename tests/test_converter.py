import hashlib
import json
import runpy
from pathlib import Path
import pytest
import pypdfium2 as pdfium
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject as N,ArrayObject as A,DecodedStreamObject
from bionic_pdf import make_pdf

ROOT=Path(__file__).resolve().parents[1]

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
            assert a.get_contents().get_data() in b.get_contents().get_data()
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

def test_refuses_original_overwrite_and_repeated_conversion(converted,tmp_path):
    source,switchable,*_=converted
    with pytest.raises(ValueError):make_pdf(source,source)
    with pytest.raises(ValueError):make_pdf(switchable,tmp_path/'twice.pdf')
    with pytest.raises(ValueError):make_pdf(switchable,tmp_path/'slice.pdf',pages=[1])


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


def test_progress_reports_completed_pages_without_console_output(converted,tmp_path,capsys):
    updates=[]
    result=make_pdf(converted[0],tmp_path/'progress.pdf',pages=[1,2],
        progress=lambda current,total:updates.append((current,total)))
    assert result['pages']==2
    assert updates==[(1,2),(2,2)]
    assert capsys.readouterr().out==''


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

    source, target = tmp_path/'shared.pdf', tmp_path/'shared-static.pdf'
    writer.write(source)
    make_pdf(source, target, mode='static')
    output = PdfReader(target)
    streams = [page['/Contents'] for page in output.pages]
    assert all(isinstance(parts, A) for parts in streams)
    assert [len(parts) for parts in streams] == [3, 4, 4]
    assert all(parts[1].get_object()._data == body.get_object()._data for parts in streams)
    assert all(parts[2].get_object().get_data() == comment.get_data() for parts in streams[1:])
    with pdfium.PdfDocument(source) as original, pdfium.PdfDocument(target) as updated:
        original_pixels = original[0].render().to_pil().tobytes()
        bold_pixels = updated[0].render().to_pil().tobytes()
        assert bold_pixels != original_pixels
        assert all(page.render().to_pil().tobytes() == bold_pixels for page in updated)
