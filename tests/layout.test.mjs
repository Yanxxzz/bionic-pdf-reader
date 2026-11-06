import fs from 'node:fs';import test from 'node:test';import assert from 'node:assert/strict';
import {planGlyphs,repairTextContent} from '../extension/layout.mjs';
const cases=JSON.parse(fs.readFileSync(new URL('./layout-cases.json',import.meta.url),'utf8'));
for(const item of cases)test(item.name,()=>{
 const records=item.text.map((text,i)=>({run:i,index:0,text,x:i*10,y:100,w:10,h:15,font:'normal',eligible:true,actual:item.actual?.[i]||null}));
 const plan=planGlyphs({runs:records.map(()=>1),records},{rule:'half',locale:item.locale});
 const selected=plan.masks.flatMap((mask,i)=>mask[0]?[i]:[]);assert.deepEqual(selected,item.selected);
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
