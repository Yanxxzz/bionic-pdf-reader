import {getPdfFilenameFromUrl} from './vendor/pdf.mjs';

// Runs in the clicked tab. Viewers can serve a PDF without a .pdf filename.
function isPdfDocument() {
  return ['application/pdf', 'application/x-pdf'].includes(document.contentType)
    || document.querySelector('embed[type="application/pdf"]')?.src === location.href;
}

const fileAccessHelp = '在扩展详情中启用「允许访问文件网址」，即可直接打开本地 PDF。也可点「打开 PDF」选择文件。';

export async function pdfFromOpener() {
  const api = globalThis.browser || globalThis.chrome;
  if (location.hash !== '#current-tab' || !api?.tabs) return null;
  history.replaceState(history.state, '', location.pathname + location.search);
  const reader = await api.tabs.getCurrent();
  if (reader?.openerTabId == null) return null;
  const tab = await api.tabs.get(reader.openerTabId).catch(() => null);
  if (!tab) return null;
  const url = tab.url && new URL(tab.url);
  // Chromium can omit the source URL when file access is disabled.
  if ((!url || url.protocol === 'file:') && location.protocol === 'chrome-extension:' &&
      !(await api.extension.isAllowedFileSchemeAccess())) throw new Error(fileAccessHelp);
  if (!url) return null;
  if (url.protocol === 'blob:' || /^data:application\/(x-)?pdf\b/i.test(tab.url)) {
    throw new Error('如果原标签页显示的是 PDF，请先保存这份临时文件，再点「打开 PDF」。');
  }
  if (!['file:', 'http:', 'https:'].includes(url.protocol)) return null;
  try {
    const [frame] = await api.scripting.executeScript({target: {tabId: tab.id}, func: isPdfDocument});
    if (!frame?.result) return null;
  } catch {
    // Some built-in PDF viewers prevent script injection. The PDF parser
    // still validates the response before it replaces the open document.
    if (!getPdfFilenameFromUrl(tab.url, '')) return null;
  }
  const requestedPage = Number(new URLSearchParams(url.hash.slice(1)).get('page'));
  url.hash = '';
  return {url: url.href, name: getPdfFilenameFromUrl(url.href, '当前文档.pdf'), type: 'application/pdf',
    initialPage: Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : null};
}
