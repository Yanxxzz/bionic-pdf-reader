import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const tmpBase = path.resolve(process.env.TEST_TMP || os.tmpdir());
const profile = fs.mkdtempSync(path.join(tmpBase, 'bionic-extension-'));
const channel = process.env.EXTENSION_CHANNEL || 'chromium';
const app = path.join(root, 'extension');
const sample = path.join(root, '.tmp/examples/multilingual.pdf');
const bytes = fs.readFileSync(sample);
const named = fs.readFileSync(path.join(path.dirname(sample), 'named.pdf'));
// Valid trailing PDF comments make two distinct editions with the same name,
// declared ID, file size, and first 1024 bytes.
const editions = ['A', 'B'].map(tag => Buffer.concat([bytes, Buffer.from('\n% Edition ' + tag + '\n')]));
let edition = 0;
let expired = false;
let htmlRequests = 0;
const server = http.createServer((req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  if (req.url === '/ordinary.pdf') {
    ++htmlRequests;
    res.writeHead(200, {'Content-Type':'text/html'}).end('<title>HTML article</title>');
  } else if (req.url === '/edition.pdf') {
    res.writeHead(200, {'Content-Type':'application/pdf', 'Content-Length':editions[edition].length}).end(editions[edition]);
  } else if (req.url === '/named') {
    res.writeHead(200, {'Content-Type':'application/pdf', 'Content-Length':named.length}).end(named);
  } else if (req.url === '/paper' && !expired && req.headers.cookie?.includes('session=reader-test')) {
    res.writeHead(200, {'Content-Type':'application/pdf', 'Content-Length':bytes.length,
      'Content-Disposition':'inline; filename="article.pdf"'}).end(bytes);
  } else {
    res.writeHead(403).end('Session expired');
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;
let context;
try {
  const args = ['--enable-unsafe-extension-debugging'];
  if (channel === 'chromium') args.push(`--disable-extensions-except=${app}`, `--load-extension=${app}`);
  context = await chromium.launchPersistentContext(profile, {
    headless:true, channel, args, ignoreDefaultArgs:['--disable-extensions'],
  });
  const cdp = await context.browser().newBrowserCDPSession();
  if (channel !== 'chromium') await cdp.send('Extensions.loadUnpacked', {path:app});
  const worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker');
  const id = new URL(worker.url()).hostname;
  assert.ok(await worker.evaluate(() => chrome.action.onClicked.hasListeners()));
  const source = await context.newPage();
  const sourceSession = await context.newCDPSession(source);
  const errors = [];
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)));

  async function clickExtension() {
    await source.bringToFront();
    const {targetInfo} = await sourceSession.send('Target.getTargetInfo');
    const {targetInfos} = await cdp.send('Target.getTargets', {filter:[{type:'tab'}]});
    const tab = targetInfos.find(t => t.targetId === targetInfo.parentId) || targetInfos.find(t => t.url === source.url());
    assert.ok(tab, 'The native PDF tab is available');
    const [reader] = await Promise.all([
      context.waitForEvent('page'),
      cdp.send('Extensions.triggerAction', {id, targetId:tab.targetId}),
    ]);
    await reader.waitForSelector('html[data-reader-ready]');
    return reader;
  }
  const waitForPage = (reader, number) => reader.waitForFunction(n =>
    document.querySelector('#page-frame').dataset.renderedPage === String(n), number);

  await source.goto(base + '/ordinary.pdf');
  const visits = htmlRequests;
  let reader = await clickExtension();
  await reader.locator('#choose-file').click({trial:true});
  await reader.locator('#file-input').setInputFiles(sample);
  await waitForPage(reader, 1);
  await reader.locator('#bionic-mode').click();
  await reader.waitForFunction(() => document.querySelector('#page-frame').dataset.mode === 'bionic');
  assert.ok(Number(await reader.locator('#pdf-canvas').getAttribute('data-bold-glyphs')) > 10);
  assert.equal(htmlRequests, visits);
  await reader.close();

  await context.addCookies([{name:'session', value:'reader-test', url:base, sameSite:'Lax'}]);
  await source.goto(base + '/paper#page=2');
  reader = await clickExtension();
  await waitForPage(reader, 2);
  assert.equal(await reader.locator('#file-name').textContent(), 'article.pdf');
  assert.equal(reader.url(), `chrome-extension://${id}/reader.html`);
  assert.equal(source.url(), base + '/paper#page=2');
  const saved = await reader.evaluate(() => sessionStorage.getItem('bionic-tab-view'));
  assert.ok(saved && !saved.includes(base));
  await reader.locator('#outline').getByRole('button', {name:'de', exact:true}).click();
  await waitForPage(reader, 3);
  await reader.locator('#zoom').selectOption('2');
  await waitForPage(reader, 3);
  const top = await reader.locator('#page-scroller').evaluate(el => { el.scrollTop = 290; return el.scrollTop; });
  assert.ok(top > 0);
  const other = await clickExtension();
  await waitForPage(other, 2);
  await other.waitForFunction(() => document.querySelector('#zoom').value === '2');
  await reader.reload();
  await waitForPage(reader, 3);
  assert.equal(await reader.locator('#page-scroller').evaluate(el => el.scrollTop), top);
  assert.ok(await reader.locator('#return-position').isEnabled());
  await other.close();
  await source.goto(base + '/ordinary.pdf');
  const ordinaryVisits = htmlRequests;
  await reader.reload();
  await reader.getByRole('alert').filter({hasText:'原标签页'}).waitFor();
  assert.ok(await reader.locator('#choose-file').isVisible());
  assert.equal(htmlRequests, ordinaryVisits, 'Reload never fetches the replacement page');
  await reader.close();

  await source.goto(base + '/named#page=2#nameddest=Methods%20+%20data');
  reader = await clickExtension();
  await waitForPage(reader, 4);
  assert.equal(await reader.locator('#zoom').inputValue(), '2');
  assert.ok(await reader.locator('#page-scroller').evaluate(el => el.scrollTop > 300));
  await reader.locator('#file-input').setInputFiles(sample);
  await waitForPage(reader, 3);
  await reader.reload();
  await waitForPage(reader, 3);
  assert.equal(await reader.locator('#file-name').textContent(), 'multilingual.pdf');
  await reader.evaluate(() => {
    const write = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      if (this === sessionStorage) throw new DOMException('Full', 'QuotaExceededError');
      return write.call(this, key, value);
    };
  });
  await reader.locator('#file-input').setInputFiles(path.join(path.dirname(sample), 'named.pdf'));
  await reader.waitForFunction(() => document.querySelector('#file-name').textContent === 'named.pdf' &&
    document.querySelector('#page-frame').dataset.renderState === 'ready');
  assert.equal(await reader.evaluate(() => sessionStorage.getItem('bionic-tab-view')), null);
  await reader.reload();
  await reader.locator('#choose-file').waitFor();
  await reader.close();
  await source.goto(base + '/paper#page=2');
  expired = true;
  reader = await clickExtension();
  await reader.getByRole('alert').filter({hasText:'请在原标签页保存文件'}).waitFor();
  assert.ok(await reader.locator('#choose-file').isVisible());
  await reader.locator('#file-input').setInputFiles(sample);
  await waitForPage(reader, 3);
  assert.equal(await reader.locator('#file-name').textContent(), 'multilingual.pdf');
  await reader.close();

  await source.goto(base + '/edition.pdf');
  async function openEdition() {
    const tab = await clickExtension();
    await tab.waitForFunction(() => JSON.parse(sessionStorage.getItem('bionic-tab-view'))?.contentKey);
    return tab;
  }
  reader = await openEdition();
  await reader.locator('#page-number').fill('4');
  await reader.locator('#page-number').press('Enter');
  await waitForPage(reader, 4);
  await reader.close();
  edition = 1;
  reader = await openEdition();
  await waitForPage(reader, 1);
  await reader.locator('#page-number').fill('2');
  await reader.locator('#page-number').press('Enter');
  await waitForPage(reader, 2);
  await reader.reload();
  await waitForPage(reader, 2);
  await reader.locator('#file-input').setInputFiles({name:'renamed.pdf', mimeType:'application/pdf', buffer:editions[0]});
  await waitForPage(reader, 4);
  assert.deepEqual(errors, []);
  console.log('Extension toolbar, reload, named destination, expired session and file picker passed');
} finally {
  await context?.close();
  await new Promise(resolve => server.close(resolve));
  assert.ok(path.basename(profile).startsWith('bionic-extension-'));
  assert.equal(path.dirname(path.resolve(profile)), tmpBase);
  fs.rmSync(profile, {recursive:true, force:true});
}
