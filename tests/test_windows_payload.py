"""The same version number can label two different desktop or browser builds."""
from zipfile import ZipFile

import pytest

from scripts.windows_payload import source_digest, verify_executable


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
