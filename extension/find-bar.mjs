import {BookSearch} from './search.mjs';
import {markMatch} from './page-view.mjs';

export function installFindBar({currentPosition, showPage, recordJump}) {
  const byId = id => document.getElementById(id);
  const bar = byId('find-bar'), input = byId('find-query'), status = byId('find-status');
  const toggle = byId('find-toggle'), frame = byId('page-frame');
  let book, timer, searchStart, hasReturnEntry = false, reveal = false;

  function clearMatch() {
    clearTimeout(timer);
    book?.clear();
    reveal = false;
    markMatch(null);
    status.textContent = '';
  }
  function clear() {
    clearMatch();
    searchStart = null;
    hasReturnEntry = false;
  }
  function open(visible) {
    bar.hidden = !visible;
    toggle.setAttribute('aria-expanded', String(visible));
    if (visible) {
      input.focus();
      input.select();
    } else {
      clear();
      toggle.focus();
    }
  }
  function paint() {
    const match = book.match;
    if (!match || frame.dataset.renderedPage !== String(match.page)) { markMatch(null); return; }
    const visible = markMatch(match, reveal);
    if (reveal) hasReturnEntry = recordJump(searchStart, currentPosition(), hasReturnEntry);
    reveal = false;
    status.textContent = `第 ${match.page} 页 · 本页第 ${match.index + 1}/${match.count} 处`
      + (visible ? '' : '（无可显示的位置）');
  }
  async function find(step) {
    clearTimeout(timer);
    if (!book || !input.value.trim()) { clear(); return; }
    try {
      const match = await book.find(input.value, currentPosition().number, step,
        page => { status.textContent = `正在查找第 ${page} 页…`; });
      if (match === undefined) return;
      if (!match) {
        markMatch(null);
        status.textContent = '全书没有找到匹配文字';
      } else {
        // One search can visit many matches. Back returns to where reading was interrupted.
        searchStart ??= currentPosition();
        reveal = true;
        if (frame.dataset.renderedPage === String(match.page)) paint();
        else await showPage(match.page);
      }
    } catch {
      clear();
      status.textContent = '无法完成全文查找，请重试';
    }
  }
  toggle.addEventListener('click', () => open(bar.hidden));
  byId('find-close').addEventListener('click', () => open(false));
  byId('find-prev').addEventListener('click', () => find(-1));
  byId('find-next').addEventListener('click', () => find(1));
  input.addEventListener('input', () => {
    clearMatch();
    if (input.value.trim()) timer = setTimeout(() => find(1), 180);
  });
  document.addEventListener('keydown', event => {
    if (!book || event.isComposing || document.querySelector('dialog[open]')) return;
    if ((event.ctrlKey || event.metaKey) && event.code === 'KeyF') {
      event.preventDefault();
      open(true);
    } else if (!bar.hidden && event.key === 'Escape') {
      event.preventDefault();
      open(false);
    } else if (event.target === input && event.key === 'Enter') {
      event.preventDefault();
      find(event.shiftKey ? -1 : 1);
    }
  });
  return {
    clear,
    reset(pdf, locale, originalLayers) {
      clear();
      book = new BookSearch(pdf, locale, originalLayers);
      bar.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      input.value = '';
    },
    setLocale(locale) {
      if (!book) return;
      book.setLocale(locale);
      if (!bar.hidden && input.value.trim()) find(1);
    },
    rendered(number, items) {
      if (book.remember(number, items)) find();
      else paint();
    },
  };
}
