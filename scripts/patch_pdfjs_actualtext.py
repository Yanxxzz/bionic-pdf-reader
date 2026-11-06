"""Apply a version-checked PDF.js 5.6.205 operator metadata patch.

The extra argument carries decoded ActualText to the main-thread renderer.
It changes neither PDF bytes nor the upstream text-extraction implementation.
"""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'extension/vendor/pdf.worker.min.mjs'
source=path.read_text(encoding='utf-8')
old='e=[e[0].name,e[1]instanceof Dict?e[1].get("MCID"):null];break;'
new='e=[e[0].name,e[1]instanceof Dict?e[1].get("MCID"):null,e[1]instanceof Dict&&typeof e[1].get("ActualText")==="string"?stringToPDFString(e[1].get("ActualText")):null];break;'
if new not in source:
    assert source.count(old)==1,'Unexpected PDF.js worker; review the upstream operator handling'
    source=source.replace(old,new)
    source='/* Bionic PDF Reader modification: forward decoded ActualText as an additional marked-content operator argument. */\n'+source
    path.write_text(source,encoding='utf-8',newline='\n')
print('PDF.js ActualText operator metadata patch present')
