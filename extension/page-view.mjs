import {AnnotationMode, TextLayer} from './vendor/pdf.mjs';
import {GlyphCapture, planGlyphs, repairTextContent} from './layout.mjs';

const scroller = document.getElementById('page-scroller');
const frame = document.getElementById('page-frame');
const canvas = document.getElementById('pdf-canvas');
const textContainer = document.getElementById('text-layer');
const layouts = new Map();
let displayedText = null;
let activeTask = null;
let revision = 0;
let pending = Promise.resolve();

function fitWidth() {
  return Math.max(240, scroller.clientWidth - (innerWidth <= 760 ? 24 : 56));
}

export function fitWidthChanged() {
  return Math.abs(fitWidth() - parseFloat(canvas.style.width || '0')) > 0.5;
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
    textContainer.replaceChildren();
    canvas.width = canvas.height = 0;
  });
  return pending;
}

async function drawCanvas(page, target, viewport, transform) {
  activeTask = page.render({canvas: target, viewport, transform, annotationMode: AnnotationMode.ENABLE});
  try { await activeTask.promise; }
  finally { activeTask = null; }
}

async function pagePlan(page, viewport, {rule, locale}) {
  let entry = layouts.get(page);
  if (!entry) {
    const capture = new GlyphCapture();
    const scratch = document.createElement('canvas');
    scratch.width = Math.ceil(viewport.width);
    scratch.height = Math.ceil(viewport.height);
    scratch.bionicReader = capture;
    try { await drawCanvas(page, scratch, viewport); }
    finally { scratch.width = scratch.height = 0; }
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

async function drawPage(request, pdf, number, zoom, settings, resetScroll) {
  if (request !== revision) return;
  const page = await pdf.getPage(number);
  if (request !== revision) return;
  const base = page.getViewport({scale: 1});
  const scale = zoom === 'fit' ? fitWidth() / base.width : Number(zoom);
  const viewport = page.getViewport({scale});
  const outputScale = Math.min(devicePixelRatio || 1, 2);
  const samePage = displayedText?.page === page;
  const top = resetScroll || !samePage ? 0 : scroller.scrollTop;
  canvas.width = Math.round(viewport.width * outputScale);
  canvas.height = Math.round(viewport.height * outputScale);
  canvas.style.width = frame.style.width = `${viewport.width}px`;
  canvas.style.height = frame.style.height = `${viewport.height}px`;
  frame.style.setProperty('--total-scale-factor', String(scale));
  frame.style.setProperty('--scale-factor', String(scale));
  if (!samePage) {
    displayedText = null;
    textContainer.replaceChildren();
  }

  const {masks, repairs} = await pagePlan(page, base, settings);
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
  canvas.bionicReader = emphasis;
  const transform = outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0];
  await drawCanvas(page, canvas, viewport, transform);
  if (request !== revision) return;
  if (displayedText) {
    displayedText.layer.update({viewport});
  } else {
    const content = repairTextContent(await page.getTextContent(), repairs, base);
    if (request !== revision) return;
    const layer = new TextLayer({textContentSource: content, container: textContainer, viewport});
    activeTask = layer;
    try { await layer.render(); }
    finally { activeTask = null; }
    if (request !== revision) return;
    displayedText = {page, layer, hasText: content.items.some(item => /\p{L}/u.test(item.str || ''))};
  }
  canvas.dataset.boldGlyphs = String(emphasis.stroked);
  frame.dataset.renderedPage = String(number);
  frame.dataset.renderRevision = String(request);
  frame.dataset.mode = settings.enabled ? 'bionic' : 'original';
  frame.dataset.renderState = 'ready';
  scroller.scrollTop = top;
  return {hasText: displayedText.hasText, stroked: emphasis.stroked};
}

export function renderPage(pdf, number, zoom, settings, resetScroll) {
  const request = invalidate();
  frame.dataset.renderState = 'rendering';
  delete frame.dataset.renderedPage;
  delete frame.dataset.mode;

  const result = pending.then(() => drawPage(request, pdf, number, zoom, settings, resetScroll)).catch(error => {
    if (request !== revision || error.name === 'RenderingCancelledException' || error.name === 'AbortException') return;
    frame.dataset.renderState = 'error';
    throw error;
  });
  // The caller receives its error. The next request can still use the same canvas.
  pending = result.catch(() => {});
  return result;
}
