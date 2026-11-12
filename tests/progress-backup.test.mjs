import assert from 'node:assert/strict';
import test from 'node:test';
import {makeBackup, restoreBackup, settingsKey} from '../extension/progress-backup.mjs';
import {bookmarkPrefix} from '../extension/reading-progress.mjs';

class MemoryStorage extends Map {
  get length() { return this.size; }
  key(index) { return [...this.keys()][index]; }
  getItem(key) { return this.get(key) ?? null; }
  setItem(key, value) { this.set(key, value); }
  removeItem(key) { this.delete(key); }
}
const hash = 'a'.repeat(43) + '=';
const key = bookmarkPrefix + hash;
const settings = {enabled:true, locale:'en', rule:'reference', strength:1};
const position = {number:4, zoom:'1.25', left:0, top:235, scale:1.25, point:[14, 336]};

test('progress backup transfers a position and preferences without exporting tab or file information', () => {
  const source = new MemoryStorage([[key, JSON.stringify({...position, name:'private.pdf'})],
    ['bionic-tab-view', '{"sourceKey":"private URL"}'], ['unrelated', 'private']]);
  const data = makeBackup(source, settings);
  assert.deepEqual(data.bookmarks, {[hash]:position});
  assert.ok(!JSON.stringify(data).includes('private'));
  const restored = new MemoryStorage([['unrelated','original']]);
  assert.equal(restoreBackup(data, restored, settings), 1);
  assert.deepEqual(JSON.parse(restored.getItem(key)),position);
  assert.deepEqual(JSON.parse(restored.getItem(settingsKey)),settings);
  assert.equal(restored.getItem('unrelated'),'original');
});

test('invalid bookmarks and storage errors leave all existing progress intact', () => {
  const data = makeBackup(new MemoryStorage([[key,JSON.stringify(position)]]),settings);
  const store = new MemoryStorage([[key,'old position'], [settingsKey,'old settings']]);
  const previous = [...store];
  assert.throws(()=>restoreBackup({...data,bookmarks:{...data.bookmarks,invalid:position}},store,settings));
  assert.deepEqual([...store],previous);
  store.setItem = (k,v) => {
    if (k === settingsKey) throw new Error('Storage full');
    store.set(k,v);
  };
  assert.throws(()=>restoreBackup(data,store,settings), /Storage full/);
  assert.deepEqual([...store],previous);
});
