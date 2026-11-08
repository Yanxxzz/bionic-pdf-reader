import fs from 'node:fs';import test from 'node:test';import assert from 'node:assert/strict';
import {GlyphCapture,planGlyphs,repairTextContent,textGlyphBounds} from '../extension/layout.mjs';

test('search aligns an inferred space and a ligature with the painted line', () => {
  const viewport = {convertToViewportPoint: (x, y) => [x, 100 - y]};
  const item = {str:'a fi', dir:'ltr', fontName:'roman', transform:[12,0,0,12,10,72], width:30};
  const glyph = (text, x, w, y=28) => ({text, x, w, y, font:'roman'});
  const records = [glyph('a',10,5), glyph('ﬁ',32,8), glyph('x',34,5,45), glyph('b',41,7)];
  const bounds = textGlyphBounds(item, records, viewport);
  assert.deepEqual([bounds[0],bounds[1],bounds[2],bounds[3]], [[10,15],undefined,[32,40],[32,40]]);
  assert.equal(textGlyphBounds({...item,str:'a fig'}, records, viewport), undefined);
});
const cases=JSON.parse(fs.readFileSync(new URL('./layout-cases.json',import.meta.url),'utf8'));
for(const item of cases)test(item.name,()=>{
 const capture = new GlyphCapture(), size = item.fontSize ?? 15;
 const state = {font:{name:'normal'}, fontMatrix:[.001,0,0,.001], fontSize:size,
   fontSizeScale:1, fontDirection:1, charSpacing:0, wordSpacing:0, textRenderingMode:0};
 item.text.forEach((unicode, i) => {
   capture.mask([{unicode, width:10000 / size}], state,
     {a:1, b:0, c:0, d:1, e:item.x?.[i] ?? i*10, f:item.y?.[i] ?? 100});
   capture.records[i].actual = item.actual?.[i] ?? null;
 });
 const plan=planGlyphs(capture,{rule:item.rule ?? 'half',locale:item.locale});
 const selected=plan.masks.flatMap((mask,i)=>mask[0]?[i]:[]);assert.deepEqual(selected,item.selected);
});

test('the rendering planner selects prefixes in every authored language',()=>{
 const samples=JSON.parse(fs.readFileSync(new URL('../examples/languages.json',import.meta.url),'utf8'));
 for(const {code,text} of samples){
  const records=[...text].map((letter,index)=>({run:0,index,text:letter,x:index*7,y:100,w:7,h:15,font:'normal',eligible:true}));
  const plan=planGlyphs({runs:[records.length],records},{rule:'half',locale:code});
  assert.equal(plan.masks[0].length,records.length,code);
  assert.ok(plan.masks[0].some(Boolean),code);
  assert.ok(plan.masks[0].some(flag=>!flag),code);
 }
});

test('glyph capture keeps styled text, rotated labels and formulae unchanged',()=>{
 const current={font:{name:'regular'},fontMatrix:[.001,0,0,.001],fontSize:12,fontSizeScale:1,fontDirection:1,charSpacing:0,wordSpacing:0,textMatrix:[1,0,0,1,0,0],textRenderingMode:0};
 const transform={a:1,b:0,c:0,d:1,e:0,f:100};
 for(const [text,state,matrix] of [
  ['Reading text',{...current,font:{...current.font,bold:true}},transform],
  ['Reading text',current,{...transform,b:1,c:-1}],
  ['x = 2',current,transform],
  ['https://example.com',current,transform],
 ]){
  const capture=new GlyphCapture();
  capture.mask([...text].map(unicode=>({unicode,width:500})),state,matrix);
  assert.ok(planGlyphs(capture,{rule:'half'}).masks.flat().every(flag=>!flag),text);
 }
});

test('an implicit identity text matrix gives the same glyph positions at high DPI', () => {
  const state = {font:{name:'regular'}, fontMatrix:[.001,0,0,.001], fontSize:12, fontSizeScale:1,
    fontDirection:1, charSpacing:0, wordSpacing:0, textMatrix:null, textRenderingMode:0};
  const captures = [1, 2.5].map(scale => {
    const capture = new GlyphCapture(scale);
    capture.mask([{unicode:'a',width:500}], state, {a:scale,b:0,c:0,d:scale,e:10*scale,f:80*scale});
    return capture.records;
  });
  assert.equal(captures[0][0].eligible, true);
  assert.deepEqual(captures[1], captures[0]);
});
test('ActualText repairs retain source order across columns',()=>{
 const viewport={convertToViewportPoint:(x,y)=>[x,y],convertToPdfPoint:(x,y)=>[x,y]};
 const item=(str,x,y,width=20)=>({str,width,height:15,fontName:'regular',transform:[15,0,0,15,x,y]});
 const content={styles:{regular:{}},items:[item('left first',0,100),item('left second',0,150),item('broken',200,100),item('right second',200,150)]};
 const fixed=repairTextContent(content,[{str:'office',dir:'ltr',x:200,y:100,width:20,height:15,fontName:'regular'}],viewport);
 assert.deepEqual(fixed.items.map(i=>i.str),['left first','left second','office','right second']);
 const crossing={...content,items:[item('spans two columns',0,100,300)]};
 assert.equal(repairTextContent(crossing,[{str:'office',dir:'ltr',x:200,y:100,width:20,height:15,fontName:'regular'}],viewport).items[0].str,'spans two columns');
});

test('a single ActualText tag spanning lines or columns preserves each original copy item', () => {
  const viewport = {convertToViewportPoint: (x,y) => [x,y], convertToPdfPoint: (x,y) => [x,y]};
  for (const [text, x, y] of [['First\nSecond', 30, 100], ['First Second', 0, 130], ['First Second', 200, 100]]) {
    const actual = {id: 0, text};
    const records = [{text: 'First', x: 0, y: 100}, {text: 'Second', x, y}]
      .map((r, index) => ({...r, run: 0, index, h: 15, w: 30, font: 'regular', eligible: true, actual}));
    const content = {styles: {}, items: records.map(r => ({
      str: r.text, width: r.w, height: r.h, fontName: r.font, transform: [15,0,0,15,r.x,r.y],
    }))};
    const {masks, repairs} = planGlyphs({runs: [2], records}, {rule: 'half'});
    assert.deepEqual(masks, [[false, false]]);
    assert.deepEqual(repairTextContent(content, repairs, viewport).items.map(i => i.str), ['First','Second']);
  }
});

test('a tagged tab retains its spelling and the PDF position of the following word', () => {
  const atoms = [{text:'4.2',x:10,w:18}, {text:' ',x:30,w:3,actual:{id:0,text:'\t'}},
    {text:'Methods',x:53,w:55}];
  const records = atoms.map((r,index) => ({...r,index,run:0,y:90,h:15,font:'text',eligible:true}));
  const content = {styles:{text:{}},items:records.map(r => ({
    str:r.text,width:r.w,height:r.h,fontName:'text',transform:[15,0,0,15,r.x,r.y],
  }))};
  const viewport = {convertToViewportPoint:(x,y)=>[x,y],convertToPdfPoint:(x,y)=>[x,y]};
  const {repairs} = planGlyphs({runs:[3],records},{rule:'half'});
  const result = repairTextContent(content,repairs,viewport).items;
  assert.equal(result.map(item=>item.str).join(''), '4.2\tMethods');
  assert.deepEqual(result.map(item=>item.transform[4]), [10,30,53]);
  assert.deepEqual(result[2].glyphBounds[0], [53,108]);
  assert.deepEqual(result.map(item=>item.hasEOL), [false,false,true]);
});
