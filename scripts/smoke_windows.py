"""Check that the frozen executable can convert without a Python installation."""
from pathlib import Path
import os
import subprocess
import pypdfium2 as pdfium
from make_examples import create_sample

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
gui=subprocess.run([str(ROOT/'dist/BionicPDF.exe'),'--smoke-gui'],timeout=30,env=dict(os.environ,TMP=str(folder),TEMP=str(folder)))
assert gui.returncode==0,gui.returncode
print('Standalone Windows GUI, 13 language choices and in-app guide passed')
