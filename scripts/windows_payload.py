"""Match a frozen Windows reader to the Python sources and browser assets shipped with it."""
import hashlib
from zipfile import ZipFile


def backend_digest(files):
    digest = hashlib.sha256()
    for name, content in sorted(files):
        digest.update(name.encode('utf-8') + b'\0' + hashlib.sha256(content).digest())
    return digest.hexdigest().encode('ascii')


def source_digest(package):
    return backend_digest((path.relative_to(package).as_posix(), path.read_bytes())
                          for path in package.rglob('*.py'))


def verify_executable(executable, browser_zip, expected_backend):
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(executable))
    entries = {name.replace('\\', '/'): name for name in archive.toc}
    stamp = entries.get('bionic_pdf/backend.sha256')
    if stamp is None or archive.extract(stamp) != expected_backend:
        raise ValueError('BionicPDF.exe 的桌面代码与当前包不匹配，请重新运行 scripts/build_windows.py。')

    prefix = 'bionic_pdf/reader/'
    embedded = {key.removeprefix(prefix): entry for key, entry in entries.items() if key.startswith(prefix)}
    with ZipFile(browser_zip) as browser:
        assets = set(browser.namelist()) - {'LICENSE', '使用指南.html'}
        if assets != embedded.keys():
            raise ValueError('BionicPDF.exe 内置阅读器的文件清单与浏览器包不匹配。')
        for name in sorted(assets):
            if archive.extract(embedded[name]) != browser.read(name):
                raise ValueError(f'BionicPDF.exe 内置的 {name} 与浏览器包不匹配。')
