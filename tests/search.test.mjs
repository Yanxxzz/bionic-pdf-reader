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

test('book search visits only the necessary pages, wraps in both directions, and cancels', async () => {
  const visited = [];
  const pdf = {numPages:4, async getPage(n) {
    visited.push(n);
    return {getTextContent: async () => ({items:[{str:['', 'desk desk', '', 'DESK'][n - 1]}]})};
  }};
  const book = new BookSearch(pdf);
  const find = (page, direction, previous) => book.find('desk', page, direction, previous, () => false, () => {});
  let hit = await find(1, 1, null);
  assert.deepEqual([hit.page, hit.index, hit.count], [2, 0, 2]);
  assert.deepEqual(visited, [1, 2]);
  hit = await find(2, 1, hit);
  assert.equal(hit.index, 1);
  hit = await find(2, 1, hit);
  assert.equal(hit.page, 4);
  hit = await find(4, 1, hit);
  assert.deepEqual([hit.page, hit.index], [2, 0]);
  assert.equal((await find(2, -1, hit)).page, 4);
  assert.deepEqual(visited, [1, 2, 3, 4]);
  const fresh = new BookSearch(pdf);
  assert.equal(await fresh.find('desk', 1, 1, null, () => true, () => {}), null);
  assert.equal(fresh.pages.size, 0);
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
