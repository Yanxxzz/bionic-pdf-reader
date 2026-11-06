import fs from 'node:fs';import path from 'node:path';import os from 'node:os';
import assert from 'node:assert/strict';import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const profile=fs.mkdtempSync(path.join(process.env.TEST_TMP||os.tmpdir(),'bionic-extension-'));
const context=await chromium.launchPersistentContext(profile,{headless:true,channel:process.env.EXTENSION_CHANNEL||'chromium',ignoreDefaultArgs:['--disable-extensions'],args:['--enable-unsafe-extension-debugging','--no-first-run']});
try{
  const cdp=await context.browser().newBrowserCDPSession();
  const {id}=await cdp.send('Extensions.loadUnpacked',{path:path.join(root,'extension')});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`chrome-extension://${id}/reader.html`);
  await page.locator('#file-input').setInputFiles(path.join(root,'.tmp/examples/multilingual.pdf'));
  await page.waitForFunction(()=>document.querySelector('#page-frame').dataset.renderedPage==='1');
  await page.locator('#bionic-mode').click();
  await page.waitForFunction(()=>document.querySelector('#page-frame').dataset.mode==='bionic');
  assert.ok(Number(await page.locator('#pdf-canvas').getAttribute('data-bold-glyphs'))>10);
  assert.deepEqual(errors,[]);
  console.log('Packaged extension CSP, module worker and toggle passed');
}finally{
  await context.close();
  // A freshly generated, dedicated test profile only.
  assert.ok(path.basename(profile).startsWith('bionic-extension-'));
  fs.rmSync(profile,{recursive:true,force:true});
}
