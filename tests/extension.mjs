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
const app = path.resolve(process.env.EXTENSION_DIR || path.join(root, 'extension'));
const sample = path.join(root, '.tmp/examples/multilingual.pdf');
const bytes = fs.readFileSync(sample);
const named = fs.readFileSync(path.join(path.dirname(sample), 'named.pdf'));
// Valid trailing PDF comments make two distinct editions with the same name,
// declared ID, file size, and first 1024 bytes.
const editions = ['A', 'B'].map(tag => Buffer.concat([bytes, Buffer.from('\n% Edition ' + tag + '\n')]));
// Leave a hole before the xref. The front and tail suffice to display the first pages.
const xref = Number(/startxref\s+(\d+)\s+%%EOF/.exec(bytes.toString('latin1'))[1]);
const gap = Buffer.alloc(4 * 1024 * 1024, 32);
const tail = bytes.subarray(xref).toString('latin1').replace(/(startxref\s+)\d+/, (_, prefix) => prefix + (xref + gap.length));
const large = Buffer.concat([bytes.subarray(0, xref), gap, Buffer.from(tail + '\n% edition A', 'latin1')]);
const revised = Buffer.from(large); revised[revised.length - 1] = 66;
let remote = large, etag, hold = false;
const held = new Set();
function releaseDownload() {
  hold = false;
  for (const finish of held) finish();
  held.clear();
}

function serveRange(req, res) {
  const data = remote;
  const range = /^bytes=(\d+)-(\d+)$/.exec(req.headers.range || '');
  const start = range ? Number(range[1]) : 0, end = range ? Math.min(Number(range[2]) + 1, data.length) : data.length;
  res.setHeader('Accept-Ranges', 'bytes');
  res.setHeader('Content-Type', 'application/pdf');
  res.setHeader('Content-Length', end - start);
  if (etag) res.setHeader('ETag', etag);
  if (range) { res.statusCode = 206; res.setHeader('Content-Range', `bytes ${start}-${end - 1}/${data.length}`); }
  if (!hold || (range && (start < 65536 || end >= data.length - 65536))) return res.end(data.subarray(start, end));
  if (!range) res.write(data.subarray(0, 65536));
  else res.flushHeaders();
  const finish = () => res.end(data.subarray(range ? start : 65536, end));
  held.add(finish);
  res.on('close', () => held.delete(finish));
}
let edition = 0;
let expired = false;
let htmlRequests = 0;
const server = http.createServer((req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  if (req.url === '/slow.pdf') {
    serveRange(req, res);
  } else if (req.url === '/ordinary.pdf') {
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
async function launchExtension() {
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
  return {cdp, id};
}
try {
  const {cdp, id} = await launchExtension();
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
  await reader.close();

  // Seed a conflicting bookmark for each complete edition, then reload mid-download.
  reader = await context.newPage();
  await reader.goto(`chrome-extension://${id}/reader.html`);
  async function turn(number) {
    await reader.locator('#page-number').fill(String(number));
    await reader.locator('#page-number').press('Enter');
    await waitForPage(reader, number);
  }
  for (const [data, number] of [[large, 4], [revised, 3]]) {
    await reader.locator('#file-input').setInputFiles({name:'seed.pdf', mimeType:'application/pdf', buffer:data});
    await waitForPage(reader, 1);
    await turn(number);
  }
  await reader.close();
  for (const scenario of ['refresh-twice', 'changed-bytes', 'new-navigation', 'changed-etag', 'untouched']) {
    remote = large;
    etag = scenario === 'changed-etag' ? '"first"' : null;
    await source.goto(base + '/slow.pdf');
    hold = true;
    reader = await clickExtension();
    await waitForPage(reader, 1);
    if (scenario === 'refresh-twice') {
      // Interrupt the turn before page two can paint, then reload the still-partial file again below.
      await Promise.all([reader.waitForEvent('domcontentloaded'), reader.evaluate(() => {
        const input = document.querySelector('#page-number');
        input.value = '2';
        input.dispatchEvent(new Event('change', {bubbles:true}));
        location.reload();
      })]);
      await waitForPage(reader, 1);
    } else if (scenario !== 'untouched') {
      await turn(2);
      await reader.waitForFunction(() => JSON.parse(sessionStorage.getItem('bionic-tab-view')).pending);
    }
    if (scenario === 'changed-bytes') remote = revised; // Same URL, length, PDF ID and first 1024 bytes.
    if (scenario === 'changed-etag') {
      remote = Buffer.from(large);
      remote[xref + gap.length / 2] = 9; // Only an unread middle byte changes.
      etag = '"replacement"';
    }
    await reader.reload();
    await waitForPage(reader, 1);
    if (scenario === 'new-navigation') await turn(5);
    releaseDownload();
    const expected = {'refresh-twice':2, 'changed-bytes':3, 'new-navigation':5, 'changed-etag':1, untouched:5}[scenario];
    await reader.waitForFunction(n => {
      const saved = JSON.parse(sessionStorage.getItem('bionic-tab-view'));
      return saved?.contentKey && saved.position.number === n &&
        document.querySelector('#page-frame').dataset.renderedPage === String(n);
    }, expected);
    await reader.close();
  }
  assert.deepEqual(errors, []);
  // Reload the unpacked extension from its original directory and browser profile.
  // A fresh reader tab must recover both the persistent settings and the document's place.
  const home = 'chrome-extension://' + id + '/reader.html';
  reader = await context.newPage();
  await reader.goto(home);
  await reader.locator('#file-input').setInputFiles(sample);
  await reader.locator('#page-number').waitFor({state:'visible'});
  await reader.locator('#bionic-mode').click();
  await reader.locator('#zoom').selectOption('1.25');
  await reader.locator('#page-number').fill('3');
  await reader.locator('#page-number').press('Enter');
  await waitForPage(reader, 3);
  await reader.close();
  await context.close();
  assert.equal((await launchExtension()).id, id);
  reader = await context.newPage();
  await reader.goto(home);
  await reader.locator('#file-input').setInputFiles(sample);
  await waitForPage(reader, 3);
  assert.equal(await reader.locator('#zoom').inputValue(), '1.25');
  assert.equal(await reader.locator('#bionic-mode').getAttribute('aria-pressed'), 'true');
  console.log('Extension toolbar, file picker, named destination, expired session and partial-download reloads passed');
} finally {
  releaseDownload();
  await context?.close();
  await new Promise(resolve => server.close(resolve));
  assert.ok(path.basename(profile).startsWith('bionic-extension-'));
  assert.equal(path.dirname(path.resolve(profile)), tmpBase);
  fs.rmSync(profile, {recursive:true, force:true});
}
