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
  if (req.url === '/selected/sample') {
    res.writeHead(200, {'Content-Type':'application/pdf', 'X-PDF-Name':encodeURIComponent('已选 #1.pdf')});
    fs.createReadStream(pdf).pipe(res);
    return;
  }
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
    const context=await browser.newContext({viewport:{width:1440,height:1040}});
    const page=await context.newPage();
    if(process.env.FORCE_LEGACY_STREAMS==='1')await page.addInitScript(()=>Object.defineProperty(ReadableStream.prototype,Symbol.asyncIterator,{value:undefined,configurable:true,writable:true}));
    const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:')&&!/^(blob:|data:)/.test(r.url()))external.push(r.url());});
    try{
      const url = `http://127.0.0.1:${server.address().port}/reader.html`;
      await page.goto(url + '#selected=sample');
      await page.waitForFunction(() => document.querySelector('#page-frame').dataset.renderedPage === '1');
      assert.equal(await page.locator('#file-name').textContent(), '已选 #1.pdf');
      assert.equal(page.url(), url);
      await page.reload();
      await page.waitForFunction(() => document.querySelector('#page-frame').dataset.renderedPage === '1');
      assert.equal(await page.locator('#file-name').textContent(), '已选 #1.pdf');
      await page.goto('about:blank');
      await page.goto(url);
      await page.locator('#welcome img').evaluate(image => image.decode());
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
      const settingsToggle = page.locator('#sidebar-toggle');
      for (const width of [760, 375, 320]) {
        await page.setViewportSize({width,height:812});
        assert.equal(await settingsToggle.count(), 1);
        await settingsToggle.click();
        assert.equal(await settingsToggle.getAttribute('aria-expanded'), 'true');
        await settingsToggle.press('Escape');
        assert.equal(await settingsToggle.getAttribute('aria-expanded'), 'false');
        await settingsToggle.press('Enter');
        for (const id of ['language','rule','strength','outline']) assert.ok(await page.locator('#'+id).isVisible());
        await page.locator('#language').selectOption('de');
        await page.locator('#outline').getByRole('button', {name:'de', exact:true}).click();
        await wait(3,'original');
        assert.equal(await settingsToggle.getAttribute('aria-expanded'), 'false');
        for (const id of ['return-position','find-toggle','prev-page','page-number','next-page','zoom','help-button']) {
          const box = await page.locator('#'+id).boundingBox();
          assert.ok(box && box.x >= 0 && box.x + box.width <= width + 1, id + ' at ' + width);
        }
      }
      await page.setViewportSize({width:1440,height:1040});
      assert.ok(await settingsToggle.isHidden());
      await page.locator('#outline').getByRole('button', {name:'en', exact:true}).click();
      await wait(1,'original');
      // Old or damaged settings can coexist with a valid language preference.
      await page.evaluate(() => {
        const progress = Object.keys(localStorage).find(key => key.startsWith('bionic-page-'));
        localStorage.setItem(progress, '2.5');
        localStorage.setItem('bionic-pdf-settings', JSON.stringify({locale:'fr', rule:'retired', enabled:'false', strength:99}));
      });
      await page.goto('about:blank');
      await page.goto(url);
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
      await page.reload();
      await wait(2, 'bionic');
      assert.equal(await page.locator('#text-layer').textContent(), previousText);
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
      const englishPage = await page.locator('#pdf-canvas').evaluate(canvas => canvas.toDataURL());
      await page.locator('#language').selectOption('auto');await wait(1,'bionic');
      assert.equal(await page.locator('#pdf-canvas').evaluate(canvas => canvas.toDataURL()), englishPage);
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
      await page.reload();
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
      await query.fill('multiplicative');
      await query.press('Enter');
      await page.waitForFunction(() => document.querySelectorAll('#find-marks i').length === 2);
      const leftEdges = await page.locator('#find-marks i').evaluateAll(marks => {
        const frame = document.querySelector('#page-frame').getBoundingClientRect();
        return marks.map(mark => (mark.getBoundingClientRect().left - frame.left) * 300 / frame.width);
      });
      assert.ok(Math.abs(leftEdges[0] - 170) < 2 && Math.abs(leftEdges[1] - 30) < 2);
      await page.locator('#find-next').click();
      await page.waitForFunction(() => document.querySelector('#find-status').textContent === '第 2 页 · 本页第 1/1 处');
      await query.fill('STRASSE');
      await query.press('Enter');
      await page.waitForFunction(() => document.querySelector('#find-status').textContent === '第 2 页 · 本页第 1/1 处');
      await page.locator('#find-prev').click();
      await page.waitForFunction(() => document.querySelector('#find-status').textContent === '第 1 页 · 本页第 1/1 处');
      assert.equal(await page.locator('#find-marks i').count(), 1);
      await query.press('Escape');
      assert.equal(await page.locator('#find-marks i').count(), 0);
      await chooseSample('#open-file');
      await page.waitForFunction(() => document.querySelector('#file-name').textContent === 'multilingual.pdf');
      await wait(1,'bionic');
      assert.equal(await copyBlocked(), false);
      // Reopen immediately after scrolling, including at a different fit width.
      const scroller = page.locator('#page-scroller');
      const scroll = () => scroller.evaluate(el => [el.scrollLeft, el.scrollTop]);
      const visibleFraction = () => scroller.evaluate(el => {
        const frame = document.querySelector('#page-frame').getBoundingClientRect();
        return (el.getBoundingClientRect().top - frame.top) / frame.height;
      });
      async function changeView(change) {
        const revision = await page.locator('#page-frame').getAttribute('data-render-revision');
        await change();
        await page.waitForFunction(old => {
          const f = document.querySelector('#page-frame').dataset;
          return f.renderState === 'ready' && f.renderRevision !== old;
        }, revision);
      }
      const zoomTo = value => changeView(() => page.locator('#zoom').selectOption(value));
      await zoomTo('2');
      await scroller.evaluate(el => el.scrollTo(40, 388));
      const fixed = await scroll();
      assert.ok(fixed[1] > 300);
      const second = await context.newPage();
      await second.goto(url);
      await second.locator('#file-input').setInputFiles(pdf);
      await second.locator('#outline').getByRole('button', {name:'de', exact:true}).click();
      await second.waitForFunction(() => document.querySelector('#page-frame').dataset.renderedPage === '3');
      await page.reload();
      await wait(1, 'bionic');
      assert.equal(await page.locator('#zoom').inputValue(), '2');
      assert.deepEqual(await scroll(), fixed);
      await second.reload();
      await second.waitForFunction(() => document.querySelector('#page-frame').dataset.renderedPage === '3');
      await second.locator('#return-position').click();
      await second.waitForFunction(() => document.querySelector('#page-frame').dataset.renderedPage === '1');
      await second.close();
      await zoomTo('fit');
      await scroller.evaluate(el => el.scrollTo(0, 320));
      const fraction = await visibleFraction();
      await page.reload();
      await page.setViewportSize({width:1050, height:650});
      await wait(1, 'bionic');
      assert.equal(await page.locator('#zoom').inputValue(), 'fit');
      assert.ok(Math.abs(await visibleFraction() - fraction) < .003, 'The same line is visible after resizing');
      await changeView(() => page.setViewportSize({width:1250, height:650}));
      assert.ok(Math.abs(await visibleFraction() - fraction) < .003, 'Live fit-width resizing keeps the same line');
      await zoomTo('2');
      assert.ok(Math.abs(await visibleFraction() - fraction) < .003, 'Changing zoom keeps the same line');
      const projectUrl = 'https://github.com/Yanxxzz/bionic-pdf-reader';
      await context.route(projectUrl, route => route.fulfill({contentType:'text/html', body:'<title>Paper link</title>'}));
      for (const mode of ['original', 'bionic']) {
        await page.locator('#' + mode + '-mode').click();
        await wait(1, mode);
        const link = page.locator(`#page-links a[href="${projectUrl}"]`);
        await link.scrollIntoViewIfNeeded();
        const before = await scroll();
        const [tab] = await Promise.all([context.waitForEvent('page'), link.click()]);
        await tab.waitForURL(projectUrl);
        assert.deepEqual(await tab.evaluate(() => [window.opener === null, document.referrer]), [true, '']);
        await tab.close();
        assert.deepEqual(await scroll(), before);
        assert.equal(await page.locator('#page-number').inputValue(), '1');
      }
      const blocked = await context.newPage();
      await blocked.addInitScript(() => Object.defineProperty(navigator, 'serviceWorker', {value:undefined}));
      await blocked.goto(url);
      await blocked.locator('#file-input').setInputFiles(pdf);
      await blocked.locator('#outline').getByRole('button', {name:'de', exact:true}).click();
      await blocked.waitForFunction(() => document.querySelector('#page-frame').dataset.renderedPage === '3');
      await blocked.reload();
      await blocked.getByRole('alert').filter({hasText:'重新选择'}).waitFor();
      assert.ok(await blocked.locator('#choose-file').isVisible());
      await blocked.locator('#file-input').setInputFiles(pdf);
      await blocked.waitForFunction(() => document.querySelector('#page-frame').dataset.renderedPage === '3');
      await blocked.close();
      await chooseSample('#open-file', path.join(root,'.tmp/examples/named.pdf'));
      await page.waitForFunction(() => document.querySelector('#file-name').textContent === 'named.pdf');
      for (const mode of ['original', 'bionic']) {
        await page.locator('#' + mode + '-mode').click();
        await wait(1, mode);
        const zoom = await page.locator('#zoom').inputValue();
        for (const [action, number] of [['NextPage', 2], ['LastPage', 4], ['PrevPage', 3], ['FirstPage', 1]]) {
          await page.getByRole('link', {name:action, exact:true}).click();
          await wait(number, mode);
          assert.equal(await page.locator('#zoom').inputValue(), zoom);
        }
        await page.locator('#return-position').click();
        await wait(3, mode);
        await page.goForward();
        await wait(1, mode);
        const nextSlide = page.locator('#outline').getByRole('button', {name:'Next slide', exact:true});
        for (const number of [2, 3]) {
          await nextSlide.click();
          await wait(number, mode);
        }
        for (const number of [2, 1]) {
          await page.locator('#return-position').click();
          await wait(number, mode);
        }
      }
      await chooseSample('#open-file', path.join(root,'.tmp/examples/scaled-text.pdf'));
      await page.locator('#bionic-mode').click();
      let expectedGlyphs;
      for (let number = 1; number <= 4; ++number) {
        await page.locator('#page-number').fill(String(number));
        await page.locator('#page-number').press('Enter');
        await wait(number, 'bionic');
        const count = Number(await page.locator('#pdf-canvas').getAttribute('data-bold-glyphs'));
        assert.ok(count > 0, `Scaled text on page ${number}`);
        expectedGlyphs ??= count;
        assert.equal(count, expectedGlyphs);
      }
      await chooseSample('#open-file', path.join(root,'.tmp/examples/numbers.pdf'));
      await page.waitForFunction(() => document.querySelector('#file-name').textContent === 'numbers.pdf');
      for (const mode of ['original', 'bionic']) {
        await page.locator('#' + mode + '-mode').click();
        await wait(1, mode);
        assert.match(await page.locator('#reading-status').textContent(), /可搜索/);
      }
      await page.keyboard.press('Control+f');
      await query.fill('12345');
      await query.press('Enter');
      await page.locator('#find-marks i').first().waitFor();
      if (process.env.OCR_READING_PDF) {
        const scan = path.resolve(root, process.env.OCR_READING_PDF);
        await chooseSample('#open-file', scan);
        await page.waitForFunction(file => document.querySelector('#file-name').textContent === file &&
          document.querySelector('#page-frame').dataset.renderState === 'ready', path.basename(scan));
        for (const [number, phrase, rest] of [
          [1, 'Reading together readers', 'Research papers retain their words.'],
          [2, 'I found a pressed fern between two pages.', 'The next line stays separate. 1'],
        ]) {
          await page.locator('#page-number').fill(String(number));
          await page.locator('#page-number').press('Enter');
          for (const mode of ['original', 'bionic']) {
            await page.locator('#' + mode + '-mode').click();
            await wait(number, mode);
            const selected = await page.locator('#text-layer').evaluate(layer => {
              const range = new Range(), selection = getSelection();
              range.selectNodeContents(layer);
              selection.removeAllRanges();
              selection.addRange(range);
              return selection.toString().replace(/\s+/gu, ' ').trim();
            });
            assert.equal(selected, phrase + ' ' + rest);
          }
          await page.keyboard.press('Control+f');
          await query.fill(phrase);
          await query.press('Enter');
          await page.locator('#find-marks i').first().waitFor();
          assert.match(await page.locator('#find-status').textContent(), /本页第 1\/1 处/);
        }
      }
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
