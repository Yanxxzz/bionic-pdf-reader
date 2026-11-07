import './compat.mjs';
import * as pdfjs from './vendor/pdf.mjs';
import { prefixLength } from './words.mjs';
import {fitWidthChanged, renderPage, resetPageView} from './page-view.mjs';

// Create a packaged module worker directly: extension CSP does not allow blob workers.
const workerURL = new URL('./pdf-worker.mjs', import.meta.url);
pdfjs.GlobalWorkerOptions.workerSrc = workerURL.href;
pdfjs.GlobalWorkerOptions.workerPort = new Worker(workerURL, { type: 'module' });
const $ = id => document.getElementById(id);
const settings = { enabled: false, rule: 'reference', strength: 1, locale: 'auto' };
try { Object.assign(settings, JSON.parse(localStorage.getItem('bionic-pdf-settings') || '{}')); } catch {}
let pdf = null, loadingTask = null, pageNumber = 1, pageLabels = null;
let loadRevision = 0, messageTimer = null;
if(![...$('language').options].some(option=>option.value===settings.locale))settings.locale='auto';

function notify(text) {
  clearTimeout(messageTimer);
  $('message').textContent = text;
  $('message').hidden = false;
  messageTimer = setTimeout(() => { $('message').hidden = true; }, 9000);
}
function persistSettings() {
  try { localStorage.setItem('bionic-pdf-settings', JSON.stringify(settings)); } catch {}
}
function updateModeUI() {
  $('original-mode').classList.toggle('selected', !settings.enabled);
  $('bionic-mode').classList.toggle('selected', settings.enabled);
  $('original-mode').setAttribute('aria-pressed', String(!settings.enabled));
  $('bionic-mode').setAttribute('aria-pressed', String(settings.enabled));
  $('rule').value = settings.rule;
  $('language').value = settings.locale;
  $('strength').value = Math.round(settings.strength * 100);
  $('strength-value').textContent = `${Math.round(settings.strength * 100)}%`;
  $('rule-note').textContent = settings.rule === 'half'
    ? '强调每个单词前半部分的字母，保留原来的字符间距。'
    : '英文使用参考项目规则，其他语言按词语前半部分加粗。';
  const count = prefixLength('Reading', settings.rule);
  const bold = document.createElement('b');
  bold.textContent = 'Reading'.slice(0, count);
  $('sample-word').replaceChildren(bold, document.createTextNode('Reading'.slice(count)));
}
function setMode(enabled) {
  if (settings.enabled === enabled) return;
  settings.enabled = enabled;
  persistSettings();
  updateModeUI();
  scheduleRender();
}

async function scheduleRender(resetScroll = false) {
  const activePDF = pdf;
  if (!activePDF) return;
  const number = pageNumber;
  const snapshot = {...settings};
  $('reading-status').textContent = '正在显示页面…';
  try {
    const result = await renderPage(activePDF, number, $('zoom').value, snapshot, resetScroll);
    if (!result || pdf !== activePDF) return;
    $('prev-page').disabled = number === 1;
    $('next-page').disabled = number === activePDF.numPages;
    const label = pageLabels?.[number - 1];
    $('page-label').textContent = label ? `书内页码 ${label}` : `PDF 第 ${number} 页`;
    let status = '原始模式';
    if (!result.hasText) status = '图片页或无可识别文字，保留原页';
    else if (snapshot.enabled) status = result.stroked ? '仿生模式 · 词首加粗' : '此页没有可加粗文字，保留原页';
    $('reading-status').textContent = status;
    try { localStorage.setItem(`bionic-page-${activePDF.fingerprints[0]}`, String(number)); } catch {}
  } catch (error) {
    if (pdf !== activePDF) return;
    $('reading-status').textContent = '此页暂时无法显示';
    notify(`无法显示此页：${error.message}`);
    console.error(error);
  }
}

function goToPage(number) {
  if (!pdf || !Number.isFinite(number)) return;
  pageNumber = Math.min(pdf.numPages, Math.max(1, Math.trunc(number)));
  $('page-number').value = pageNumber;
  scheduleRender(true);
}

async function openFile(file) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
    notify('请选择 PDF 文件。');
    return;
  }
  const currentLoad = ++loadRevision;
  pdf = null;
  await resetPageView();
  if (currentLoad !== loadRevision) return;
  await loadingTask?.destroy();
  if (currentLoad !== loadRevision) return;
  loadingTask = null;
  $('message').hidden = true;
  $('reading-status').textContent = '正在打开文件…';
  let data;
  try { data = new Uint8Array(await file.arrayBuffer()); }
  catch(error){
    if(currentLoad===loadRevision){$('reading-status').textContent='未打开文件';notify(`无法读取 PDF：${error.message}。请重新选择文件。`);}
    return;
  }
  if (currentLoad !== loadRevision) return;
  const task = pdfjs.getDocument({
    data,
    isEvalSupported: false,
    cMapUrl: new URL('./vendor/cmaps/', import.meta.url).href,
    cMapPacked: true,
    standardFontDataUrl: new URL('./vendor/standard_fonts/', import.meta.url).href,
    wasmUrl: new URL('./vendor/wasm/', import.meta.url).href,
    useWorkerFetch: true,
  });
  loadingTask = task;
  task.onPassword = (updatePassword, reason) => {
    $('pdf-password').value = '';
    $('password-dialog').querySelector('h2').textContent = reason === pdfjs.PasswordResponses.INCORRECT_PASSWORD ? '密码不正确，请重试' : '此 PDF 需要密码';
    $('password-dialog').showModal();
    $('password-dialog').addEventListener('close', () => {
      if ($('password-dialog').returnValue === 'open') updatePassword($('pdf-password').value);
      else task.destroy();
    }, { once: true });
  };
  try {
    const loadedPDF = await task.promise;
    if (currentLoad !== loadRevision) { await loadedPDF.destroy(); return; }
    const labels = await loadedPDF.getPageLabels();
    if (currentLoad !== loadRevision) return;
    pdf = loadedPDF;
    pageLabels = labels;
    pageNumber = 1;
    try { pageNumber = Math.max(1, Math.min(pdf.numPages, Number(localStorage.getItem(`bionic-page-${pdf.fingerprints[0]}`)) || 1)); } catch {}
    $('welcome').hidden = true;
    $('document').hidden = false;
    $('file-name').textContent = file.name;
    $('file-name').title = file.name;
    $('page-count').textContent = String(pdf.numPages);
    $('page-number').max = String(pdf.numPages);
    $('page-number').value = pageNumber;
    document.title = `${file.name} · 仿生 PDF 阅读`;
    await scheduleRender(true);
    if (currentLoad === loadRevision) buildOutline(loadedPDF, currentLoad);
  } catch (error) {
    if (currentLoad !== loadRevision) return;
    notify(`无法打开 PDF：${error.message}`);
  }
}

async function buildOutline(activePDF, load) {
  const outline = await activePDF.getOutline();
  if (load !== loadRevision) return;
  const root = $('outline');
  root.replaceChildren();
  if (!outline?.length) {
    const p = document.createElement('p'); p.className = 'field-note';
    p.textContent = '这个 PDF 没有内嵌目录。可以通过上方页码跳转。';
    root.append(p); return;
  }
  function append(items, container) {
    for (const item of items) {
      const wrapper = document.createElement(item.items?.length ? 'details' : 'div');
      let target = wrapper;
      if (item.items?.length) {
        const summary = document.createElement('summary');
        summary.textContent = item.title; wrapper.append(summary);
        target = document.createElement('div'); wrapper.append(target);
      }
      const button = document.createElement('button');
      button.textContent = item.title;
      button.addEventListener('click', async () => {
        if (!item.dest) return;
        const destination = typeof item.dest === 'string' ? await activePDF.getDestination(item.dest) : item.dest;
        if (!destination || load !== loadRevision) return;
        const ref = destination[0];
        const index = typeof ref === 'number' ? ref : await activePDF.getPageIndex(ref);
        if (load === loadRevision) goToPage(index + 1);
      });
      target.append(button);
      if (item.items?.length) append(item.items, target);
      container.append(wrapper);
    }
  }
  append(outline, root);
}

function chooseFile() {
  const input = $('file-input');
  if (typeof input.showPicker === 'function') input.showPicker();
  else input.click();
}
for (const id of ['open-file', 'choose-file']) $(id).addEventListener('click', chooseFile);
$('help-button').addEventListener('click', () => $('help-dialog').showModal());
$('file-input').addEventListener('change', async e => {
  const input=e.target,file=input.files[0];
  // Keep the selection while asynchronous reading and rendering finish.
  // A newer selection must not be cleared by an older load.
  try{await openFile(file);}finally{if(input.files[0]===file)input.value='';}
});
$('original-mode').addEventListener('click', () => setMode(false));
$('bionic-mode').addEventListener('click', () => setMode(true));
$('rule').addEventListener('change', e => { settings.rule = e.target.value; persistSettings(); updateModeUI(); scheduleRender(); });
$('language').addEventListener('change', e => { settings.locale = e.target.value; persistSettings(); scheduleRender(); });
let strengthTimer;
$('strength').addEventListener('input', e => {
  settings.strength = Number(e.target.value) / 100;
  updateModeUI(); persistSettings();
  clearTimeout(strengthTimer); strengthTimer = setTimeout(() => scheduleRender(), 120);
});
$('prev-page').addEventListener('click', () => goToPage(pageNumber - 1));
$('next-page').addEventListener('click', () => goToPage(pageNumber + 1));
$('page-number').addEventListener('change', e => goToPage(Number(e.target.value)));
$('page-number').addEventListener('keydown', e => { if (e.key === 'Enter') goToPage(Number(e.target.value)); });
$('zoom').addEventListener('change', () => scheduleRender());
$('outline-toggle').addEventListener('click', () => {
  $('outline').hidden = !$('outline').hidden;
  $('outline-toggle').setAttribute('aria-expanded', String(!$('outline').hidden));
});
document.addEventListener('keydown', e => {
  if(document.querySelector('dialog[open]'))return;
  if (e.altKey && e.code === 'KeyB') { e.preventDefault(); setMode(!settings.enabled); return; }
  if ((e.ctrlKey || e.metaKey) && e.code === 'KeyO') { e.preventDefault(); chooseFile(); return; }
  if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName) || getSelection()?.toString()) return;
  if (e.code === 'ArrowLeft') { e.preventDefault(); goToPage(pageNumber - 1); }
  if (e.code === 'ArrowRight') { e.preventDefault(); goToPage(pageNumber + 1); }
});
let dragCounter = 0;
document.addEventListener('dragenter', e => { e.preventDefault(); if (e.dataTransfer.types.includes('Files')) { ++dragCounter; $('drop-overlay').hidden = false; } });
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('dragleave', e => { e.preventDefault(); if (--dragCounter <= 0) { dragCounter = 0; $('drop-overlay').hidden = true; } });
document.addEventListener('drop', e => { e.preventDefault(); dragCounter = 0; $('drop-overlay').hidden = true; openFile(e.dataTransfer.files[0]); });
let resizeTimer;
addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  if (pdf && $('zoom').value === 'fit') {
    resizeTimer = setTimeout(() => {
      if (pdf && $('zoom').value === 'fit' && fitWidthChanged()) scheduleRender();
    }, 180);
  }
});
updateModeUI();
document.documentElement.dataset.readerReady='true';
