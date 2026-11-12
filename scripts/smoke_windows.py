"""Check that the frozen executable can convert without a Python installation."""
from pathlib import Path
import os
import subprocess
from tempfile import TemporaryDirectory
import pypdfium2 as pdfium
from make_examples import create_rotated_text, create_sample

ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'.tmp/frozen-smoke';folder.mkdir(parents=True,exist_ok=True)
source=create_sample(folder/'source.pdf')
target=folder/'result.pdf'
run=subprocess.run([str(ROOT/'dist/BionicPDF.exe'),'--cli',str(source),str(target),'--mode','static'],timeout=120,env=dict(os.environ,TMP=str(folder),TEMP=str(folder)))
assert run.returncode==0,run.returncode
before,after=pdfium.PdfDocument(source),pdfium.PdfDocument(target)
assert len(before)==len(after)==14
for i in range(len(before)):
    assert before[i].get_textpage().get_text_range()==after[i].get_textpage().get_text_range()
before.close();after.close()
print('Standalone Windows conversion passed for 13 languages and a blank page')
with TemporaryDirectory(dir=folder) as temp:
    output = Path(temp)
    rotated = create_rotated_text(output/'rotated.pdf')
    gui = subprocess.run([str(ROOT/'dist/BionicPDF.exe'), '--smoke-gui', str(rotated), temp],
                         timeout=70, env=dict(os.environ, TMP=temp, TEMP=temp))
    if gui.returncode and (output/'gui-smoke-error.txt').exists():
        print((output/'gui-smoke-error.txt').read_text(encoding='utf-8'))
    assert gui.returncode == 0, gui.returncode
    with (pdfium.PdfDocument(rotated) as original, pdfium.PdfDocument(output/'switchable.pdf') as off,
          pdfium.PdfDocument(output/'static.pdf') as static):
        assert len(off) == len(static) == 1
        pixels = original[1].render(scale=2).to_pil()
        assert off[0].render(scale=2).to_pil() == pixels != static[0].render(scale=2).to_pil()
print('Standalone Windows GUI, 90-degree page export in both modes, language choices and guide passed')
