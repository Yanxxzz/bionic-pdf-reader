import {wordSpans,prefixLength} from './words.mjs';

const rtl=/[\p{Script=Arabic}\p{Script=Hebrew}]/u;
const letter=/[\p{L}\p{N}]/u;
const graphemes=new Intl.Segmenter(undefined,{granularity:'grapheme'});

export class GlyphCapture {
  constructor(){this.runs=[];this.records=[];this.scopes=[];this.serial=0;}
  renderer(){return {enabled:true,strength:1,stroked:0,
    beginMarkedContent:text=>this.scopes.push(typeof text==='string'?{id:this.serial++,text}:null),
    endMarkedContent:()=>this.scopes.pop(),
    mask:(glyphs,current,matrix,visible=true)=>{this.capture(glyphs,current,matrix,visible);return null;}};}
  capture(glyphs,c,m,visible=true){
    const run=this.runs.length;this.runs.push(glyphs.length);
    if(!visible)return;
    const actual=this.scopes.find(s=>s!==null)||null;
    const size=c.fontSize,fs=c.fontSizeScale,advance=size*c.fontMatrix[0];let x=0;
    const eligible=!c.font.bold&&!c.font.black&&!c.font.italic&&!c.font.vertical&&!/bold|italic|oblique|black|heavy|demi|symbol|dingbat/i.test(c.font.name||'')&&c.textRenderingMode===0&&!c.patternFill&&size*Math.hypot(c.textMatrix[2],c.textMatrix[3])>=6.8&&size*Math.hypot(c.textMatrix[2],c.textMatrix[3])<=25&&Math.abs(m.b)<1e-5&&Math.abs(m.c)<1e-5;
    glyphs.forEach((glyph,index)=>{
      if(typeof glyph==='number'){x-=glyph*size/1000;return;}
      const width=glyph.width*advance+(c.charSpacing+(glyph.isSpace?c.wordSpacing:0))*c.fontDirection;
      const a=m.a*x/fs+m.e,b=m.a*(x+width)/fs+m.e;
      this.records.push({run,index,text:glyph.unicode||'',x:Math.min(a,b),y:m.b*x/fs+m.f,w:Math.abs(b-a),h:Math.abs(m.d*size/fs),font:c.font.loadedName||c.font.name,actual,eligible});x+=width;
    });
  }
}

function atomsFromRecords(records){
  const atoms=[],scopes=new Map();
  records.forEach((record,id)=>{
    if(record.actual){
      if(!scopes.has(record.actual.id)){const atom={text:record.actual.text,records:[],actual:true};scopes.set(record.actual.id,atom);atoms.push(atom);}
      scopes.get(record.actual.id).records.push({...record,id});
    }else atoms.push({text:record.text,records:[{...record,id}],actual:false});
  });
  for(const atom of atoms){
    const base=atom.records.reduce((a,b)=>a.w>=b.w?a:b);
    Object.assign(atom,{x:Math.min(...atom.records.map(r=>r.x)),right:Math.max(...atom.records.map(r=>r.x+r.w)),y:base.y,h:base.h,font:base.font});
    atom.eligible=atom.records.every(r=>r.eligible)&&!atom.text.includes('\0')&&!/\s/u.test(atom.text.trim());
  }
  return atoms;
}

function logicalText(atoms){
  const count=atoms.reduce((n,a)=>n+(rtl.test(a.text)?a.text.length:0),0);
  const total=atoms.reduce((n,a)=>n+([...a.text].filter(c=>letter.test(c)).length),0);
  const direction=count>total/2?'rtl':'ltr';
  const ordered=direction==='rtl'?[...atoms].reverse():[...atoms];
  const strong=a=>rtl.test(a.text)?'rtl':letter.test(a.text)?'ltr':null;
  let output='',pending=[];
  const flush=()=>{output+=pending.reverse().map(a=>a.text).join('');pending=[];};
  ordered.forEach((atom,i)=>{
    let d=strong(atom);
    if(!d){const left=[...ordered.slice(0,i)].reverse().find(a=>strong(a)),right=ordered.slice(i+1).find(a=>strong(a));d=left&&right&&strong(left)===strong(right)?strong(left):direction;}
    if(d!==direction)pending.push(atom);else{flush();output+=atom.text;}
  });flush();
  return {text:output,dir:direction};
}

export function planGlyphs(capture,settings){
  const masks=capture.runs.map(n=>Array(n).fill(false)),groups=new Map(),repairs=[];
  for(const atom of atomsFromRecords(capture.records)){if(!groups.has(atom.font))groups.set(atom.font,[]);groups.get(atom.font).push(atom);}
  for(const atoms of groups.values()){
    const lines=[];
    for(const atom of atoms.sort((a,b)=>a.y-b.y||a.x-b.x)){
      let line=lines.slice(-3).reverse().find(l=>Math.abs(l[0].y-atom.y)<=Math.max(l[0].h,atom.h)*.32&&Math.abs(l[0].h-atom.h)<Math.max(1,atom.h*.15));
      if(!line){line=[];lines.push(line);}line.push(atom);
    }
    const segments=[];
    for(const line of lines){
      let segment=[],edge=null;
      for(const atom of line.sort((a,b)=>a.x-b.x)){
        if(edge!==null&&atom.x-edge>atom.h*2){segments.push(segment);segment=[];}
        segment.push(atom);edge=Math.max(edge??atom.right,atom.right);
      }
      if(segment.length)segments.push(segment);
    }
    for(const line of segments){
      const ordered=[];let right=null;
      for(const atom of line.sort((a,b)=>a.x-b.x)){
        if(right!==null&&atom.x-right>atom.h*.18&&ordered.length&&!/\s$/u.test(ordered.at(-1).text))ordered.push({text:' ',records:[],x:right,right:atom.x,y:atom.y,h:atom.h,font:atom.font,eligible:false});
        ordered.push(atom);right=Math.max(right??atom.right,atom.right);
      }
      let text='';const spans=[];
      for(const atom of ordered){const start=text.length;text+=atom.text;spans.push({start,end:text.length,atom});}
      if(text.includes('\0'))continue;
      const flags=new Uint8Array(text.length);
      if(!/[=+<>∑∫√±×÷≤≥∞]/u.test(text)&&!/https?:\/\/|www\.|@|_/i.test(text)&&!/^[A-Za-z]{1,4}$/.test(text)){
        for(const word of wordSpans(text,settings.locale||'auto')){
          if(/^[A-ZА-ЯЁΑ-Ω]{1,5}$/u.test(word.segment))continue;
          let start=word.index,end=start+prefixLength(word.segment,settings.rule,settings.locale||'auto');
          if(rtl.test(word.segment)){
            const g=[...graphemes.segment(word.segment)].map(s=>s.segment),n=g.length<2?0:Math.ceil(g.length/2);
            end=start+word.segment.length;start=end-(n?g.slice(-n).join('').length:0);
          }
          flags.fill(1,start,end);
        }
      }
      for(const {start,end,atom} of spans)if(atom.eligible&&flags.slice(start,end).some(Boolean))for(const record of atom.records)masks[record.run][record.index]=true;
      if(line.some(a=>a.actual)&&line.every(a=>a.records.every(r=>Math.abs(r.h)>0))){
        const logical=logicalText(ordered);
        repairs.push({str:logical.text,dir:logical.dir,x:line[0].x,y:line[0].y,width:right-line[0].x,height:line[0].h,fontName:line[0].font});
      }
    }
  }
  return {masks,repairs};
}

export function repairTextContent(content,repairs,viewport){
  if(!repairs.length)return content;
  const replaced=new Set(),insertions=new Map();
  for(const repair of repairs){
    const candidates=[];let crossing=false;
    content.items.forEach((item,i)=>{
      if(typeof item.str!=='string'||!item.transform)return;
      const [x,y]=viewport.convertToViewportPoint(item.transform[4],item.transform[5]);
      const tolerance=repair.height*.2;
      if(Math.abs(y-repair.y)>repair.height*.4||x+item.width<repair.x-tolerance||x>repair.x+repair.width+tolerance)return;
      if(x<repair.x-tolerance||x+item.width>repair.x+repair.width+tolerance){crossing=true;return;}
      candidates.push([i,item]);
    });
    if(crossing||!candidates.length)continue;
    const fontName=content.styles[repair.fontName]?repair.fontName:candidates[0][1].fontName;
    const [x,y]=viewport.convertToPdfPoint(repair.x,repair.y);
    candidates.forEach(([i])=>replaced.add(i));
    insertions.set(candidates[0][0],{str:repair.str,dir:repair.dir,width:repair.width,height:repair.height,transform:[repair.height,0,0,repair.height,x,y],fontName,hasEOL:true});
  }
  // Retain the source reading order, including multicolumn documents.
  const combined=[];
  content.items.forEach((item,i)=>{if(insertions.has(i))combined.push(insertions.get(i));if(!replaced.has(i))combined.push(item);});
  return {...content,items:combined};
}
