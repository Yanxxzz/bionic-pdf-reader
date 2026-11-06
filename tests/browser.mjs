import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {chromium,firefox} from 'playwright';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const app=path.join(root,'extension'),pdf=path.join(root,'.tmp/examples/multilingual.pdf');
const output=path.join(root,'test-results');fs.mkdirSync(output,{recursive:true});
const mime={'.mjs':'text/javascript','.js':'text/javascript','.html':'text/html; charset=utf-8','.css':'text/css','.wasm':'application/wasm'};
const server=http.createServer((req,res)=>{
  const file=path.resolve(app,'.'+decodeURIComponent(new URL(req.url,'http://localhost').pathname));
  if(!file.startsWith(app+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404).end();return;}
  res.setHeader('Content-Type',mime[path.extname(file)]||'application/octet-stream');fs.createReadStream(file).pipe(res);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const reports=[];
try{
  for(const name of (process.env.BROWSERS||'chromium,firefox').split(',')){
    const engine=name==='firefox'?firefox:chromium;
    const options={headless:true};if(name==='chrome'||name==='edge')options.channel=name==='edge'?'msedge':'chrome';
    const browser=await engine.launch(options);
    const page=await browser.newPage({viewport:{width:1440,height:1040}});
    const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:')&&!/^(blob:|data:)/.test(r.url()))external.push(r.url());});
    try{
      await page.goto(`http://127.0.0.1:${server.address().port}/reader.html`);
      await page.locator('#file-input').setInputFiles(pdf);
      await page.waitForFunction(()=>document.querySelector('#page-frame').dataset.renderedPage==='1');
      const pages=Number(await page.locator('#page-count').textContent());
      const wait=async(n,mode)=>page.waitForFunction(({n,mode})=>{const f=document.querySelector('#page-frame');return f.dataset.renderedPage===String(n)&&f.dataset.mode===mode;},{n,mode});
      for(let n=1;n<pages;n++){
        if(n>1){await page.locator('#page-number').fill(String(n));await page.locator('#page-number').press('Enter');await wait(n,'original');}
        const text=await page.locator('#text-layer').textContent();
        const pixels=await page.locator('#pdf-canvas').evaluate(c=>c.toDataURL());
        const geometry=await page.locator('#pdf-canvas').evaluate(c=>[c.width,c.height]);
        await page.locator('#bionic-mode').click();await wait(n,'bionic');
        assert.equal(await page.locator('#text-layer').textContent(),text);
        assert.deepEqual(await page.locator('#pdf-canvas').evaluate(c=>[c.width,c.height]),geometry);
        assert.ok(Number(await page.locator('#pdf-canvas').getAttribute('data-bold-glyphs'))>0,`${name} page ${n}`);
        assert.notEqual(await page.locator('#pdf-canvas').evaluate(c=>c.toDataURL()),pixels);
        if(n===1)await page.screenshot({path:path.join(output,`${name}-reading.png`)});
        await page.keyboard.press('Alt+b');await wait(n,'original');
        assert.equal(await page.locator('#pdf-canvas').evaluate(c=>c.toDataURL()),pixels);
      }
      await page.locator('#zoom').selectOption('1.25');
      await page.locator('#page-number').fill('1');await page.locator('#page-number').press('Enter');await wait(1,'original');
      await page.locator('#language').selectOption('fr');await page.locator('#bionic-mode').click();await wait(1,'bionic');
      const previous=await page.locator('#page-frame').getAttribute('data-render-revision');
      await page.locator('#file-input').setInputFiles(pdf);
      await page.waitForFunction(r=>document.querySelector('#page-frame').dataset.renderRevision!==r,previous);
      assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
      reports.push({browser:name,version:browser.version(),pages:pages-1,textPreserved:true,originalPixelsRestored:true,noExternalRequests:true});
      console.log(name, 'passed',pages-1,'language pages');
    }finally{await browser.close();}
  }
}finally{
  fs.writeFileSync(path.join(output,'browser-report.json'),JSON.stringify(reports,null,2));
  await new Promise(resolve=>server.close(resolve));
}
