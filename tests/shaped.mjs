import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';import {chromium,firefox} from 'playwright';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..'),app=path.join(root,'extension');
const samples=JSON.parse(fs.readFileSync(path.join(root,'examples/shaping-cases.json'),'utf8'));
const mime={'.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.html':'text/html; charset=utf-8','.wasm':'application/wasm'};
const server=http.createServer((req,res)=>{const file=path.resolve(app,'.'+new URL(req.url,'http://localhost').pathname);if(!file.startsWith(app+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404).end();return;}res.setHeader('Content-Type',mime[path.extname(file)]||'application/octet-stream');fs.createReadStream(file).pipe(res);});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const output=path.join(root,'test-results');fs.mkdirSync(output,{recursive:true});const report=[];
try{
 for(const name of (process.env.BROWSERS||'chromium,firefox').split(',')){
  const engine=name==='firefox'?firefox:chromium,options={headless:true};if(name==='chrome'||name==='edge')options.channel=name==='edge'?'msedge':'chrome';
  const browser=await engine.launch(options);
  try{
   const page=await browser.newPage({viewport:{width:1440,height:1040}}),errors=[],external=[];
   page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:')&&!/^(blob:|data:)/.test(r.url()))external.push(r.url());});
   await page.goto(`http://127.0.0.1:${server.address().port}/reader.html`);
   let originalEnglish;
   for(const variant of ['tagged','plain']){
    await page.evaluate(()=>{for(const key of Object.keys(localStorage))if(key.startsWith('bionic-page-'))localStorage.removeItem(key);});
    await page.locator('#file-input').setInputFiles(path.join(root,`.tmp/examples/shaped-${variant}.pdf`));
    await page.waitForFunction(()=>document.querySelector('#page-frame').dataset.mode==='original'&&document.querySelector('#text-layer').textContent.includes('Reading becomes'));
    for(let i=0;i<samples.length;i++){
     if(i){await page.locator('#page-number').fill(String(i+1));await page.locator('#page-number').press('Enter');await page.waitForFunction(n=>document.querySelector('#page-frame').dataset.renderedPage===String(n)&&document.querySelector('#page-frame').dataset.mode==='original',i+1);}
     const revision=await page.locator('#page-frame').getAttribute('data-render-revision');
     await page.locator('#language').selectOption(samples[i].code);
     await page.waitForFunction(r=>document.querySelector('#page-frame').dataset.renderRevision!==r,revision);
     const normalize=s=>s.normalize('NFC').replace(/\s+/gu,' ');
     const text=await page.locator('#text-layer').textContent(),expected=normalize(samples[i].text);
     const sameWords=(actual,wanted)=>normalize(actual).replace(/\s/gu,'').includes(normalize(wanted).replace(/\s/gu,''));
     assert.ok(sameWords(text,expected),`${name} ${variant} ${samples[i].code}: logical text: ${JSON.stringify(text)}`);
     assert.ok(!text.includes('\0'),`${name} ${samples[i].code}: no missing ActualText`);
     const selected=await page.locator('#text-layer').evaluate(layer=>{const r=document.createRange();r.selectNodeContents(layer);const s=getSelection();s.removeAllRanges();s.addRange(r);const text=s.toString();s.removeAllRanges();return text;});
     assert.ok(normalize(selected).includes(expected),`${name} ${samples[i].code}: selection/copy order and word spaces: ${JSON.stringify(selected)}`);
     const pixels=await page.locator('#pdf-canvas').evaluate(c=>c.toDataURL());
     if (variant === 'tagged' && i === 0) originalEnglish = pixels;
     await page.locator('#bionic-mode').click();await page.waitForFunction(()=>document.querySelector('#page-frame').dataset.mode==='bionic');
     assert.equal(await page.locator('#text-layer').textContent(),text);
     assert.ok(Number(await page.locator('#pdf-canvas').getAttribute('data-bold-glyphs'))>0);
     assert.notEqual(await page.locator('#pdf-canvas').evaluate(c=>c.toDataURL()),pixels);
     if(variant==='tagged')await page.screenshot({path:path.join(output,`${name}-shaped-${samples[i].code}.png`)});
     await page.locator('#original-mode').click();await page.waitForFunction(()=>document.querySelector('#page-frame').dataset.mode==='original');
     assert.equal(await page.locator('#pdf-canvas').evaluate(c=>c.toDataURL()),pixels);
     report.push({browser:name,version:browser.version(),variant,language:samples[i].code,logicalText:true,selection:true,originalPixelsRestored:true});
    }
   }
   const pixels = () => page.locator('#pdf-canvas').evaluate(canvas => canvas.toDataURL());
   async function openFirstPage(variant) {
    const name = 'shaped-' + variant + '.pdf';
    await page.locator('#file-input').setInputFiles(path.join(root, '.tmp/examples', name));
    await page.waitForFunction(name => document.querySelector('#file-name').textContent === name &&
      document.querySelector('#page-frame').dataset.renderState === 'ready', name);
    await page.locator('#page-number').fill('1');
    await page.locator('#page-number').press('Enter');
    await page.waitForFunction(() => document.querySelector('#page-frame').dataset.renderedPage === '1');
   }
   await openFirstPage('switchable');
   assert.ok(await page.locator('#strength').isDisabled() && await page.locator('#rule').isDisabled());
   assert.equal(await pixels(), originalEnglish);
   await page.locator('#bionic-mode').click();
   await page.waitForFunction(() => document.querySelector('#page-frame').dataset.mode === 'bionic');
   const prepared = await pixels();
   assert.notEqual(prepared, originalEnglish);
   assert.equal(await page.locator('#pdf-canvas').getAttribute('data-bold-glyphs'), '0');
   await page.locator('#original-mode').click();
   await page.waitForFunction(() => document.querySelector('#page-frame').dataset.mode === 'original');
   assert.equal(await pixels(), originalEnglish);
   await openFirstPage('static');
   assert.equal(await pixels(), prepared, 'The switch shows the exported strokes at their original weight');
   assert.ok(await page.locator('#strength').isEnabled() && await page.locator('#rule').isEnabled());
   assert.deepEqual(errors,[]);assert.deepEqual(external,[]);console.log(name,'shaped scripts, ActualText, selection and toggles passed');
  }finally{await browser.close();}
 }
}finally{fs.writeFileSync(path.join(output,'shaped-report.json'),JSON.stringify(report,null,2));await new Promise(r=>server.close(r));}
