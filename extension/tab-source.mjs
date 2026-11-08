import {getPdfFilenameFromUrl} from './vendor/pdf.mjs';

// Runs in the clicked tab. Viewers can serve a PDF without a .pdf filename.
function isPdfDocument() {
  return ['application/pdf', 'application/x-pdf'].includes(document.contentType)
    || document.querySelector('embed[type="application/pdf"]')?.src === location.href;
}

const fileAccessHelp = '在扩展详情中启用「允许访问文件网址」，即可直接打开本地 PDF。也可点「打开 PDF」选择文件。';
const sourceChanged = '原标签页已关闭或已打开其他文档。请点「打开 PDF」重新选择文件。';
const tabViewKey = 'bionic-tab-view';

export function rememberTabView(source, position) {
  try {
    if (source) sessionStorage.setItem(tabViewKey, JSON.stringify({...source, position}));
    else sessionStorage.removeItem(tabViewKey);
  } catch {}
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

export async function pdfFromOpener() {
  const api = globalThis.browser || globalThis.chrome;
  if (!api?.tabs) return null;
  const clicked = location.hash === '#current-tab';
  let resume;
  if (!clicked && performance.getEntriesByType('navigation')[0]?.type === 'reload') {
    try { resume = JSON.parse(sessionStorage.getItem(tabViewKey)); } catch {}
  } else {
    rememberTabView(null);
  }
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
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(url.href));
  const sourceKey = btoa(String.fromCharCode(...new Uint8Array(digest)));
  if (resume && resume.sourceKey !== sourceKey) throw new Error(sourceChanged);
  // Built-in viewers that block script injection may still expose a PDF filename.
  const isPDF = await api.scripting.executeScript({target: {tabId: tab.id}, func: isPdfDocument})
    .then(([frame]) => frame?.result, () => Boolean(getPdfFilenameFromUrl(tab.url, '')));
  if (!isPDF) {
    if (resume) throw new Error(sourceChanged);
    return null;
  }
  return {url: url.href, name: getPdfFilenameFromUrl(url.href, '当前文档.pdf'), type: 'application/pdf',
    sourceKey, resume, ...initialDestination(clicked ? hash : '')};
}
