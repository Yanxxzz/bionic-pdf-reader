import {GlyphCapture, planGlyphs} from './layout.mjs';

// Both text selection and full-book search use the same logical page. Ordinary
// pages need only the worker's text items. Tagged pages can also need painted
// positions to reconstruct the spelling and word order of ActualText spans.
export async function readPageText(page, repairs, originalLayers) {
  const content = await page.getTextContent({includeMarkedContent: true});
  const tagged = content.items.some(item => typeof item.actualText === 'string');
  if (!tagged && !repairs?.length) return repairTextContent(content, [], null);
  const viewport = page.getViewport({scale: 1});
  if (!repairs) {
    // A small, full-page canvas captures positions without allocating a display-sized bitmap.
    const scale = Math.min(1, 64 / Math.max(viewport.width, viewport.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(viewport.width * scale);
    canvas.height = Math.ceil(viewport.height * scale);
    const capture = canvas.bionicReader = new GlyphCapture(scale);
    try {
      await page.render({canvas, viewport, transform: [scale, 0, 0, scale, 0, 0],
        optionalContentConfigPromise: originalLayers && Promise.resolve(originalLayers)}).promise;
      repairs = planGlyphs(capture).repairs;
    } finally {
      canvas.width = canvas.height = 0;
      page.cleanup();
    }
  }
  return repairTextContent(content, repairs, viewport);
}

// Map a horizontal text-layer item to the glyphs actually painted on the page.
// PDF.js can insert spaces between glyphs or expand a single ligature to letters.
export function textGlyphBounds(item, records, viewport) {
  const [a, b, , , tx, ty] = item.transform;
  const [left, baseline] = viewport.convertToViewportPoint(tx, ty);
  const [along, across] = viewport.convertToViewportPoint(tx + a, ty + b);
  if (item.dir !== 'ltr' || along <= left || Math.abs(across - baseline) > 0.01) return;
  const glyphs = records.filter(glyph => {
    const mid = glyph.x + glyph.w / 2;
    return glyph.font === item.fontName && Math.abs(glyph.y - baseline) < 0.5
      && mid >= left - 0.1 && mid <= left + item.width * (viewport.userUnit ?? 1) + 0.1;
  }).sort((a, b) => a.x - b.x);
  const bounds = [];
  let at = 0;
  for (const glyph of glyphs) {
    if (!glyph.text.trim()) continue;
    while (at < item.str.length && /\s/u.test(item.str[at])) ++at;
    const text = item.str.startsWith(glyph.text, at) ? glyph.text : glyph.text.normalize('NFKC');
    if (!item.str.startsWith(text, at)) return;
    const span = [glyph.x, glyph.x + glyph.w];
    for (let i = 0; i < text.length; ++i) bounds[at++] = span;
  }
  if (!item.str.slice(at).trim()) return bounds;
}

export function repairTextContent(content, repairs, viewport) {
  // A marked span containing one positioned item gives its exact selectable spelling,
  // including spaces that glyph geometry alone cannot recover. Multi-item spans may
  // cross lines or columns and continue through the geometry-based repairs below.
  const items = [];
  for (const [i, item] of content.items.entries()) {
    if (typeof item.str !== 'string') continue;
    const label = content.items[i - 1]?.actualText;
    const single = typeof label === 'string' && content.items[i + 1]?.type === 'endMarkedContent';
    items.push(single ? {...item, str: label} : item);
  }
  content = {...content, items};
  if (!repairs.length) return content;
  const replaced = new Set(), insertions = new Map();
  const unit = viewport.userUnit ?? 1;
  for (const repair of repairs) {
    const left = repair.x - repair.height * 0.2;
    const right = repair.x + repair.width + repair.height * 0.2;
    const indices = [];
    let crossesEdge = false;
    for (const [index, item] of content.items.entries()) {
      if (typeof item.str !== 'string' || !item.transform) continue;
      const [x, y] = viewport.convertToViewportPoint(item.transform[4], item.transform[5]);
      const end = x + item.width * unit;
      if (Math.abs(y - repair.y) > repair.height * 0.4 || end < left || x > right) continue;
      if (x < left || end > right) {
        crossesEdge = true;
        break;
      }
      indices.push(index);
    }
    // Never pull a different column past the intervening text in the PDF's reading order.
    if (crossesEdge || !indices.length || indices.at(-1) - indices[0] + 1 !== indices.length) continue;

    const first = indices[0];
    const fontName = content.styles[repair.fontName] ? repair.fontName : content.items[first].fontName;
    for (const index of indices) replaced.add(index);
    const parts = repair.parts ?? [repair];
    insertions.set(first, parts.map((part, index) => {
      const [x, y] = viewport.convertToPdfPoint(part.x, repair.y);
      const [alongX, alongY] = viewport.convertToPdfPoint(part.x + repair.height, repair.y);
      const [upX, upY] = viewport.convertToPdfPoint(part.x, repair.y - repair.height);
      return {str: part.str, dir: repair.dir, width: part.width / unit, height: repair.height / unit,
        transform: [alongX - x, alongY - y, upX - x, upY - y, x, y],
        glyphBounds: part.glyphBounds, fontName, hasEOL: index === parts.length - 1};
    }));
  }
  if (!insertions.size) return content;

  // Place repairs in the original item order, including across columns.
  const repaired = [];
  for (const [index, item] of content.items.entries()) {
    if (insertions.has(index)) repaired.push(...insertions.get(index));
    else if (!replaced.has(index)) repaired.push(item);
  }
  return {...content, items: repaired};
}
