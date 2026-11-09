"""Create reproducible extension/web ZIPs and SHA256 checksums offline."""
import base64
import hashlib
import json
import re
from pathlib import Path
from string import Template
import zipfile
import tomllib
from windows_payload import source_digest, verify_executable

ROOT=Path(__file__).resolve().parents[1]

def offline_guide(source, version):
    reader = (source/'reader.html').read_text(encoding='utf-8')
    dialog = re.search(r'<dialog id="help-dialog"[^>]*>(.*?)</dialog>', reader, re.S).group(1)
    title = re.search(r'<h2 id="help-title">(.*?)</h2>', dialog, re.S).group(1)
    intro = re.search(r'<p class="guide-intro">(.*?)</p>', dialog, re.S).group(1)
    sections = '\n'.join(re.findall(r'<details\b.*?</details>', dialog, re.S))
    cover = base64.b64encode((source/'assets/reading-room.png').read_bytes()).decode('ascii')
    template = Template((ROOT/'scripts/offline_guide.html').read_text(encoding='utf-8'))
    return template.substitute(title=title, intro=intro, sections=sections,
                               cover=cover, version=version).encode('utf-8')


def write_web_asset(archive, name, data):
    entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
    entry.create_system = 3  # Use the same Unix file attributes on every build host.
    entry.external_attr = 0o100644 << 16
    archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main():
    version=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    source=ROOT/'extension'
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['version']==version
    guide = offline_guide(source, version)
    packages=[]
    assets = sorted(path.relative_to(source).as_posix() for path in source.rglob('*') if path.is_file())
    for target in ('chrome-edge','firefox-temporary','web-reader'):
        name=f'bionic-pdf-{target}-{version}.zip'
        packages.append(out/name)
        with zipfile.ZipFile(out/name,'w') as writer:
            for rel in assets:
                if target=='web-reader' and rel in ('manifest.json','background.js'):continue
                data=(source/rel).read_bytes()
                if target=='firefox-temporary' and rel=='manifest.json':
                    firefox=dict(manifest);firefox.pop('minimum_chrome_version',None)
                    firefox['background']={'scripts':['background.js']}
                    firefox['browser_specific_settings']={'gecko':{'id':'bionic-pdf-reader@yanxxzz','strict_min_version':'128.0','data_collection_permissions':{'required':['none']}}}
                    data=(json.dumps(firefox,ensure_ascii=False,indent=2)+'\n').encode()
                write_web_asset(writer,rel,data)
            write_web_asset(writer,'LICENSE',(ROOT/'LICENSE').read_bytes())
            write_web_asset(writer,'使用指南.html',guide)
    if (out/'BionicPDF.exe').is_file():
        verify_executable(out/'BionicPDF.exe', out/f'bionic-pdf-chrome-edge-{version}.zip',
                          source_digest(ROOT/'src/bionic_pdf'))
        packages.append(out/f'bionic-pdf-windows-x64-{version}.zip')
        with zipfile.ZipFile(out/f'bionic-pdf-windows-x64-{version}.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as writer:
            writer.write(out/'BionicPDF.exe','BionicPDF.exe')
            writer.write(ROOT/'LICENSE','LICENSE')
            writer.write(ROOT/'docs/usage.md','使用说明.md')
            writer.writestr('使用指南.html',guide)
            for path in sorted((out/'third-party-licenses').rglob('*')):
                if path.is_file():writer.write(path,path.relative_to(out).as_posix())
    # Only files published as release assets, not the intermediate executable.
    packages.extend(out/name for name in (f'bionic_pdf_reader-{version}-py3-none-any.whl',f'bionic_pdf_reader-{version}.tar.gz') if (out/name).is_file())
    files=sorted(packages)
    (out/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in files),encoding='utf-8')
    print('\n'.join(str(p) for p in files))

if __name__=='__main__':main()
