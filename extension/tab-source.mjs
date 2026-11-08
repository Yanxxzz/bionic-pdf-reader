import {getPdfFilenameFromUrl} from './vendor/pdf.mjs';
import {clearTabView, digestBytes, savedTabView} from './reading-progress.mjs';

// Runs in the clicked tab. Viewers can serve a PDF without a .pdf filename.
function isPdfDocument() {
  return ['application/pdf', 'application/x-pdf'].includes(document.contentType)
    || document.querySelector('embed[type="application/pdf"]')?.src === location.href;
}

const fileAccessHelp = '在扩展详情中启用「允许访问文件网址」，即可直接打开本地 PDF。也可点「打开 PDF」选择文件。';
const sourceChanged = '原标签页已关闭或已打开其他文档。请点「打开 PDF」重新选择文件。';
const reselectFile = '本标签页的临时文件已不可用。请点「打开 PDF」重新选择，可以继续上次的进度。';
let fileRegistration, registering, selectedFile;
const firefoxBackground = location.protocol === 'moz-extension:' ? globalThis.browser?.runtime : null;

export function prepareFileHandoff() {
  if (firefoxBackground) return;
  registering ??= (async () => {
    try {
      // A separate scope keeps this worker independent of the extension toolbar.
      fileRegistration = await navigator.serviceWorker.register('./file-handoff.mjs', {scope:'./file-handoff/', type:'module'});
    } catch { /* The reader also works where service workers are disabled. */ }
    return fileRegistration;
  })();
  return registering;
}

export function rememberSelectedFile(file, documentId) {
  selectedFile = file instanceof File ? {documentId, file} : null;
}

addEventListener('pagehide', () => {
  if (selectedFile) {
    if (firefoxBackground) {
      firefoxBackground.sendMessage({kind:'selected-file', ...selectedFile}).catch(() => {});
      return;
    }
    try { fileRegistration?.active?.postMessage(selectedFile); } catch {}
  }
});

async function takeSelectedFile(documentId) {
  if (firefoxBackground) {
    try { return await firefoxBackground.sendMessage({kind:'selected-file', documentId}); } catch { return null; }
  }
  const worker = (await prepareFileHandoff())?.active;
  if (!worker) return null;
  const {port1, port2} = new MessageChannel();
  return new Promise(resolve => {
    function finish(file) {
      clearTimeout(timer);
      port1.close();
      resolve(file);
    }
    const timer = setTimeout(() => finish(null), 3000);
    port1.onmessage = event => finish(event.data);
    port1.onmessageerror = () => finish(null);
    try { worker.postMessage({documentId}, [port2]); } catch { finish(null); }
  });
}

function initialDestination(hash) {
  const fragment = hash.slice(1);
  const params = new URLSearchParams(fragment.replaceAll('#', '&').replaceAll('+', '%2B'));
  // Older links use the destination name itself, e.g. #Table.
  if (!fragment.includes('=')) return {named: params.keys().next().value};
  let initialPage, named;
  for (const [key, value] of params) {
    if (key === 'nameddest' && value) named = value;
    if (key === 'page') {
      const page = Number(value);
      if (/^\d+$/.test(value) && Number.isSafeInteger(page) && page > 0) {
        initialPage = page;
        named = null;
      }
    }
  }
  return {initialPage, named};
}

export async function initialPdf() {
  const handoff = /^#selected=([\w-]+)$/.exec(location.hash);
  if (handoff && location.protocol === 'http:' && location.hostname === '127.0.0.1') {
    history.replaceState(null, '', location.pathname + location.search);
    const response = await fetch('/selected/' + handoff[1], {cache:'no-store'});
    if (!response.ok) throw new Error('所选文件已不可用，请在制作工具中重新点「在浏览器中阅读」。');
    const name = decodeURIComponent(response.headers.get('X-PDF-Name') || 'document.pdf');
    return {file: new File([await response.blob()], name, {type:'application/pdf'})};
  }
  const clicked = location.hash === '#current-tab';
  let resume;
  if (!clicked && performance.getEntriesByType('navigation')[0]?.type === 'reload') {
    resume = savedTabView();
  } else {
    clearTabView();
  }
  if (resume?.local && resume.documentId) {
    const file = await takeSelectedFile(resume.documentId);
    if (!file) throw new Error(reselectFile);
    return {file, resume};
  }
  const api = globalThis.browser || globalThis.chrome;
  if (!api?.tabs) return null;
  if (!clicked && !resume?.sourceKey) return null;
  if (clicked) history.replaceState(null, '', location.pathname + location.search);
  const reader = await api.tabs.getCurrent();
  const tab = reader?.openerTabId == null ? null : await api.tabs.get(reader.openerTabId).catch(() => null);
  if (resume && !tab?.url) throw new Error(sourceChanged);
  if (!tab) return null;
  const url = tab.url && new URL(tab.url);
  // Chromium can omit the source URL when file access is disabled.
  if ((!url || url.protocol === 'file:') && location.protocol === 'chrome-extension:' &&
      !(await api.extension.isAllowedFileSchemeAccess())) throw new Error(fileAccessHelp);
  if (!url) return null;
  if (!['file:', 'http:', 'https:'].includes(url.protocol)) {
    if (resume) throw new Error(sourceChanged);
    if (url.protocol === 'blob:' || /^data:application\/(x-)?pdf\b/i.test(tab.url)) {
      throw new Error('如果原标签页显示的是 PDF，请先保存这份临时文件，再点「打开 PDF」。');
    }
    return null;
  }
  const hash = url.hash;
  url.hash = '';
  // Bind reload to the original document without putting private paths or access tokens in history.
  const sourceKey = await digestBytes(new TextEncoder().encode(url.href));
  if (resume && resume.sourceKey !== sourceKey) throw new Error(sourceChanged);
  // Built-in viewers that block script injection may still expose a PDF filename.
  const isPDF = await api.scripting.executeScript({target: {tabId: tab.id}, func: isPdfDocument})
    .then(([frame]) => frame?.result, () => Boolean(getPdfFilenameFromUrl(tab.url, '')));
  if (!isPDF) {
    if (resume) throw new Error(sourceChanged);
    return null;
  }
  return {resume, file: {url: url.href, name: getPdfFilenameFromUrl(url.href, '当前文档.pdf'),
    type: 'application/pdf', sourceKey, ...initialDestination(clicked ? hash : '')}};
}
