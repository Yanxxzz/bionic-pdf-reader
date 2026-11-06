"""Collect upstream license texts accompanying the standalone distribution."""
from pathlib import Path
from importlib import metadata
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    target=ROOT/'dist/third-party-licenses';target.mkdir(parents=True,exist_ok=True)
    for name in ('pypdf','fonttools','regex','jieba','tinysegmenter','pyinstaller','setuptools','packaging'):
        dist=metadata.distribution(name)
        for file in dist.files or []:
            if any(part.lower().startswith(('license','copying','notice')) for part in file.parts):
                source=Path(dist.locate_file(file))
                if source.is_file():
                    directory=target/name;directory.mkdir(exist_ok=True)
                    shutil.copy2(source,directory/(file.name))
    base=Path(sys.base_prefix)
    for label,path in [('Python',base/'LICENSE.txt'),('Python',base/'LICENSE'),('Tcl',base/'tcl/tcl8.6/license.terms'),('Tk',base/'tcl/tk8.6/license.terms')]:
        if path.is_file():shutil.copy2(path,target/(label+'-'+path.name))
    shutil.copy2(ROOT/'THIRD_PARTY_NOTICES.md',target/'THIRD_PARTY_NOTICES.md')
    print('Collected',len(list(target.rglob('*'))),'license paths')

if __name__=='__main__':main()
