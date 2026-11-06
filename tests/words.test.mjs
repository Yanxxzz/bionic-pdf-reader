import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { prefixLength, wordSpans } from '../extension/words.mjs';
test('reference rule and complete combining characters',()=>{
  assert.equal(prefixLength('Reading'),4);
  assert.equal(prefixLength('the'),1);
  assert.equal(prefixLength('Reading','half'),4);
  assert.equal(prefixLength('e\u0301cole','half'),4);
  assert.equal(prefixLength('personnel','reference','fr'),5);
  assert.equal(prefixLength('personnel','reference','en'),4);
});
test('each authored language has word boundaries and complete word prefixes',()=>{
  const samples=JSON.parse(fs.readFileSync(new URL('../examples/languages.json',import.meta.url)));
  for(const {code,text} of samples){
    const words=wordSpans(text,code);
    assert.ok(words.length>1,code);
    assert.ok(words.some(({segment})=>prefixLength(segment,'half',code)>0),code);
    for(const {segment} of words)assert.ok(prefixLength(segment,'half',code)<=segment.length,code);
  }
});
