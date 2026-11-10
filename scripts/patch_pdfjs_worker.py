"""Reapply the Bionic PDF Reader hooks to the pinned PDF.js 5.6.205 worker."""
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
marker = 'type:"beginMarkedContentProps",id:Number.isInteger(e)?'
with_text = ('type:"beginMarkedContentProps",actualText:j[1]instanceof Dict&&typeof j[1].get("ActualText")'
             '==="string"?stringToPDFString(j[1].get("ActualText")):null,id:Number.isInteger(e)?')
if with_text not in source:
    assert source.count(marker) == 1, 'Unexpected PDF.js marked-content text handling'
    source = source.replace(marker, with_text)

hook = 'h.on("BionicResumeProof",()=>bionicStreamProof(n.pdfDocument.stream));'
if hook not in source:
    marker = 'h.on("GetData",function(e){return n.requestLoadedStream().then(e=>e.bytes)});'
    assert source.count(marker) == 1, 'Unexpected PDF.js worker document transport'
    source = ('/* Bionic PDF Reader modification: verify received byte ranges on a reader-tab reload. */\n'
              'import {streamByteProof as bionicStreamProof} from "../reading-progress.mjs";\n'
              + source.replace(marker, marker + hook))
path.write_text(source, encoding='utf-8', newline='\n')
