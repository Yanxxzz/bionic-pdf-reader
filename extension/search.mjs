// Keep only folded page text in the book index. Character offsets are needed
// for the single visible match, where ligatures can expand to multiple letters.
export function foldText(value, offsets) {
  let text = '';
  for (const match of value.matchAll(/\s+|\S\p{M}*/gu)) {
    const original = match[0];
    const folded = /^\s/u.test(original) ? ' ' :
      original.normalize('NFKC').toLowerCase().replaceAll('ς', 'σ').replaceAll('\u00ad', '');
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

export function occurrences(text, query) {
  const matches = [];
  if (!query) return matches;
  for (let i = text.indexOf(query); i >= 0; i = text.indexOf(query, i + query.length)) matches.push(i);
  return matches;
}

export class BookSearch {
  constructor(pdf) {
    this.pdf = pdf;
    this.pages = new Map();
  }

  remember(number, items) {
    this.pages.set(number, foldText(pageText(items)));
  }

  async find(query, number, direction, previous, cancelled, progress) {
    const total = this.pdf.numPages;
    for (let step = 0; step < total + (previous ? 1 : 0); ++step) {
      const page = 1 + ((number - 1 + direction * step + total) % total);
      if (!this.pages.has(page)) {
        progress(page);
        const proxy = await this.pdf.getPage(page);
        if (cancelled()) return null;
        const content = await proxy.getTextContent({includeMarkedContent: true});
        if (cancelled()) return null;
        if (!this.pages.has(page)) this.remember(page, content.items);
      }
      const matches = occurrences(this.pages.get(page), query);
      let index = direction === 1 ? 0 : matches.length - 1;
      if (step === 0 && previous) index = previous.index + direction;
      if (index >= 0 && index < matches.length) return {page, index, count: matches.length, query};
    }
    return null;
  }
}

export function matchRanges(items, divs, {query, index}) {
  const offsets = [];
  const positions = occurrences(foldText(pageText(items), offsets), query);
  if (index >= positions.length) return [];
  const start = offsets[positions[index]][0], end = offsets[positions[index] + query.length - 1][1];
  const ranges = [];
  let cursor = 0;
  for (const [i, item] of items.entries()) {
    const next = cursor + item.str.length;
    if (next > start && cursor < end && divs[i]?.firstChild && item.str.length) {
      const range = document.createRange();
      const first = Math.max(0, start - cursor), last = Math.min(item.str.length, end - cursor);
      range.setStart(divs[i].firstChild, first);
      range.setEnd(divs[i].firstChild, last);
      // Tagged tab stops have physical glyph bounds. A browser's substitute font
      // can measure their text differently at each zoom level.
      const left = item.glyphBounds?.[first], right = item.glyphBounds?.[last - 1];
      ranges.push({range, bounds: left && right ? [left[0], right[1]] : null});
    }
    cursor = next + (item.hasEOL ? 1 : 0);
    if (cursor >= end) break;
  }
  return ranges;
}
