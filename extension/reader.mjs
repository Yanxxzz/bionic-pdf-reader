import './compat.mjs';
import * as pdfjs from './vendor/pdf.mjs';
import { prefixLength } from './words.mjs';
import {embeddedReadingLayer, fitWidthChanged, readingPosition, renderPage, resetPageView, resolvePosition} from './page-view.mjs';
import {installFindBar} from './find-bar.mjs';
import {externalLink, linkDestination, pageInRange, savedPosition} from './navigation.mjs';
import {initialPdf, prepareFileHandoff, rememberSelectedFile} from './tab-source.mjs';
import {clearTabView, digestBytes, ReadingProgress, savedTabView} from './reading-progress.mjs';
import {makeBackup, restoreBackup, settingsKey} from './progress-backup.mjs';

// Create a packaged module worker directly: extension CSP does not allow blob workers.
const workerURL = new URL('./pdf-worker.mjs', import.meta.url);
const worker = new pdfjs.PDFWorker({port: new Worker(workerURL, {type: 'module'})});
const $ = id => document.getElementById(id);
const settings = {enabled: false, rule: $('rule').value, strength: $('strength').valueAsNumber / 100, locale: $('language').value};
function applySettings(saved, target = settings) {
  for (const [key, control] of [['locale', $('language')], ['rule', $('rule')]]) {
    if ([...control.options].some(option => option.value === saved[key])) target[key] = saved[key];
  }
  if (typeof saved.enabled === 'boolean') target.enabled = saved.enabled;
  const slider = $('strength');
  const percent = saved.strength * 100;
  if (Number.isFinite(saved.strength) && percent >= Number(slider.min) && percent <= Number(slider.max)) {
    const step = Number(slider.step);
    target.strength = Math.round(percent / step) * step / 100;
  }
}
try { applySettings(JSON.parse(localStorage.getItem(settingsKey)) ?? {}); } catch {}
let pdf = null, loadingTask = null, pageNumber = 1, pageLabels = null, embeddedLayer = null;
let copyAllowed = true;
let loadRevision = 0, messageTimer = null;
let readingProgress, navigationRevision = 0, pendingPosition = null, openingView;
let progressTimer;
const findBar = installFindBar({
  currentPosition, recordJump,
  showPage(position) {
    ++navigationRevision;
    return showPosition(position);
  },
});

function notify(text) {
  clearTimeout(messageTimer);
  $('message').textContent = text;
  $('message').hidden = false;
  messageTimer = setTimeout(() => { $('message').hidden = true; }, 9000);
}
function persistSettings() {
  try { localStorage.setItem(settingsKey, JSON.stringify(settings)); } catch {}
}
function updateModeUI() {
  $('original-mode').classList.toggle('selected', !settings.enabled);
  $('bionic-mode').classList.toggle('selected', settings.enabled);
  $('original-mode').setAttribute('aria-pressed', String(!settings.enabled));
  $('bionic-mode').setAttribute('aria-pressed', String(settings.enabled));
  $('rule').value = settings.rule;
  $('language').value = settings.locale;
  $('strength').value = Math.round(settings.strength * 100);
  $('rule').disabled = $('strength').disabled = Boolean(embeddedLayer);
  $('sample-word').parentElement.hidden = Boolean(embeddedLayer);
  $('strength-value').textContent = embeddedLayer ? '随副本设定' : `${Math.round(settings.strength * 100)}%`;
  $('rule-note').textContent = embeddedLayer ? '这份副本已设定词首和强度。原始和仿生按钮切换内置图层，文档语言仍用于查找。'
    : settings.rule === 'half' || !['auto', 'en'].includes(settings.locale)
    ? '强调每个单词前半部分的字母，保留原来的字符间距。'
    : '英文使用参考项目规则，其他语言按词语前半部分加粗。';
  const sample = $('sample-word').textContent;
  const count = prefixLength(sample, settings.rule, settings.locale);
  const bold = document.createElement('b');
  bold.textContent = sample.slice(0, count);
  $('sample-word').replaceChildren(bold, document.createTextNode(sample.slice(count)));
}
function setMode(enabled) {
  if (settings.enabled === enabled) return;
  settings.enabled = enabled;
  persistSettings();
  updateModeUI();
  scheduleRender();
}

async function scheduleRender() {
  const activePDF = pdf;
  if (!activePDF) return;
  const number = pageNumber;
  const snapshot = {...settings};
  $('prev-page').disabled = number === 1;
  $('next-page').disabled = number === activePDF.numPages;
  $('reading-status').textContent = '正在显示页面…';
  try {
    const result = await renderPage(activePDF, number, {
      ...snapshot, zoom: $('zoom').value, position: pendingPosition, embeddedLayer,
      followDestination: dest => goToDestination(activePDF, dest),
    });
    if (!result || pdf !== activePDF) return;
    pendingPosition = null;
    findBar.rendered(number, result.items);
    const label = pageLabels?.[number - 1];
    $('page-label').textContent = label ? `书内页码 ${label}` : `PDF 第 ${number} 页`;
    let status = '原始模式';
    if (result.textKind === 'empty') status = '本页没有可识别的正文。扫描页可在桌面工具中勾选「本地 OCR」。';
    else if (result.textKind === 'symbols') status = '本页文字可搜索，没有可加粗的词首。';
    else if (embeddedLayer) status = snapshot.enabled ? '仿生模式 · 副本内置图层已开启' : '原始模式 · 副本内置图层已关闭';
    else if (snapshot.enabled) status = result.stroked ? '仿生模式 · 词首加粗' : '此页没有可加粗文字，保留原页';
    $('reading-status').textContent = status;
    saveProgress();
  } catch (error) {
    if (pdf !== activePDF) return;
    $('reading-status').textContent = '此页暂时无法显示';
    notify(`无法显示此页：${error.message}`);
    console.error(error);
  }
}

function currentPosition() {
  return pendingPosition ?? {number: pageNumber, ...readingPosition($('zoom').value)};
}

function saveProgress() {
  clearTimeout(progressTimer);
  if (!pdf) return;
  const frame = $('page-frame').dataset;
  const ready = frame.renderedPage === String(pageNumber);
  if (!ready && !(frame.renderState === 'rendering' && pendingPosition)) return;
  const position = currentPosition();
  if (ready) openingView.position ??= position;
  readingProgress.save(position, movedSinceOpening());
}

function movedSinceOpening() {
  const scroller = $('page-scroller');
  const initial = openingView.position;
  return navigationRevision !== openingView.revision || $('zoom').value !== openingView.zoom ||
    Boolean(initial && (scroller.scrollLeft !== initial.left || scroller.scrollTop !== initial.top));
}
$('page-scroller').addEventListener('scroll', () => {
  clearTimeout(progressTimer);
  progressTimer = setTimeout(saveProgress, 180);
}, {passive: true});
addEventListener('pagehide', saveProgress);
document.addEventListener('visibilitychange', () => { if (document.hidden) saveProgress(); });
function goToPage(number) {
  if (!pdf) return;
  const next = pageInRange(number, pdf.numPages, pageNumber);
  $('page-number').value = next;
  if (next === pageNumber) return;
  findBar.clear();
  ++navigationRevision;
  return showPosition({number: next, zoom: $('zoom').value});
}

function showPosition(position) {
  pageNumber = position.number;
  $('page-number').value = pageNumber;
  const zoom = $('zoom');
  if (![...zoom.options].some(option => option.value === position.zoom)) {
    zoom.querySelector('[data-custom]')?.remove();
    const option = new Option(`${Math.round(Number(position.zoom) * 100)}%`, position.zoom);
    option.dataset.custom = '';
    zoom.add(option);
  }
  zoom.value = position.zoom;
  pendingPosition = position;
  return scheduleRender();
}

async function destinationPage(activePDF, destination) {
  const dest = typeof destination === 'string' ? await activePDF.getDestination(destination) : destination;
  if (!dest) throw new Error('找不到这个链接指向的页面。');
  const ref = dest[0];
  const index = Number.isInteger(ref) ? ref : await activePDF.getPageIndex(ref);
  return {page: await activePDF.getPage(index + 1), dest};
}

function recordJump(origin, position, replace = false) {
  if (!replace && position.top !== undefined && origin.number === position.number && origin.zoom === position.zoom
      && origin.left === position.left && origin.top === position.top) return false;
  const documentId = readingProgress.documentId;
  const depth = history.state?.documentId === documentId ? history.state.depth : 0;
  if (replace && depth) {
    history.replaceState({documentId, depth, position}, '');
  } else {
    history.replaceState({documentId, depth, position: origin}, '');
    history.pushState({documentId, depth: depth + 1, position}, '');
  }
  $('return-position').disabled = false;
  return true;
}

async function goToDestination(activePDF, dest) {
  if (!dest || dest === pageNumber || pdf !== activePDF) return;
  findBar.clear();
  const revision = ++navigationRevision;
  const origin = currentPosition();
  try {
    const position = Number.isInteger(dest)
      ? {number: dest, zoom: origin.zoom}
      : resolvePosition(await destinationPage(activePDF, dest), origin);
    if (pdf !== activePDF || revision !== navigationRevision) return;
    recordJump(origin, position);
    await showPosition(position);
  } catch {
    if (pdf === activePDF && revision === navigationRevision) notify('找不到这个链接指向的页面。');
  }
}

$('return-position').addEventListener('click', () => history.back());
addEventListener('popstate', ({state}) => {
  const documentId = readingProgress?.documentId;
  $('return-position').disabled = state?.documentId !== documentId || !state?.depth;
  if (!pdf || state?.documentId !== documentId || !state.position) return;
  findBar.clear();
  ++navigationRevision;
  showPosition(state.position);
});

async function openFile(file, resume = null) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
    notify('请选择 PDF 文件。');
    return;
  }
  const currentLoad = ++loadRevision;
  if (file instanceof File) prepareFileHandoff();
  const superseded = loadingTask;
  loadingTask = null;
  const dialog = $('password-dialog');
  if (dialog.open) dialog.close('cancel');
  notify(`正在打开「${file.name}」…`);
  let task;
  let passwordCancelled = false;
  try {
    await superseded?.destroy();
    if (currentLoad !== loadRevision) return;
    const source = file.url
      ? {url: file.url, withCredentials: true, docBaseUrl: /^https?:/.test(file.url) ? file.url : undefined}
      : {data: new Uint8Array(await file.arrayBuffer())};
    if (currentLoad !== loadRevision) return;
    // Web Crypto accepts the same buffer before PDF.js transfers it to its worker.
    const localKey = source.data ? digestBytes(source.data).catch(() => null) : null;
    task = pdfjs.getDocument({
      ...source, worker, isEvalSupported: false,
      cMapUrl: new URL('./vendor/cmaps/', import.meta.url).href,
      cMapPacked: true,
      standardFontDataUrl: new URL('./vendor/standard_fonts/', import.meta.url).href,
      wasmUrl: new URL('./vendor/wasm/', import.meta.url).href,
      useWorkerFetch: true,
    });
    loadingTask = task;
    task.onPassword = (updatePassword, reason) => {
      if (task !== loadingTask) return;
      $('pdf-password').value = '';
      dialog.returnValue = 'cancel';
      dialog.querySelector('h2').textContent = reason === pdfjs.PasswordResponses.INCORRECT_PASSWORD ? '密码不正确，请重试' : '此 PDF 需要密码';
      dialog.addEventListener('close', () => {
        if (task !== loadingTask) return;
        const password = $('pdf-password').value;
        $('pdf-password').value = '';
        passwordCancelled = dialog.returnValue !== 'open';
        updatePassword(passwordCancelled ? new Error('已取消输入密码') : password);
      }, {once: true});
      dialog.showModal();
    };
    const loadedPDF = await task.promise;
    if (currentLoad !== loadRevision) return;
    const [labels, permissions, metadata, target, layer, contentKey, proof] = await Promise.all([
      loadedPDF.getPageLabels(), loadedPDF.getPermissions(), file.url ? loadedPDF.getMetadata().catch(() => null) : null,
      file.named ? destinationPage(loadedPDF, file.named).catch(() => null) : null,
      embeddedReadingLayer(loadedPDF), localKey, file.url ? loadedPDF.getBionicResumeProof().catch(() => null) : null,
    ]);
    if (currentLoad !== loadRevision) return;
    loadingTask = null;
    $('message').hidden = true;
    if (proof && metadata?.bionicETag?.startsWith('"')) proof.etag = metadata.bionicETag;
    await showDocument(loadedPDF, {name: metadata?.contentDispositionFilename || file.name, labels, permissions, file, target, resume, layer, contentKey, proof});
  } catch (error) {
    if (currentLoad === loadRevision) {
      const reason = file.url ? '请在原标签页保存文件，再点「打开 PDF」。' : error.message;
      notify(passwordCancelled ? `已取消打开「${file.name}」。` : `无法打开 PDF「${file.name}」：${reason}`);
    }
  } finally {
    if (task && loadingTask === task) {
      loadingTask = null;
      await task.destroy();
    }
  }
}

async function showDocument(loadedPDF, {name, labels, permissions, file, target, resume, layer, contentKey, proof}) {
  saveProgress();
  const previous = pdf;
  pdf = loadedPDF;
  embeddedLayer = layer;
  updateModeUI();
  findBar.reset(pdf, settings.locale, layer?.original);
  const candidate = resume ?? (!previous && file instanceof File ? savedTabView() : null);
  readingProgress = new ReadingProgress(file, candidate, Boolean(resume && file instanceof File), proof);
  const stored = contentKey ? readingProgress.identify(contentKey) : null;
  rememberSelectedFile(file, readingProgress.documentId);
  const revision = ++navigationRevision;
  $('return-position').disabled = history.state?.documentId !== readingProgress.documentId || !history.state?.depth;
  pageLabels = labels;
  copyAllowed = permissions === null || permissions.includes(pdfjs.PermissionFlag.COPY);
  const defaultZoom = $('zoom').value;
  function openingPosition(value) {
    const saved = savedPosition(value, loadedPDF.numPages, defaultZoom);
    if (target) return resolvePosition(target, {zoom:saved.zoom});
    if (file.initialPage) return {number:pageInRange(file.initialPage, loadedPDF.numPages, 1), zoom:saved.zoom};
    return saved;
  }
  $('welcome').hidden = true;
  $('document').hidden = false;
  $('file-name').textContent = name;
  $('file-name').title = name;
  $('page-count').textContent = String(pdf.numPages);
  $('page-number').max = String(pdf.numPages);
  $('page-label').textContent = '';
  $('outline').replaceChildren();
  document.title = `${name} · 仿生 PDF 阅读`;
  const position = openingPosition(stored);
  openingView = {revision, zoom:position.zoom, position:null};
  readingProgress.save(position);
  if (file.named && !target) notify('找不到链接指定的书签，已打开 PDF。');
  const reset = resetPageView();
  const rendering = showPosition(position);
  if (file.url) {
    finishUrlProgress(loadedPDF, readingProgress, proof, rendering, openingPosition);
  }
  await reset;
  await previous?.destroy();
  await rendering;
  if (pdf === loadedPDF) await buildOutline(loadedPDF);
}

async function finishUrlProgress(doc, progress, proof, rendering, openingPosition) {
  // An HTTP range document can display its first page before the remaining
  // bytes arrive. Hash the original download without issuing another request.
  try {
    await doc.getDownloadInfo();
    if (readingProgress !== progress) return;
    const bytes = await doc.getData();
    const key = proof?.key ?? await digestBytes(bytes);
    const matches = await progress.matchesPending(bytes, key);
    await rendering;
    if (readingProgress !== progress) return;
    const untouched = !movedSinceOpening();
    const stored = progress.identify(key, untouched, matches);
    $('return-position').disabled = history.state?.documentId !== progress.documentId || !history.state?.depth;
    if (stored && untouched) {
      await showPosition(openingPosition(stored));
    } else {
      saveProgress();
    }
  } catch { /* A PDF can be closed before its download completes. */ }
}

async function buildOutline(activePDF) {
  let outline;
  try { outline = await activePDF.getOutline(); }
  catch {
    if (pdf === activePDF) $('outline').textContent = '无法读取这份 PDF 的目录。';
    return;
  }
  if (pdf !== activePDF) return;
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
      const destination = () => linkDestination(item, pageNumber, activePDF.numPages);
      const internal = destination() !== null;
      const entry = internal ? document.createElement('button') : externalLink(item) || document.createElement('span');
      entry.textContent = item.title;
      if (internal) entry.addEventListener('click', () => {
        closeSidebar();
        goToDestination(activePDF, destination());
      });
      target.append(entry);
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
$('try-sample').addEventListener('click', async () => {
  const button = $('try-sample'), revision = loadRevision;
  button.disabled = true;
  try {
    const response = await fetch(new URL('assets/first-read.pdf', import.meta.url));
    if (!response.ok) throw new Error();
    const sample = new File([await response.blob()], 'A closer reading.pdf', {type:'application/pdf'});
    if (revision === loadRevision) await openFile(sample);
  } catch {
    if (revision === loadRevision) notify('无法打开内置示例，请重新解压完整的阅读器。');
  } finally { button.disabled = false; }
});
$('backup-save').addEventListener('click', () => {
  try {
    const data = makeBackup(localStorage, settings);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data)], {type:'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'bionic-reading-progress.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $('backup-status').textContent = `备份包含 ${Object.keys(data.bookmarks).length} 份文档的进度及阅读设置。`;
  } catch { $('backup-status').textContent = '无法读取进度，请检查浏览器是否允许本地存储。'; }
});
$('backup-open').addEventListener('click', () => $('backup-file').click());
$('backup-file').addEventListener('change', async event => {
  const input = event.target, file = input.files[0], revision = loadRevision;
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    if (revision !== loadRevision) return;
    const preferences = {...settings};
    applySettings(data?.settings ?? {}, preferences);
    const count = restoreBackup(data, localStorage, preferences);
    Object.assign(settings, preferences);
    clearTabView();
    updateModeUI();
    $('backup-status').textContent = `已恢复 ${count} 份文档的进度，打开原 PDF 即可续读。`;
  } catch (error) {
    $('backup-status').textContent = error instanceof SyntaxError ? '请选择有效的 JSON 进度备份。' : `导入失败。${error.message}`;
  } finally { input.value = ''; }
});
$('cancel-password').addEventListener('click', () => $('password-dialog').close('cancel'));
$('help-button').addEventListener('click', () => $('help-dialog').showModal());
document.addEventListener('copy', event => {
  if (copyAllowed || event.target.closest?.('input, textarea')) return;
  const selection = getSelection();
  for (let i = 0; i < selection.rangeCount; ++i) {
    if (selection.getRangeAt(i).intersectsNode($('text-layer'))) {
      event.preventDefault();
      notify('这份 PDF 限制复制正文。');
      return;
    }
  }
});
$('text-layer').addEventListener('dragstart', event => {
  if (!copyAllowed) event.preventDefault();
});
$('file-input').addEventListener('change', async e => {
  const input=e.target,file=input.files[0];
  // Keep the selection while asynchronous reading and rendering finish.
  // A newer selection must not be cleared by an older load.
  try{await openFile(file);}finally{if(input.files[0]===file)input.value='';}
});
$('original-mode').addEventListener('click', () => setMode(false));
$('bionic-mode').addEventListener('click', () => setMode(true));
$('rule').addEventListener('change', e => { settings.rule = e.target.value; persistSettings(); updateModeUI(); scheduleRender(); });
$('language').addEventListener('change', e => {
  settings.locale = e.target.value;
  findBar.setLocale(settings.locale);
  persistSettings(); updateModeUI(); scheduleRender();
});
let strengthTimer;
$('strength').addEventListener('input', e => {
  settings.strength = Number(e.target.value) / 100;
  updateModeUI(); persistSettings();
  clearTimeout(strengthTimer); strengthTimer = setTimeout(() => scheduleRender(), 120);
});
$('prev-page').addEventListener('click', () => goToPage(pageNumber - 1));
$('next-page').addEventListener('click', () => goToPage(pageNumber + 1));
$('page-number').addEventListener('change', e => goToPage(e.target.valueAsNumber));
$('page-number').addEventListener('keydown', e => { if (e.key === 'Enter') goToPage(e.target.valueAsNumber); });
$('zoom').addEventListener('change', () => {
  if (pdf) showPosition({...currentPosition(), zoom: $('zoom').value});
});
const sidebarToggle = $('sidebar-toggle');
function closeSidebar() {
  if (sidebarToggle.getAttribute('aria-expanded') !== 'true') return;
  sidebarToggle.setAttribute('aria-expanded', 'false');
  if (sidebarToggle.offsetWidth) sidebarToggle.focus({preventScroll:true});
}
sidebarToggle.addEventListener('click', () => {
  sidebarToggle.setAttribute('aria-expanded', String(sidebarToggle.getAttribute('aria-expanded') !== 'true'));
});
$('outline-toggle').addEventListener('click', () => {
  $('outline').hidden = !$('outline').hidden;
  $('outline-toggle').setAttribute('aria-expanded', String(!$('outline').hidden));
});
document.addEventListener('keydown', e => {
  if(document.querySelector('dialog[open]'))return;
  if (e.key === 'Escape' && (e.target === sidebarToggle || $('reading-sidebar').contains(e.target))) {
    closeSidebar();
    return;
  }
  if (e.altKey && e.code === 'KeyB') { e.preventDefault(); setMode(!settings.enabled); return; }
  if ((e.ctrlKey || e.metaKey) && e.code === 'KeyO') { e.preventDefault(); chooseFile(); return; }
  if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
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
const initialLoad = loadRevision;
initialPdf().then(initial => {
  if (initial && initialLoad === loadRevision) openFile(initial.file, initial.resume);
}).catch(error => {
  if (initialLoad === loadRevision) notify(error.message);
});
