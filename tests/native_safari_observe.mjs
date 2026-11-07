// Observe the unchanged reader. File selection and navigation come from the native window.
const send = e => fetch('/proof', {method: 'POST', body: JSON.stringify(e)});
const digest = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), x => x.toString(16).padStart(2, '0')).join('');
const frame = document.querySelector('#page-frame');
const button = document.querySelector('#open-file');
function colors(options) {
  try {
    const c = document.createElement('canvas');
    c.width = c.height = 4;
    const ctx = c.getContext('2d', options);
    return ['red','blue'].map(color => {
      ctx.fillStyle = color;
      ctx.fillRect(0,0,4,4);
      return Array.from(ctx.getImageData(1,1,1,1).data);
    });
  } catch (e) { return String(e); }
}
function buttonPoint() {
  const r = button.getBoundingClientRect();
  return {x: screenX + r.x + r.width / 2, y: screenY + outerHeight - innerHeight + r.y + r.height / 2,
    screenX, screenY, outerHeight, innerHeight, width: window.innerWidth, ua: navigator.userAgent};
}
document.addEventListener('click', e => send({kind: 'click', target: e.target.closest('button')?.id || e.target.id, trusted: e.isTrusted, x: e.clientX, y: e.clientY}), true);
document.querySelector('#file-input').addEventListener('change', async e => {
  const f = e.target.files[0];
  try { await send({kind:'file', name:f.name, sha: await digest(await f.arrayBuffer()), trusted:e.isTrusted}); }
  catch (error) { await send({kind:'error', message:String(error)}); }
});
document.addEventListener('keydown', e => send({kind:'key', code:e.code, trusted:e.isTrusted}), true);
let revision;
new MutationObserver(async () => {
  if (frame.dataset.renderState !== 'ready' || !frame.dataset.renderRevision || revision === frame.dataset.renderRevision) return;
  revision = frame.dataset.renderRevision;
  try {
    const canvas = document.querySelector('#pdf-canvas');
    const {data} = canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height);
    let ink = false;
    for (let i=0; i<data.length && !ink; i+=4) ink = data[i+3]>0 && data[i]<220;
    const layer = document.querySelector('#text-layer');
    const range = document.createRange(); range.selectNodeContents(layer);
    const snapshot = {kind:'render', rev:revision, file:document.querySelector('#file-name').textContent,
      page:Number(frame.dataset.renderedPage), mode:frame.dataset.mode, text:layer.textContent,
      selection:range.toString(), count:Number(canvas.dataset.boldGlyphs), ink, width:canvas.width, height:canvas.height};
    snapshot.pixels = await digest(data);
    await send(snapshot);
  } catch (error) { await send({kind:'error',message:String(error),gpu:colors({}),cpu:colors({willReadFrequently:true})}); }
}).observe(frame, {attributes:true});
const ready=setInterval(()=>{
  if(document.documentElement.dataset.readerReady!=='true')return;
  clearInterval(ready);
  send({kind:'ready',...buttonPoint(),gpu:colors({}),cpu:colors({willReadFrequently:true})});
},100);
