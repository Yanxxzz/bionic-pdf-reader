// Observe real native input and rendering. Never choose files or activate UI.
const post=data=>fetch('/acceptance-report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
const digest=async bytes=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
document.querySelector('#open-file').addEventListener('click',event=>post({type:'open',trusted:event.isTrusted}));
document.querySelector('#file-input').addEventListener('change',async event=>{
 const file=event.target.files[0],result={type:'file',name:file?.name,trusted:event.isTrusted};
 try{const bytes=await file.arrayBuffer();result.size=bytes.byteLength;result.sha256=await digest(bytes);}catch(error){result.error=String(error);}
 await post(result);
});
document.addEventListener('keydown',event=>post({type:'key',trusted:event.isTrusted,code:event.code,alt:event.altKey,meta:event.metaKey,target:event.target.tagName}));
let last='',busy=false;
setInterval(async()=>{
 const frame=document.querySelector('#page-frame'),ready=document.documentElement.dataset.readerReady;
 const key=JSON.stringify([ready,frame.dataset.renderRevision,frame.dataset.renderState]);
 if(key===last||busy)return;busy=true;
 try{
  if(ready==='true'&&frame.dataset.renderState!=='ready'){last=key;const r=document.querySelector('#open-file').getBoundingClientRect();await post({type:'ready',ua:navigator.userAgent,visible:document.visibilityState,title:document.title,openBounds:{x:r.x,y:r.y,width:r.width,height:r.height},viewport:{width:innerWidth,height:innerHeight},bodyText:document.body.innerText.slice(0,500)});return;}
  if(frame.dataset.renderState!=='ready')return;
  const canvas=document.querySelector('#pdf-canvas'),blob=await new Promise(resolve=>canvas.toBlob(resolve));
  await post({type:'render',revision:frame.dataset.renderRevision,page:Number(frame.dataset.renderedPage),mode:frame.dataset.mode,name:document.querySelector('#file-name').textContent,text:document.querySelector('#text-layer').textContent,pixels:await digest(await blob.arrayBuffer()),boldGlyphs:Number(canvas.dataset.boldGlyphs),scrollY});last=key;
 }finally{busy=false;}
},100);
