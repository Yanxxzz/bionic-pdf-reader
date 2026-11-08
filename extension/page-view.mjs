import {AnnotationMode, TextLayer} from './vendor/pdf.mjs';
import {GlyphCapture, planGlyphs, repairTextContent, textGlyphBounds} from './layout.mjs';
import {destinationView, externalLink} from './navigation.mjs';

const scroller = document.getElementById('page-scroller');
const frame = document.getElementById('page-frame');
const originalCanvas = document.getElementById('pdf-canvas');
const bionicCanvas = document.createElement('canvas');
const textContainer = document.getElementById('text-layer');
const linkContainer = document.getElementById('page-links');
const findMarks = document.getElementById('find-marks');
const layouts = new Map();
let displayedText = null;
let originalView = null;
let activeTask = null;
let revision = 0;
let pending = Promise.resolve();

function fitWidth() {
  return Math.max(240, scroller.clientWidth - (innerWidth <= 760 ? 24 : 56));
}

export function fitWidthChanged() {
  return Math.abs(fitWidth() - parseFloat(frame.style.width || '0')) > 0.5;
}

function frameOrigin() {
  const view = scroller.getBoundingClientRect(), page = frame.getBoundingClientRect();
  return [page.left - view.left - scroller.clientLeft, page.top - view.top - scroller.clientTop];
}

export function readingPosition(zoom) {
  const [x, y] = frameOrigin();
  return {zoom, left: scroller.scrollLeft, top: scroller.scrollTop, scale: displayedText?.viewport.scale,
    point: displayedText?.viewport.convertToPdfPoint(Math.max(0, -x), Math.max(0, -y))};
}

export function resolvePosition({page, dest}, origin) {
  const inset = parseFloat(getComputedStyle(scroller).paddingTop);
  return {number: page.pageNumber,
    ...destinationView(page, dest, origin, fitWidth(), Math.max(1, scroller.clientHeight - 2 * inset))};
}

function restorePosition(viewport, position) {
  const resized = position?.scale && position.scale !== viewport.scale;
  if (position?.point && (position.top === undefined || resized)) {
    const [x, y] = viewport.convertToViewportPoint(...position.point);
    const [left, top] = frameOrigin();
    const margin = parseFloat(getComputedStyle(scroller).paddingTop);
    if (resized) {
      scroller.scrollBy(position.left <= margin ? position.left - scroller.scrollLeft : left + x,
                        position.top <= margin ? position.top - scroller.scrollTop : top + y);
    } else {
      scroller.scrollBy(left + x - margin, top + y - margin);
    }
  } else {
    scroller.scrollTo(position?.left ?? 0, position?.top ?? 0);
  }
}

function invalidate() {
  ++revision;
  activeTask?.cancel();
  return revision;
}

export function resetPageView() {
  invalidate();
  pending = pending.then(() => {
    layouts.clear();
    displayedText = null;
    originalView = null;
    textContainer.replaceChildren();
    linkContainer.replaceChildren();
    findMarks.replaceChildren();
    originalCanvas.width = originalCanvas.height = bionicCanvas.width = bionicCanvas.height = 0;
  });
  return pending;
}

export async function embeddedReadingLayer(pdf) {
  const original = await pdf.getOptionalContentConfig();
  const ids = [...original].filter(([, group]) => group.name === '仿生阅读 · Bionic Reading').map(([id]) => id);
  if (!ids.length) return null;
  const bionic = await pdf.getOptionalContentConfig();
  for (const id of ids) {
    original.setVisibility(id, false, false);
    bionic.setVisibility(id, true, false);
  }
  return {original, bionic};
}

async function drawCanvas(page, target, viewport, transform, reader, layers) {
  target.bionicReader = reader;
  activeTask = page.render({canvas: target, viewport, transform, annotationMode: AnnotationMode.ENABLE,
    optionalContentConfigPromise: layers && Promise.resolve(layers)});
  try { await activeTask.promise; }
  finally { target.bionicReader = null; activeTask = null; }
}

async function pagePlan(page, viewport, {rule, locale, embeddedLayer}, originalPaint) {
  let entry = layouts.get(page);
  if (!entry) {
    const capture = new GlyphCapture(originalPaint?.scale);
    if (originalPaint) {
      await drawCanvas(page, originalCanvas, originalPaint.viewport, originalPaint.transform, capture, embeddedLayer?.original);
    } else {
      const scratch = document.createElement('canvas');
      scratch.width = Math.ceil(viewport.width);
      scratch.height = Math.ceil(viewport.height);
      try { await drawCanvas(page, scratch, viewport, null, capture, embeddedLayer?.original); }
      finally { scratch.width = scratch.height = 0; }
    }
    entry = {capture};
  }
  if (entry.rule !== rule || entry.locale !== locale) {
    entry.plan = planGlyphs(entry.capture, {rule, locale});
    entry.rule = rule;
    entry.locale = locale;
  }
  layouts.delete(page);
  layouts.set(page, entry);
  if (layouts.size > 4) layouts.delete(layouts.keys().next().value);
  return entry.plan;
}

function showPageLinks(annotations, viewport, followDestination) {
  const links = document.createDocumentFragment();
  for (const annotation of annotations) {
    const {subtype, dest, rect, contentsObj} = annotation;
    if (subtype !== 'Link') continue;
    const link = dest ? document.createElement('a') : externalLink(annotation);
    if (!link) continue;
    const [x1, y1, x2, y2] = viewport.convertToViewportRectangle(rect);
    if (dest) {
      link.href = '#page-frame';
      link.setAttribute('aria-label', contentsObj?.str || '跳转到书内链接目标');
      link.addEventListener('click', event => { event.preventDefault(); followDestination(dest); });
    } else {
      link.setAttribute('aria-label', `${contentsObj?.str || link.host}（在新标签页打开）`);
    }
    Object.assign(link.style, {
      left: `${100 * Math.min(x1, x2) / viewport.width}%`, top: `${100 * Math.min(y1, y2) / viewport.height}%`,
      width: `${100 * Math.abs(x2 - x1) / viewport.width}%`, height: `${100 * Math.abs(y2 - y1) / viewport.height}%`,
    });
    links.append(link);
  }
  linkContainer.replaceChildren(links);
}

async function drawPage(request, pdf, number, settings) {
  if (request !== revision) return;
  const page = await pdf.getPage(number);
  if (request !== revision) return;
  const base = page.getViewport({scale: 1});
  const scale = settings.zoom === 'fit' ? fitWidth() / base.width : Number(settings.zoom);
  const viewport = page.getViewport({scale});
  const outputScale = Math.min(devicePixelRatio || 1, 2);
  const samePage = displayedText?.page === page;
  const position = settings.position ?? (samePage ? readingPosition(settings.zoom) : null);
  const canvas = settings.enabled ? bionicCanvas : originalCanvas;
  const previous = frame.querySelector('canvas');
  if (previous !== canvas) {
    previous.removeAttribute('id');
    canvas.id = 'pdf-canvas';
    previous.replaceWith(canvas);
  }
  // Keep the actual original pixels for this viewport, including embedded fonts and images.
  if (originalView && (originalView.page !== page || originalView.scale !== scale || originalView.outputScale !== outputScale)) {
    originalView = null;
    originalCanvas.width = originalCanvas.height = 0;
  }
  const reuseOriginal = !settings.enabled && originalView !== null;
  if (!reuseOriginal) {
    canvas.width = Math.round(viewport.width * outputScale);
    canvas.height = Math.round(viewport.height * outputScale);
  }
  canvas.style.width = frame.style.width = `${viewport.width}px`;
  canvas.style.height = frame.style.height = `${viewport.height}px`;
  frame.style.setProperty('--total-scale-factor', String(scale));
  frame.style.setProperty('--scale-factor', String(scale));
  if (!samePage) {
    displayedText = null;
    textContainer.replaceChildren();
    linkContainer.replaceChildren();
  }

  const transform = outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0];
  const originalPaint = !settings.enabled && !layouts.has(page) ? {viewport, transform, scale: scale * outputScale} : null;
  const {masks, repairs} = await pagePlan(page, base, settings, originalPaint);
  if (request !== revision) return;
  let run = 0;
  const emphasis = {
    enabled: settings.enabled, strength: settings.strength, stroked: 0,
    mask(glyphs) {
      const mask = masks[run++];
      if (mask?.length !== glyphs.length) throw new Error('PDF glyph capture and rendering are out of sync');
      return mask;
    },
  };
  if (!originalPaint && !reuseOriginal) {
    const live = settings.enabled && !settings.embeddedLayer;
    const layers = settings.enabled ? settings.embeddedLayer?.bionic : settings.embeddedLayer?.original;
    await drawCanvas(page, canvas, viewport, transform, live ? emphasis : null, layers);
  }
  if (request !== revision) return;
  if (!settings.enabled) originalView = {page, scale, outputScale};
  if (displayedText) {
    displayedText.layer.update({viewport});
  } else {
    const [text, annotations] = await Promise.all([page.getTextContent(), page.getAnnotations()]);
    if (request !== revision) return;
    const content = repairTextContent(text, repairs, base);
    const layer = new TextLayer({textContentSource: content, container: textContainer, viewport});
    activeTask = layer;
    try { await layer.render(); }
    finally { activeTask = null; }
    if (request !== revision) return;
    showPageLinks(annotations, base, settings.followDestination);
    const items = content.items.filter(item => typeof item.str === 'string');
    displayedText = {page, layer, items, hasText: items.some(item => /\p{L}/u.test(item.str))};
  }
  displayedText.viewport = viewport;
  canvas.dataset.boldGlyphs = String(emphasis.stroked);
  frame.dataset.renderedPage = String(number);
  frame.dataset.renderRevision = String(request);
  frame.dataset.mode = settings.enabled ? 'bionic' : 'original';
  frame.dataset.renderState = 'ready';
  restorePosition(viewport, position);
  return {hasText: displayedText.hasText, stroked: emphasis.stroked, items: displayedText.items};
}

export function renderPage(pdf, number, settings) {
  const request = invalidate();
  frame.dataset.renderState = 'rendering';
  delete frame.dataset.renderedPage;
  delete frame.dataset.mode;

  const result = pending.then(() => drawPage(request, pdf, number, settings)).catch(error => {
    if (request !== revision || error.name === 'RenderingCancelledException' || error.name === 'AbortException') return;
    frame.dataset.renderState = 'error';
    throw error;
  });
  // The caller receives its error. The next request can still use the same canvas.
  pending = result.catch(() => {});
  return result;
}

function* matchRanges({start, end}) {
  const {items, layer, page} = displayedText;
  const records = layouts.get(page).capture.records;
  const base = page.getViewport({scale: 1});
  let cursor = 0;
  for (const [i, item] of items.entries()) {
    const next = cursor + item.str.length;
    const node = layer.textDivs[i]?.firstChild;
    if (next > start && cursor < end && node && item.str.length) {
      const first = Math.max(0, start - cursor), last = Math.min(item.str.length, end - cursor);
      const range = document.createRange();
      range.setStart(node, first);
      range.setEnd(node, last);
      item.glyphBounds ??= textGlyphBounds(item, records, base) ?? [];
      const left = item.glyphBounds[first], right = item.glyphBounds[last - 1];
      yield {range, bounds: left && right ? [left[0], right[1]] : null};
    }
    cursor = next + (item.hasEOL ? 1 : 0);
    if (cursor >= end) break;
  }
}

export function markMatch(match, reveal = false) {
  findMarks.replaceChildren();
  if (!match || displayedText?.page.pageNumber !== match.page) return false;
  const origin = frame.getBoundingClientRect();
  const scale = displayedText.viewport.scale;
  for (const {range, bounds} of matchRanges(match)) {
    for (const rect of range.getClientRects()) {
      if (!rect.width || !rect.height) continue;
      const mark = document.createElement('i');
      const left = bounds ? bounds[0] * scale : rect.left - origin.left;
      const width = bounds ? (bounds[1] - bounds[0]) * scale : rect.width;
      Object.assign(mark.style, {left: `${left}px`, top: `${rect.top - origin.top}px`,
        width: `${width}px`, height: `${rect.height}px`});
      findMarks.append(mark);
    }
  }
  if (reveal) findMarks.firstChild?.scrollIntoView({block: 'center', inline: 'nearest'});
  return !!findMarks.firstChild;
}
