"""Release artifacts must identify the same build on every packaging run."""
import base64
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

import pytest

from scripts.windows_payload import source_digest, verify_executable


def test_browser_packages_ignore_build_and_checkout_times(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for name in ('LICENSE', 'pyproject.toml', 'extension/manifest.json', 'extension/reader.html',
                 'extension/assets/reading-room.png', 'scripts/offline_guide.html',
                 'scripts/build_packages.py', 'scripts/windows_payload.py'):
        dest = tmp_path/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/name, dest)

    def build():
        subprocess.run([sys.executable, 'scripts/build_packages.py'], cwd=tmp_path, check=True, capture_output=True)
        return {p.name: p.read_bytes() for p in (tmp_path/'dist').glob('*.zip')}

    first = build()
    os.utime(tmp_path/'LICENSE', (946684800, 946684800))
    assert build() == first
    assert len(first) == 3
    for name in first:
        with ZipFile(tmp_path/'dist'/name) as archive:
            assert len({entry.date_time for entry in archive.infolist()}) == 1
            guide = archive.read('使用指南.html')
            photo = archive.read('assets/reading-room.png')
            assert b'data:image/png;base64,' + base64.b64encode(photo) in guide
            assert b'<form' not in guide


def test_stale_windows_payload_is_rejected(tmp_path):
    writer = pytest.importorskip('PyInstaller.archive.writers').CArchiveWriter
    backend, reader, stamp = (tmp_path/name for name in ('words.py', 'words.mjs', 'backend.sha256'))
    backend.write_text('version = 1')
    reader.write_text('export const version = 1')
    stamp.write_bytes(source_digest(tmp_path))

    executable = tmp_path/'BionicPDF.exe'
    writer(str(executable), [('bionic_pdf/backend.sha256', str(stamp), True, 'x'),
                             ('bionic_pdf/reader/words.mjs', str(reader), True, 'x')], 'python.dll')
    browser = tmp_path/'browser.zip'
    with ZipFile(browser, 'w') as archive:
        archive.write(reader, reader.name)
    verify_executable(executable, browser, stamp.read_bytes())

    backend.write_text('version = 2')
    with pytest.raises(ValueError, match='桌面代码'):
        verify_executable(executable, browser, source_digest(tmp_path))
    with ZipFile(browser, 'w') as archive:
        archive.writestr(reader.name, 'export const version = 2')
    with pytest.raises(ValueError, match='words.mjs'):
        verify_executable(executable, browser, stamp.read_bytes())
