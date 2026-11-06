"""Real browser-shaped PDFs are generated before this integration suite."""
from pathlib import Path
import pytest
import pypdfium2 as pdfium
from PIL import ImageChops
from pypdf import PdfWriter
from pypdf.generic import NameObject as N,ArrayObject as A
from bionic_pdf import make_pdf

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('variant',['tagged','plain'])
def test_shaped_pdf_preserves_text_and_actual_glyphs(variant,tmp_path):
    source=ROOT/f'.tmp/examples/shaped-{variant}.pdf'
    if not source.exists():pytest.skip('Run npm run fixtures:shaped before shaped PDF integration tests')
    off,on,static=[tmp_path/name for name in ('off.pdf','on.pdf','static.pdf')]
    make_pdf(source,off);make_pdf(source,static,mode='static')
    writer=PdfWriter(clone_from=off);props=writer._root_object['/OCProperties']
    props['/D'][N('/ON')]=A([props['/OCGs'][-1]]);props['/D'][N('/OFF')]=A();writer.write(on)
    docs=[pdfium.PdfDocument(p) for p in (source,off,on,static)]
    for i in range(len(docs[0])):
        text=docs[0][i].get_textpage().get_text_range()
        assert all(d[i].get_textpage().get_text_range()==text for d in docs[1:])
        images=[d[i].render(scale=1.5).to_pil().convert('RGB') for d in docs]
        assert images[0].tobytes()==images[1].tobytes()
        assert images[2].tobytes()==images[3].tobytes()
        body=(60,180,images[0].width-60,360)
        assert ImageChops.difference(images[0].crop(body),images[2].crop(body)).getbbox() is not None
        # No original strokes are removed or whitened by emphasis.
        assert ImageChops.subtract(images[2],images[0]).getbbox() is None
    for doc in docs:doc.close()
