from pathlib import Path
import subprocess
import sys
from windows_payload import source_digest

ROOT=Path(__file__).resolve().parents[1]
stamp = ROOT/'build/backend.sha256'
stamp.parent.mkdir(exist_ok=True)
stamp.write_bytes(source_digest(ROOT/'src/bionic_pdf'))
command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
         '--name','BionicPDF','--paths',str(ROOT/'src'),
         '--collect-all','regex','--collect-binaries','freetype','--collect-data','pypdfium2','--collect-all','pypdfium2_raw',
         '--add-data',str(ROOT/'extension')+':bionic_pdf/reader',
         '--add-data',str(stamp)+':bionic_pdf',
         '--distpath',str(ROOT/'dist'),'--workpath',str(ROOT/'build/windows'),
         '--specpath',str(ROOT/'build'),str(ROOT/'scripts/app_entry.py')]
subprocess.run(command,check=True,cwd=ROOT)
subprocess.run([sys.executable,str(ROOT/'scripts/collect_licenses.py')],check=True,cwd=ROOT)
