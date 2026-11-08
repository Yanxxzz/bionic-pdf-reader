import test from 'node:test';
import assert from 'node:assert/strict';
import {savedPosition, webLinkURL} from '../extension/navigation.mjs';

test('paper links accept web addresses and DOI identifiers', () => {
  assert.equal(webLinkURL({url:'https://publisher.example/paper#results'}), 'https://publisher.example/paper#results');
  assert.equal(webLinkURL({url:'http://journal.example/'}), 'http://journal.example/');
  for (const unsafeUrl of ['doi:10.1234/foo(bar)', '10.1234/foo(bar)']) {
    assert.equal(webLinkURL({unsafeUrl}), 'https://doi.org/10.1234/foo(bar)');
  }
  assert.equal(webLinkURL({unsafeUrl:'doi:10.1234/p#1'}), 'https://doi.org/10.1234/p%231');
  for (const url of ['javascript:alert(1)', 'file:///private.pdf', 'data:text/html,Hi', 'mailto:a@example.org', '/missing-base']) {
    assert.equal(webLinkURL({url, unsafeUrl:url}), null);
  }
});

test('reading progress supports older page numbers and recovers usable parts of a damaged entry', () => {
  const read = raw => savedPosition(raw, 12, 'fit');
  const position = {number:8, zoom:'2', left:38, top:441, scale:2, point:[10, 760]};
  assert.deepEqual(read(JSON.stringify(position)), position);
  assert.deepEqual(read('8'), {number:8, zoom:'fit'});
  assert.deepEqual(read('99'), {number:12, zoom:'fit'});
  for (const raw of [null, '2.5', '{', 'null']) assert.deepEqual(read(raw), {number:1, zoom:'fit'});
  assert.deepEqual(read('{"number":5,"zoom":"bogus"}'), {number:5, zoom:'fit'});
  assert.deepEqual(read('{"number":5,"zoom":"2","left":-1,"top":10}'), {number:5, zoom:'2'});
});
