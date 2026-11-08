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
    if(process.env.FORCE_LEGACY_STREAMS==='1')await page.addInitScript(()=>Object.defineProperty(ReadableStream.prototype,Symbol.asyncIterator,{value:undefined,configurable:true,writable:true}));
    const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:')&&!/^(blob:|data:)/.test(r.url()))external.push(r.url());});
    try{
      await page.goto(`http://127.0.0.1:${server.address().port}/reader.html`);
      assert.deepEqual(await page.locator('#language option').evaluateAll(options=>options.map(o=>o.value)),['auto','en','fr','de','es','pt','it','nl','pl','tr','vi','ru','uk','el']);
      await page.locator('#help-button').click();
      assert.equal(await page.locator('#help-dialog').evaluate(d=>d.open),true);
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#help-dialog').evaluate(d=>d.open),false);
      await page.setViewportSize({width:375,height:812});
      const helpBounds=await page.locator('#help-button').boundingBox();
      assert.ok(helpBounds.x>=0&&helpBounds.x+helpBounds.width<=375,'Guide remains reachable on a narrow screen');
      await page.locator('#help-button').click();
      assert.equal(await page.locator('#help-dialog').evaluate(d=>d.open),true);
      await page.keyboard.press('Escape');
      await page.setViewportSize({width:1440,height:1040});
      async function chooseSample(button, file = pdf) {
        const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.locator(button).click()]);
        await chooser.setFiles(file);
      }
      const damaged = {name:'damaged.pdf', mimeType:'application/pdf', buffer:Buffer.from('%PDF-1.4\nbroken\n%%EOF')};
      const waitForOpenError = () => page.waitForFunction(() => {
        const message = document.querySelector('#message');
        return !message.hidden && message.textContent.includes('无法打开 PDF');
      });
      await chooseSample('#choose-file', damaged);
      await waitForOpenError();
      assert.ok(await page.locator('#welcome').isVisible());
      await chooseSample('#choose-file');
      await page.waitForFunction(()=>document.querySelector('#page-frame').dataset.renderedPage==='1');
      const pages=Number(await page.locator('#page-count').textContent());
      const wait=async(n,mode)=>page.waitForFunction(({n,mode})=>{const f=document.querySelector('#page-frame');return f.dataset.renderedPage===String(n)&&f.dataset.mode===mode;},{n,mode});
      // Old or damaged settings can coexist with a valid language preference.
      await page.evaluate(() => {
        const progress = Object.keys(localStorage).find(key => key.startsWith('bionic-page-'));
        localStorage.setItem(progress, '2.5');
        localStorage.setItem('bionic-pdf-settings', JSON.stringify({locale:'fr', rule:'retired', enabled:'false', strength:99}));
      });
      await page.reload();
      await page.waitForSelector('html[data-reader-ready]');
      assert.equal(await page.locator('#language').inputValue(), 'fr');
      assert.equal(await page.locator('#rule').inputValue(), 'reference');
      assert.equal(await page.locator('#strength-value').textContent(), '100%');
      assert.equal(await page.locator('#original-mode').getAttribute('aria-pressed'), 'true');
      await chooseSample('#choose-file');
      await wait(1, 'original');
      assert.equal(await page.locator('#page-number').inputValue(), '1');
      // A mode change can supersede the render requested by a page turn.
      const previousScroll = await page.evaluate(() => {
        const scroller = document.querySelector('#page-scroller');
        scroller.scrollTop = 250;
        const top = scroller.scrollTop;
        document.querySelector('#next-page').click();
        document.querySelector('#bionic-mode').click();
        return top;
      });
      assert.ok(previousScroll > 0);
      await wait(2, 'bionic');
      assert.equal(await page.locator('#page-scroller').evaluate(el => el.scrollTop), 0);
      await page.locator('#page-number').fill('');
      await page.locator('#page-number').press('Enter');
      assert.equal(await page.locator('#page-number').inputValue(), '2');
      assert.equal(await page.locator('#page-frame').getAttribute('data-rendered-page'), '2');
      const previousPixels = await page.locator('#pdf-canvas').evaluate(canvas => canvas.toDataURL());
      const previousText = await page.locator('#text-layer').textContent();
      await chooseSample('#open-file', damaged);
      await waitForOpenError();
      assert.equal(await page.locator('#file-name').textContent(), path.basename(pdf));
      assert.equal(await page.locator('#page-number').inputValue(), '2');
      assert.equal(await page.locator('#reading-status').textContent(), '仿生模式 · 词首加粗');
      assert.equal(await page.locator('#text-layer').textContent(), previousText);
      assert.equal(await page.locator('#pdf-canvas').evaluate(canvas => canvas.toDataURL()), previousPixels);
      const locked = path.join(path.dirname(pdf), 'locked.pdf');
      await chooseSample('#open-file', locked);
      const password = page.locator('#pdf-password');
      await password.fill('incorrect');
      await password.press('Enter');
      await page.getByText('密码不正确，请重试', {exact:true}).waitFor();
      await password.press('Escape');
      await page.getByRole('alert').filter({hasText:'已取消打开'}).waitFor();
      await page.locator('#outline').getByRole('button', {name:'de', exact:true}).click();
      await wait(3, 'bionic');
      await page.locator('#prev-page').click();
      await wait(2, 'bionic');
      await page.locator('#prev-page').click();
      await page.locator('#original-mode').click();
      await wait(1, 'original');
      for(let n=1;n<pages;n++){
        if(n>1){await page.locator('#page-number').fill(String(n));await page.locator('#page-number').press('Enter');await wait(n,'original');}
        const text=await page.locator('#text-layer').textContent();
        const pixels=await page.locator('#pdf-canvas').evaluate(c=>c.toDataURL());
        const geometry=await page.locator('#pdf-canvas').evaluate(c=>[c.width,c.height]);
        let selection;
        if(n===1){
          selection=await page.locator('#text-layer').evaluate(layer=>{
            const range=document.createRange(),selected=getSelection();
            range.selectNodeContents([...layer.querySelectorAll('span')].find(span=>span.textContent.trim()));
            selected.removeAllRanges();selected.addRange(range);
            return selected.toString();
          });
          assert.ok(selection.trim());
        }
        await page.locator('#bionic-mode').click();await wait(n,'bionic');
        assert.equal(await page.locator('#text-layer').textContent(),text);
        assert.deepEqual(await page.locator('#pdf-canvas').evaluate(c=>[c.width,c.height]),geometry);
        assert.ok(Number(await page.locator('#pdf-canvas').getAttribute('data-bold-glyphs'))>0,`${name} page ${n}`);
        assert.notEqual(await page.locator('#pdf-canvas').evaluate(c=>c.toDataURL()),pixels);
        if(n===1){
          assert.equal(await page.evaluate(()=>getSelection().toString()),selection,'The toolbar preserves the selected text');
          await page.screenshot({path:path.join(output,`${name}-reading.png`)});
        }
        await page.keyboard.press('Alt+b');await wait(n,'original');
        assert.equal(await page.locator('#pdf-canvas').evaluate(c=>c.toDataURL()),pixels);
        if(n===1){
          assert.equal(await page.evaluate(()=>getSelection().toString()),selection,'Mode switches preserve the selected text');
          await page.evaluate(()=>getSelection().removeAllRanges());
        }
      }
      await page.locator('#zoom').selectOption('1.25');
      await page.locator('#page-number').fill('1');await page.locator('#page-number').press('Enter');await wait(1,'original');
      await page.locator('#language').selectOption('fr');await page.locator('#bionic-mode').click();await wait(1,'bionic');
      const strokes=()=>page.locator('#pdf-canvas').getAttribute('data-bold-glyphs');
      const half=await strokes();
      const sample = page.locator('#sample-word b');
      const halfPreview = await sample.textContent();
      await page.locator('#language').selectOption('en');await wait(1,'bionic');
      assert.notEqual(await strokes(),half,'Changing language updates English reference prefixes');
      assert.notEqual(await sample.textContent(), halfPreview);
      await page.locator('#rule').selectOption('half');await wait(1,'bionic');
      assert.equal(await strokes(),half,'Changing the rule restores half-word prefixes');
      assert.equal(await sample.textContent(), halfPreview);
      const previous=await page.locator('#page-frame').getAttribute('data-render-revision');
      // Finish an older file read after a newer document has been accepted.
      await page.evaluate(() => {
        const slow = new File(['invalid PDF'], 'slow.pdf', {type:'application/pdf'});
        slow.arrayBuffer = () => new Promise((_, reject) => {
          window.finishOldRead = () => reject(new Error('superseded read'));
        });
        const transfer = new DataTransfer();
        transfer.items.add(slow);
        document.dispatchEvent(new DragEvent('drop', {dataTransfer:transfer}));
      });
      await page.waitForFunction(() => typeof window.finishOldRead === 'function');
      await chooseSample('#open-file', locked);
      await password.fill('reader-test');
      await password.press('Enter');
      await page.waitForFunction(r=>document.querySelector('#page-frame').dataset.renderRevision!==r,previous);
      assert.equal(await page.locator('#file-name').textContent(), 'locked.pdf');
      assert.match(await page.locator('#text-layer').textContent(), /Password protected example/);
      await page.evaluate(() => window.finishOldRead());
      assert.ok(await page.locator('#message').isHidden());
      await chooseSample('#open-file', locked);
      await password.waitFor();
      await page.locator('#file-input').setInputFiles(pdf);
      await page.waitForFunction(() => document.querySelector('#file-name').textContent === 'multilingual.pdf');
      await wait(1, 'bionic');
      assert.ok(await page.locator('#password-dialog').isHidden());
      const copyBlocked = () => page.locator('#text-layer').evaluate(layer => {
        const selection = getSelection(), range = document.createRange();
        range.selectNodeContents(layer); selection.removeAllRanges(); selection.addRange(range);
        return !layer.dispatchEvent(new Event('copy', {bubbles:true, cancelable:true}));
      });
      assert.equal(await copyBlocked(), false);
      await chooseSample('#open-file', path.join(root,'.tmp/examples/restricted.pdf'));
      await page.waitForFunction(() => document.querySelector('#file-name').textContent === 'restricted.pdf');
      for (const mode of ['original', 'bionic']) {
        await page.locator('#'+mode+'-mode').click();
        await wait(1, mode);
        assert.equal(await copyBlocked(), true);
        await page.evaluate(() => getSelection().removeAllRanges());
        await page.getByRole('link', {name:'Next chapter'}).click();
        await wait(2, mode);
        assert.match(await page.locator('#text-layer').textContent(), /Second chapter/);
        await page.locator('#return-position').click();
        await wait(1, mode);
        assert.ok(await page.locator('#return-position').isDisabled());
      }
      await page.keyboard.press('Control+f');
      const query = page.locator('#find-query');
      await query.fill('chapter');
      await query.press('Enter');
      await page.waitForFunction(() => document.querySelector('#find-status').textContent.startsWith('第 1 页'));
      await query.press('Enter');
      await page.waitForFunction(() => document.querySelector('#find-status').textContent.startsWith('第 2 页'));
      assert.ok(await page.locator('#find-marks i').count());
      assert.equal(await copyBlocked(), true);
      await query.press('Shift+Enter');
      await page.waitForFunction(() => document.querySelector('#find-status').textContent.startsWith('第 1 页'));
      await query.press('Escape');
      assert.equal(await page.locator('#find-marks i').count(), 0);
      await chooseSample('#open-file');
      await page.waitForFunction(() => document.querySelector('#file-name').textContent === 'multilingual.pdf');
      await wait(1,'bionic');
      assert.equal(await copyBlocked(), false);
      assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
      reports.push({browser:name,version:browser.version(),pages:pages-1,textPreserved:true,originalPixelsRestored:true,noExternalRequests:true});
      console.log(name, 'passed',pages-1,'language pages');
    }catch(error){
      console.log(name,'failure',await page.evaluate(()=>({frame:{...document.querySelector('#page-frame').dataset},status:document.querySelector('#reading-status').textContent,message:document.querySelector('#message').textContent,modal:document.querySelector('dialog[open]')?.id,active:document.activeElement?.outerHTML})),errors);
      await page.screenshot({path:path.join(output,`${name}-failure.png`)});throw error;
    }finally{await browser.close();}
  }
}finally{
  fs.writeFileSync(path.join(output,'browser-report.json'),JSON.stringify(reports,null,2));
  await new Promise(resolve=>server.close(resolve));
}
