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
let expired = false;
let htmlRequests = 0;
const server = http.createServer((req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  if (req.url === '/ordinary.pdf') {
    ++htmlRequests;
    res.writeHead(200, {'Content-Type':'text/html'}).end('<title>HTML article</title>');
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
  await reader.close();

  expired = true;
  reader = await clickExtension();
  await reader.getByRole('alert').filter({hasText:'请在原标签页保存文件'}).waitFor();
  assert.ok(await reader.locator('#choose-file').isVisible());
  await reader.locator('#file-input').setInputFiles(sample);
  await waitForPage(reader, 2);
  assert.equal(await reader.locator('#file-name').textContent(), 'multilingual.pdf');
  assert.deepEqual(errors, []);
  console.log('Extension toolbar, authenticated PDF, expired session, file picker and bionic rendering passed');
} finally {
  await context?.close();
  await new Promise(resolve => server.close(resolve));
  assert.ok(path.basename(profile).startsWith('bionic-extension-'));
  assert.equal(path.dirname(path.resolve(profile)), tmpBase);
  fs.rmSync(profile, {recursive:true, force:true});
}
