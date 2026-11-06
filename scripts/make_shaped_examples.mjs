// Browser-generated fixtures exercise split drawing runs, ligatures and accents.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const samples=JSON.parse(fs.readFileSync(path.join(root,'examples/shaping-cases.json'),'utf8'));
const fonts=[...new Set(samples.map(s=>s.font))];
const css=fonts.map(font=>`@font-face{font-family:"${font}";src:url(data:font/ttf;base64,${fs.readFileSync(path.join(root,'tests/assets/fonts',font+'.ttf')).toString('base64')})}`).join('');
const escape=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const html=`<!doctype html><meta charset="utf-8"><title>Original multilingual reading samples</title><style>${css}@page{size:A4;margin:28mm 20mm}body{margin:0}section{break-after:page}section:last-child{break-after:auto}h1{font:700 16px Arial;color:#285442;direction:ltr;text-align:left;margin:0 0 40px}p{font-size:20px;line-height:2;color:#202b26;margin:0 0 32px}small{font:12px Arial;direction:ltr;display:block;margin-top:48px;color:#66756c}</style>`+
samples.map(s=>`<section lang="${s.code}" dir="${s.dir}" style="font-family:'${s.font}'"><h1>ORIGINAL SHAPED SAMPLE / ${s.code.toUpperCase()}</h1><p>${escape(s.text)}</p><p>${escape(s.text)}</p><small>Bionic PDF Reader — original test content, Noto OFL fonts.</small></section>`).join('');
const browser=await chromium.launch({headless:true,...(process.env.FIXTURE_CHANNEL?{channel:process.env.FIXTURE_CHANNEL}:{})});
try{
  const page=await browser.newPage();await page.setContent(html);await page.evaluate(()=>document.fonts.ready);
  const output=path.join(root,'.tmp/examples');fs.mkdirSync(output,{recursive:true});
  for(const tagged of [true,false])await page.pdf({path:path.join(output,`shaped-${tagged?'tagged':'plain'}.pdf`),printBackground:true,preferCSSPageSize:true,tagged});
  console.log('Created shaped PDFs for',samples.map(s=>s.code).join(', '));
}finally{await browser.close();}
