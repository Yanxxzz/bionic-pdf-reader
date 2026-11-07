"""Verify the six downloadable packages and their published checksum manifest."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import tarfile
import tomllib
import zipfile


def audit(folder,version):
    hashes={name:digest for digest,name in (line.split('  ',1) for line in (folder/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines())}
    expected={f'bionic-pdf-{name}-{version}.zip' for name in ('chrome-edge','firefox-temporary','web-reader','windows-x64')}
    expected|={f'bionic_pdf_reader-{version}-py3-none-any.whl',f'bionic_pdf_reader-{version}.tar.gz'}
    assert set(hashes)==expected,'The manifest must match the published packages exactly'
    for name,digest in hashes.items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest,name

    def check_paths(names):
        for name in names:
            path=PurePosixPath(name)
            assert not path.is_absolute() and '..' not in path.parts and '\\' not in name,name
            assert not name.lower().endswith('.pdf'),name
            assert not any(part in ('.git','node_modules','.env') for part in path.parts),name

    for name in sorted(expected):
        path=folder/name
        if name.endswith('.tar.gz'):
            with tarfile.open(path) as archive:
                check_paths(archive.getnames())
                assert any(n.endswith('/src/bionic_pdf/layout.py') for n in archive.getnames())
            continue
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None,name
            names=archive.namelist();check_paths(names)
            if name.endswith('.whl'):
                assert {'bionic_pdf/layout.py','bionic_pdf/embedded_font.py'}<=set(names)
                assert version in archive.read('bionic_pdf/__init__.py').decode()
                continue
            guide=archive.read('使用指南.html').decode('utf-8')
            assert version in guide and '乌克兰语' in guide and '希腊语' in guide
            if 'windows-x64' not in name:assert {'reader.mjs','page-view.mjs','layout.mjs','compat.mjs','pdf-worker.mjs'}<=set(names)
            if 'windows-x64' in name:
                assert 'BionicPDF.exe' in names and 'LICENSE' in names
                assert any(n.startswith('third-party-licenses/pypdf/') for n in names)
                assert any(n.startswith('third-party-licenses/fonttools/') for n in names)
            elif 'web-reader' in name:
                assert 'manifest.json' not in names and 'layout.mjs' in names
            else:
                manifest=json.loads(archive.read('manifest.json'))
                assert manifest['version']==version
                assert 'layout.mjs' in names and 'vendor/LICENSE_PDFJS' in names
                if 'firefox-temporary' in name:
                    assert manifest['background']=={'scripts':['background.js']}
                else:assert manifest['background']=={'service_worker':'background.js'}
    print('Verified six release packages, exact checksums, guides, licenses and archive contents')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    version=tomllib.loads((Path(__file__).resolve().parents[1]/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    parser.add_argument('folder',type=Path);parser.add_argument('version',nargs='?',default=version)
    args=parser.parse_args();audit(args.folder,args.version)
