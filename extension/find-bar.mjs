import {BookSearch, foldText, occurrences} from './search.mjs';
import {markMatch} from './page-view.mjs';

export function installFindBar(currentPage, showPage) {
  const byId = id => document.getElementById(id);
  const bar = byId('find-bar'), input = byId('find-query'), status = byId('find-status');
  const toggle = byId('find-toggle'), frame = byId('page-frame');
  let book, match, timer, revision = 0, direction = 1, reveal = false;

  function clear() {
    ++revision;
    clearTimeout(timer);
    match = null;
    markMatch(null);
    status.textContent = '';
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
    if (!match || frame.dataset.renderedPage !== String(match.page)) return;
    const visible = markMatch(match, reveal);
    reveal = false;
    status.textContent = `第 ${match.page} 页 · 本页第 ${match.index + 1}/${match.count} 处`
      + (visible ? '' : '（无可显示的位置）');
  }
  async function find(step, restart = false) {
    clearTimeout(timer);
    const query = foldText(input.value.trim());
    if (!book || !query) { clear(); return; }
    const request = ++revision;
    direction = step;
    const number = currentPage();
    const previous = !restart && match?.query === query && match.page === number ? match : null;
    const cancelled = () => request !== revision;
    try {
      const next = await book.find(query, number, step, previous, cancelled,
        page => { status.textContent = `正在查找第 ${page} 页…`; });
      if (cancelled()) return;
      match = next;
      reveal = true;
      if (!match) {
        markMatch(null);
        status.textContent = '全书没有找到匹配文字';
      } else if (frame.dataset.renderedPage === String(match.page)) {
        paint();
      } else {
        await showPage(match.page);
      }
    } catch {
      if (!cancelled()) {
        clear();
        status.textContent = '无法完成全文查找，请重试';
      }
    }
  }
  toggle.addEventListener('click', () => open(bar.hidden));
  byId('find-close').addEventListener('click', () => open(false));
  byId('find-prev').addEventListener('click', () => find(-1));
  byId('find-next').addEventListener('click', () => find(1));
  input.addEventListener('input', () => {
    clear();
    if (input.value.trim()) timer = setTimeout(() => find(1, true), 180);
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
    reset(pdf) {
      clear();
      book = new BookSearch(pdf);
      bar.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      input.value = '';
    },
    rendered(number, items) {
      book.remember(number, items);
      if (number !== match?.page) { markMatch(null); return; }
      // The visible layer may repair unusual embedded text. Use that same spelling on revisits.
      match.count = occurrences(book.pages.get(number), match.query).length;
      if (!match.count) {
        find(direction, true);
        return;
      }
      match.index = Math.min(match.index, match.count - 1);
      paint();
    },
  };
}
