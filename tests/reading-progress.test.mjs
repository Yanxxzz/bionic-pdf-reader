import assert from 'node:assert/strict';
import test from 'node:test';
import {digestBytes, ReadingProgress, savedTabView} from '../extension/reading-progress.mjs';

function storage() {
  const items = new Map();
  return {getItem: key => items.get(key) ?? null, setItem: (key, value) => items.set(key, value),
    removeItem: key => items.delete(key)};
}

test('different content with the same PDF prefix and size has independent persistent positions', async () => {
  globalThis.localStorage = storage();
  globalThis.sessionStorage = storage();
  const bytes = new Uint8Array(2048);
  const first = await digestBytes(bytes);
  bytes[1400] = 4;
  const second = await digestBytes(bytes);
  assert.notEqual(first, second);
  const a = new ReadingProgress({}, null, false);
  assert.equal(a.identify(first), null);
  a.save({number:4});
  const b = new ReadingProgress({}, savedTabView(), false);
  assert.equal(b.identify(second), null);
  assert.notEqual(b.documentId, a.documentId);
  b.save({number:2});
  const reopened = new ReadingProgress({sourceKey:'local URL'}, null, false);
  assert.deepEqual(JSON.parse(reopened.identify(first)), {number:4});
});

test('only the original handed-back File may recover an old fingerprint-only tab', () => {
  globalThis.localStorage = storage();
  globalThis.sessionStorage = storage();
  const old = {local:true, documentId:'old-tab', pdfVersion:'ambiguous', position:{number:7}};
  localStorage.setItem('bionic-page-ambiguous', '7');
  const different = new ReadingProgress({}, old, false);
  assert.equal(different.identify('different bytes'), null);
  const original = new ReadingProgress({}, old, true);
  assert.deepEqual(original.identify('original bytes'), {number:7});
  assert.equal(original.documentId, old.documentId);
  original.save(old.position);
  const reselected = new ReadingProgress({}, savedTabView(), false);
  assert.deepEqual(reselected.identify('original bytes'), {number:7});
  assert.equal(reselected.documentId, old.documentId);
  const other = new ReadingProgress({}, savedTabView(), false);
  assert.equal(other.identify('different bytes'), null);
  assert.notEqual(other.documentId, old.documentId);
});
