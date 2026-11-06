from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
         '--name','BionicPDF','--paths',str(ROOT/'src'),
         '--collect-all','regex','--add-data',str(ROOT/'extension')+':reader',
         '--distpath',str(ROOT/'dist'),'--workpath',str(ROOT/'build/windows'),
         '--specpath',str(ROOT/'build'),str(ROOT/'scripts/app_entry.py')]
subprocess.run(command,check=True,cwd=ROOT)
subprocess.run([sys.executable,str(ROOT/'scripts/collect_licenses.py')],check=True,cwd=ROOT)
