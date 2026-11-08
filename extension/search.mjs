// Keep only folded page text in the book index. Character offsets are needed
// for the single visible match, where ligatures can expand to multiple letters.
export function foldText(value, offsets, locale = 'auto') {
  let text = '';
  // In untagged mixed text, Turkish letters give an otherwise ambiguous I its
  // dotless spelling. This substitution preserves every source offset.
  if (locale === 'auto' && value.includes('I')) {
    value = value.replace(/[\p{L}\p{M}]+/gu, word =>
      /[İıĞğŞş]/u.test(word) ? word.replace(/I(?!\u0307)/gu, 'ı') : word);
  }
  // Reserve a newline in the index for a hyphen between letters at a line break.
  // Ordinary line breaks remain searchable as spaces.
  const parts = /(?<=[\p{L}\p{M}])[-\u2010\u00ad][^\S\r\n]*(?:\r\n?|\n)[^\S\r\n]*(?=\p{L})|\s+|\S\p{M}*/gu;
  for (const match of value.matchAll(parts)) {
    const original = match[0];
    let folded;
    if (/^\s/u.test(original)) folded = ' ';
    else if (/[\r\n]/u.test(original)) folded = '\n';
    else {
      const normalized = original.normalize('NFKC');
      folded = locale === 'tr' && /[Iİ]/u.test(normalized)
        ? normalized.toLocaleLowerCase('tr') : normalized.toLowerCase();
      folded = folded.replaceAll('ß', 'ss').replaceAll('ς', 'σ').replaceAll('\u2010', '-').replaceAll('\u00ad', '');
      if (locale === 'auto') folded = folded.replaceAll('i\u0307', 'i');
    }
    text += folded;
    if (offsets) {
      for (let i = 0; i < folded.length; ++i) offsets.push([match.index, match.index + original.length]);
    }
  }
  return text;
}

export function pageText(items) {
  let text = '', replacementDepth = 0;
  for (const item of items) {
    if (typeof item.str === 'string') {
      if (!replacementDepth) text += item.str;
      if (item.hasEOL) text += '\n';
    } else if (item.type === 'endMarkedContent') {
      if (replacementDepth) --replacementDepth;
    } else if (replacementDepth) {
      ++replacementDepth;
    } else if (typeof item.actualText === 'string') {
      text += item.actualText;
      replacementDepth = 1;
    }
  }
  return text;
}

function wrappedMatchEnd(text, start, query) {
  let pos = start, typed = 0;
  while (typed < query.length) {
    if (text[pos] === '\n') {
      // At a discretionary break the user may omit the hyphen or type "-"/"- ".
      if (query[typed] === '-') typed += query[typed + 1] === ' ' ? 2 : 1;
    } else if (text[pos] === query[typed]) {
      ++typed;
    } else {
      return -1;
    }
    ++pos;
  }
  return pos;
}

export class BookSearch {
  #pages = new Map();
  #visible = null;
  #selected = null;
  #query = '';
  #revision = 0;

  constructor(pdf, locale = 'auto') {
    this.pdf = pdf;
    this.locale = locale;
    this.direction = 1;
  }

  clear() {
    ++this.#revision;
    this.#selected = null;
  }

  setLocale(locale) {
    this.clear();
    this.locale = locale;
    this.#pages.clear();
    const visible = this.#visible;
    this.#visible = null;
    if (visible) this.remember(visible.page, visible.items);
  }

  get match() {
    if (!this.#selected) return null;
    const {page, index, hits} = this.#selected;
    const [first, last] = hits[index];
    const visible = this.#visible?.page === page ? this.#visible : null;
    if (visible && !visible.offsets) {
      visible.offsets = [];
      foldText(pageText(visible.items), visible.offsets, this.locale);
    }
    const offsets = visible?.offsets;
    return {page, index, count: hits.length, start: offsets?.[first][0], end: offsets?.[last - 1][1]};
  }

  #hits(text) {
    const hits = [];
    const wrapped = text.includes('\n');
    const haystack = wrapped ? text.replaceAll('\n', '-') : text;
    const needle = wrapped ? this.#query[0] : this.#query;
    let start = haystack.indexOf(needle);
    while (start >= 0) {
      const end = wrapped ? wrappedMatchEnd(text, start, this.#query) : start + needle.length;
      if (end > start) hits.push([start, end]);
      start = haystack.indexOf(needle, end > start ? end : start + 1);
    }
    return hits;
  }

  remember(page, items) {
    if (this.#visible?.items === items && this.#visible.page === page) return;
    const offsets = this.#selected?.page === page ? [] : null;
    const text = foldText(pageText(items), offsets, this.locale);
    const old = this.#pages.get(page);
    this.#visible = {page, items, offsets};
    this.#pages.set(page, text);
    // The rendered page can repair the worker's spelling. Reconcile before painting.
    if (this.#selected?.page === page && old !== text) {
      const hits = this.#hits(text);
      const index = Math.min(this.#selected.index, hits.length - 1);
      this.#selected = hits.length ? {page, hits, index} : null;
      return !hits.length;
    }
  }

  async find(value, number, direction = this.direction, progress = () => {}) {
    const query = foldText(value.trim(), null, this.locale).replaceAll('\n', '-');
    const revision = ++this.#revision;
    if (!query) { this.#selected = null; return null; }
    this.direction = direction;
    if (query !== this.#query) {
      this.#query = query;
      this.#selected = null;
    }
    const previous = this.#selected?.page === number ? this.#selected : null;
    const total = this.pdf.numPages;
    for (let step = 0; step < total + (previous ? 1 : 0); ++step) {
      const page = 1 + ((number - 1 + direction * step + total) % total);
      if (!this.#pages.has(page)) {
        progress(page);
        try {
          const proxy = await this.pdf.getPage(page);
          if (revision !== this.#revision) return;
          const content = await proxy.getTextContent({includeMarkedContent: true});
          if (revision !== this.#revision) return;
          if (!this.#pages.has(page)) this.#pages.set(page, foldText(pageText(content.items), null, this.locale));
        } catch (error) {
          if (revision !== this.#revision) return;
          throw error;
        }
      }
      const hits = this.#selected?.page === page ? this.#selected.hits : this.#hits(this.#pages.get(page));
      let index = direction === 1 ? 0 : hits.length - 1;
      if (step === 0 && previous) index = previous.index + direction;
      if (index >= 0 && index < hits.length) {
        this.#selected = {page, index, hits};
        return this.match;
      }
    }
    this.#selected = null;
    return null;
  }
}
