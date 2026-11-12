import test from 'node:test';
import assert from 'node:assert/strict';
import {BookSearch, foldText, pageText} from '../extension/search.mjs';
import {destinationView} from '../extension/navigation.mjs';

test('search expands ligatures and maps normalized accents back to the original characters', () => {
  const offsets = [];
  assert.equal(foldText('Oﬃce\r\nCafe\u0301', offsets), 'office café');
  assert.deepEqual(offsets.slice(1, 4), [[1, 2], [1, 2], [1, 2]]);
  assert.deepEqual(offsets.at(-1), [9, 11]);
  const items = [{type:'beginMarkedContentProps', actualText:'fi'}, {str:'\0'},
    {type:'beginMarkedContent'}, {str:'x'}, {type:'endMarkedContent'},
    {type:'endMarkedContent'}, {str:'nal', hasEOL:true}, {str:'line'}];
  assert.equal(pageText(items), 'final\nline');
});

test('search finds a wrapped word and literal compounds without hiding the source spelling', async () => {
  const book = new BookSearch({numPages:1});
  const items = [{str:'multi-', hasEOL:true}, {str:'plicative source-', hasEOL:true}, {str:'target HTTP-date [a+b].'}];
  const original = pageText(items);
  book.remember(1, items);
  const find = q => book.find(q, 1, 1);
  for (const [query, spelling] of [
    ['multiplicative source-target', 'multi-\nplicative source-\ntarget'],
    ['multi- plicative', 'multi-\nplicative'], ['source-\ntarget', 'source-\ntarget'],
    ['http-date', 'HTTP-date'], ['[a+b].', '[a+b].'],
  ]) {
    const {start, end, count} = await find(query);
    assert.equal(original.slice(start, end), spelling);
    assert.equal(count, 1);
  }
  assert.equal(await find('httpdate'), null);
  assert.equal(await find('aaab'), null);
});

test('full case folding returns original offsets and Turkish preserves both dotted and dotless I', async () => {
  const book = new BookSearch({numPages:1}, 'de');
  const line = 'Eine Straße und STRASSE. IŞIK, İSTANBUL, sık, sik, Σς.';
  book.remember(1, [{str:line}]);
  async function spelling(query, direction = 1) {
    const match = await book.find(query, 1, direction);
    return match && line.slice(match.start, match.end);
  }
  assert.equal(await spelling('STRASSE'), 'Straße');
  assert.equal(await spelling('Straße'), 'STRASSE');
  assert.equal(await spelling('strasse', -1), 'Straße');
  book.setLocale('tr');
  assert.equal(await spelling('istanbul'), 'İSTANBUL');
  assert.equal(await spelling('ışık'), 'IŞIK');
  assert.equal(await spelling('sık'), 'sık');
  assert.equal(book.match.count, 1);
  assert.equal(await spelling('sik'), 'sik');
  assert.equal(book.match.count, 1);
  book.setLocale('auto');
  assert.equal(await spelling('istanbul'), 'İSTANBUL');
  assert.equal(await spelling('ışık'), 'IŞIK');
  assert.equal(await spelling('sık'), 'sık');
  assert.equal(book.match.count, 1);
  assert.equal(await spelling('σσ'), 'Σς');
});

test('a long pasted passage is matched literally across a line break', async () => {
  const book = new BookSearch({numPages:1});
  const passage = 'independent evidence '.repeat(500);
  book.remember(1, [{str:'con-',hasEOL:true},{str:'trol ' + passage + 'complete'}]);
  const hit = await book.find('control ' + passage + 'complete', 1);
  assert.deepEqual([hit.start, hit.end], [0, passage.length + 18]);
});

test('keyboard and typographic quotes find the original spelling without matching prime signs', async () => {
  const line = '“Kane’s research” and "Kane\'s research". L’étude. обʼєкт. 5′ 6″';
  const book = new BookSearch({numPages:1});
  book.remember(1, [{str:line}]);
  async function found(query) {
    const match = await book.find(query, 1);
    return match && line.slice(match.start, match.end);
  }
  assert.equal(await found('"Kane\'s research"'), '“Kane’s research”');
  assert.equal(book.match.count, 2);
  assert.equal(await found('“Kane’s research”'), '"Kane\'s research"');
  assert.equal(await found("l'étude"), 'L’étude');
  assert.equal(await found("об'єкт"), 'обʼєкт');
  assert.equal(await found("5'"), null);
  assert.equal(await found('6"'), null);
});

test('book search visits only the necessary pages, wraps in both directions, and cancels', async () => {
  const visited = [];
  const pdf = {numPages:4, async getPage(n) {
    visited.push(n);
    return {getTextContent: async () => ({items:[{str:['', 'desk desk', '', 'DESK'][n - 1]}]})};
  }};
  const book = new BookSearch(pdf);
  const find = (page, direction) => book.find('desk', page, direction);
  let hit = await find(1, 1);
  assert.deepEqual([hit.page, hit.index, hit.count], [2, 0, 2]);
  assert.deepEqual(visited, [1, 2]);
  hit = await find(2, 1);
  assert.equal(hit.index, 1);
  hit = await find(2, 1);
  assert.equal(hit.page, 4);
  hit = await find(4, 1);
  assert.deepEqual([hit.page, hit.index], [2, 0]);
  assert.equal((await find(2, -1)).page, 4);
  assert.deepEqual(visited, [1, 2, 3, 4]);
  let release;
  const pendingPage = new Promise(resolve => { release = resolve; });
  const fresh = new BookSearch({numPages:1, getPage: () => pendingPage});
  const stale = fresh.find('desk', 1);
  fresh.clear();
  fresh.remember(1, [{str:'new'}]);
  await fresh.find('new', 1);
  release({getTextContent() { assert.fail('A superseded search should stop'); }});
  assert.equal(await stale, undefined);
  assert.deepEqual(fresh.match, {page:1, index:0, count:1, start:0, end:3});
});

test('a repaired visible page supplies the range and count used on revisits', async () => {
  const book = new BookSearch({numPages:1, async getPage() {
    return {getTextContent: async () => ({items:[{str:'Straße Straße'}]})};
  }});
  await book.find('STRASSE', 1, -1);
  assert.equal(book.match.index, 1);
  book.remember(1, [{str:'Die Straße'}]);
  assert.deepEqual(book.match, {page:1, index:0, count:1, start:4, end:10});
  assert.equal(book.remember(1, [{str:'Different'}]), true);
  assert.equal(await book.find('STRASSE', 1), null);
});

test('overlapping queries share page extraction and use the latest search language', async () => {
  let reads = 0;
  const started = Promise.withResolvers();
  const content = Promise.withResolvers();
  const book = new BookSearch({numPages:1, async getPage() {
    return {getTextContent() { ++reads; started.resolve(); return content.promise; }};
  }}, 'en');
  const stale = book.find('unused', 1);
  await started.promise;
  book.setLocale('tr');
  const latest = book.find('ışık', 1);
  await new Promise(resolve => setImmediate(resolve));
  content.resolve({items:[{str:'IŞIK IŞIK'}]});
  assert.equal(await stale, undefined);
  assert.equal((await latest).count, 2);
  assert.equal(reads, 1);
});

test('a failed page read can be retried and a visible repair wins over pending text', async () => {
  let reads = 0;
  const started = Promise.withResolvers();
  const content = Promise.withResolvers();
  const book = new BookSearch({numPages:1, async getPage() {
    return {getTextContent() {
      if (++reads === 1) throw new Error('read failed');
      started.resolve();
      return content.promise;
    }};
  }});
  await assert.rejects(book.find('correct', 1), /read failed/);
  const retry = book.find('correct', 1);
  await started.promise;
  book.remember(1, [{str:'correct'}]);
  content.resolve({items:[{str:'stale'}]});
  assert.deepEqual(await retry, {page:1, index:0, count:1, start:0, end:7});
  assert.equal(reads, 2);
});

test('destinations respect explicit zoom, omitted coordinates and a rotated FitR rectangle', () => {
  const page = {getViewport: () => ({width:200,height:100,viewBox:[10,20,110,220],
    convertToViewportRectangle: ([x,y,r,t]) => [y-20,x-10,t-20,r-10],
    convertToPdfPoint: (x,y) => [y+10,x+20]})};
  const resolve = (kind, ...args) => destinationView(page, [0,{name:kind},...args],
    {zoom:'2',point:[15,95]}, 100, 80);
  assert.deepEqual(resolve('XYZ',null,85,null), {zoom:'2',point:[15,85]});
  assert.deepEqual(resolve('XYZ',60,null,1.25), {zoom:'1.25',point:[60,95]});
  assert.deepEqual(resolve('FitH',78), {zoom:'fit',point:[10,78]});
  assert.deepEqual(resolve('FitR',20,80,70,130), {zoom:'1.6',point:[20,80]});
  assert.deepEqual(resolve('Fit'), {zoom:'0.5',point:null});
});
