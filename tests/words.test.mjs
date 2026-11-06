import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { prefixLength, glyphMask, wordSpans } from '../extension/bionic.mjs';
const current={font:{},fontSize:12,textMatrix:[1,0,0,1,0,0],textRenderingMode:0};
test('reference rule and complete combining characters',()=>{
  assert.equal(prefixLength('Reading'),4);
  assert.equal(prefixLength('the'),1);
  assert.equal(prefixLength('Reading','half'),4);
  assert.equal(prefixLength('e\u0301cole','half'),4);
  assert.equal(prefixLength('personnel','reference','fr'),5);
  assert.equal(prefixLength('personnel','reference','en'),4);
});
test('each authored language has word boundaries and selected original glyphs',()=>{
  const samples=JSON.parse(fs.readFileSync(new URL('../examples/languages.json',import.meta.url)));
  for(const {code,text} of samples){
    assert.ok(wordSpans(text,code).length>1,code);
    const glyphs=[...text].map(unicode=>({unicode}));
    const flags=glyphMask(glyphs,current,{enabled:true,rule:'half',locale:code});
    assert.ok(flags.some(Boolean),code);
    assert.ok(flags.some(f=>!f),code);
    assert.equal(flags.length,glyphs.length);
  }
});
test('original mode, formula runs and rotated chart labels are unchanged',()=>{
  const glyphs=[...'Reading text'].map(unicode=>({unicode}));
  assert.equal(glyphMask(glyphs,current,{enabled:false}),null);
  assert.equal(glyphMask(glyphs,{...current,textMatrix:[0,1,-1,0,0,0]},{enabled:true}),null);
  assert.equal(glyphMask([...'x = 2'].map(unicode=>({unicode})),current,{enabled:true}),null);
});
