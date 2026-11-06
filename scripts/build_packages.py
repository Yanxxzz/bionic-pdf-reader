"""Create reproducible extension/web ZIPs and SHA256 checksums offline."""
import hashlib
import json
import re
from pathlib import Path
import zipfile
import tomllib

ROOT=Path(__file__).resolve().parents[1]

def main():
    version=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    source=ROOT/'extension'
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['version']==version
    content=re.search(r'<dialog id="help-dialog"[^>]*>(.*?)</dialog>',(source/'reader.html').read_text(encoding='utf-8'),re.S).group(1)
    content=re.sub(r'<form\b.*?</form>','',content,flags=re.S)
    guide=('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>仿生 PDF 阅读 · 使用指南</title><style>body{font:16px/1.85 system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 24px;color:#22363a}details{border-top:1px solid #dce3da;padding:14px 0}summary{font-weight:600;cursor:pointer}a{color:#17655d}</style>'+content+'<p>版本 '+version+' · <a href="https://github.com/Yanxxzz/bionic-pdf-reader">项目主页与更新</a></p></html>').encode('utf-8')
    packages=[]
    for target in ('chrome-edge','firefox-temporary','web-reader'):
        name=f'bionic-pdf-{target}-{version}.zip'
        packages.append(out/name)
        with zipfile.ZipFile(out/name,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as writer:
            for path in sorted(source.rglob('*')):
                if not path.is_file():continue
                rel=path.relative_to(source).as_posix()
                if target=='web-reader' and rel in ('manifest.json','background.js'):continue
                data=path.read_bytes()
                if target=='firefox-temporary' and rel=='manifest.json':
                    firefox=dict(manifest);firefox.pop('minimum_chrome_version',None)
                    firefox['background']={'scripts':['background.js']}
                    firefox['browser_specific_settings']={'gecko':{'id':'bionic-pdf-reader@yanxxzz','strict_min_version':'128.0','data_collection_permissions':{'required':['none']}}}
                    data=(json.dumps(firefox,ensure_ascii=False,indent=2)+'\n').encode()
                info=zipfile.ZipInfo(rel,(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                writer.writestr(info,data)
            writer.write(ROOT/'LICENSE','LICENSE')
            writer.writestr('使用指南.html',guide)
    if (out/'BionicPDF.exe').is_file():
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
