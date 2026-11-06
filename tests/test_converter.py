import hashlib
import json
import runpy
from pathlib import Path
import pytest
import pypdfium2 as pdfium
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject as N,ArrayObject as A
from bionic_pdf import make_pdf

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def converted(tmp_path_factory):
    folder=tmp_path_factory.mktemp('pdf')
    samples=json.loads((ROOT/'examples/languages.json').read_text(encoding='utf-8'))
    # Complex-script word-boundary tests are separate from PDF typography tests.
    samples=[s for s in samples if s['code'] not in ('ar','he','hi')]
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

def test_refuses_original_overwrite_and_repeated_conversion(converted,tmp_path):
    source,switchable,*_=converted
    with pytest.raises(ValueError):make_pdf(source,source)
    with pytest.raises(ValueError):make_pdf(switchable,tmp_path/'twice.pdf')
