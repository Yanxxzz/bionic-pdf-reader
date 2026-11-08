// Resolve PDF destinations against the target page's rotated, cropped viewport.
export function destinationView(page, dest, current, width, height) {
  const base = page.getViewport({scale: 1});
  const [left, , , top] = base.viewBox;
  const [, {name}, x, y, value, upper] = dest;
  const visible = current.point || [left, top];
  let zoom = current.zoom;
  let point = [left, top];
  switch (name) {
    case 'XYZ':
      point = [x ?? visible[0], y ?? visible[1]];
      if (value > 0) zoom = value;
      break;
    case 'FitH': case 'FitBH':
      zoom = 'fit';
      point = [left, x ?? visible[1]];
      break;
    case 'FitV': case 'FitBV':
      zoom = height / base.height;
      point = [x ?? visible[0], top];
      break;
    case 'FitR': {
      const [x1, y1, x2, y2] = base.convertToViewportRectangle([x, y, value, upper]);
      if (x1 === x2 || y1 === y2) break;
      zoom = Math.min(width / Math.abs(x2 - x1), height / Math.abs(y2 - y1));
      point = base.convertToPdfPoint(Math.min(x1, x2), Math.min(y1, y2));
      break;
    }
    case 'Fit': case 'FitB':
      zoom = Math.min(width / base.width, height / base.height);
      point = null;
      break;
    default:
      point = null;
  }
  if (typeof zoom === 'number') zoom = String(Math.min(8, Math.max(.1, zoom)));
  return {zoom, point};
}

export function webLinkURL({url, unsafeUrl}) {
  const doi = /^(?:doi:\s*)?(10\.\d{4,9}\/[^\s]+)$/i.exec((unsafeUrl || url || '').trim());
  if (doi) {
    const target = new URL('https://doi.org');
    target.pathname = '/' + doi[1];
    return target.href;
  }
  try {
    const target = new URL(url);
    return ['http:', 'https:'].includes(target.protocol) ? target.href : null;
  } catch { return null; }
}

export function externalLink(item) {
  const href = webLinkURL(item);
  if (!href) return null;
  const link = document.createElement('a');
  link.href = href;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.title = href;
  return link;
}

export function pageInRange(number, total, fallback) {
  return Number.isInteger(number) ? Math.min(total, Math.max(1, number)) : fallback;
}

export function savedPosition(raw, total, defaultZoom) {
  let saved;
  try { saved = JSON.parse(raw); } catch {}
  const fallback = {number: 1, zoom: defaultZoom};
  if (typeof saved === 'number') return {...fallback, number: pageInRange(saved, total, 1)};
  if (!saved || !Number.isInteger(saved.number)) return fallback;
  const number = pageInRange(saved.number, total, 1);
  const validZoom = typeof saved.zoom === 'string' && (saved.zoom === 'fit' ||
    (Number(saved.zoom) >= .1 && Number(saved.zoom) <= 8));
  if (!validZoom) return {...fallback, number};
  const result = {number, zoom: saved.zoom};
  if ([saved.left, saved.top].every(v => Number.isFinite(v) && v >= 0)) {
    Object.assign(result, {left: saved.left, top: saved.top});
    if (Number.isFinite(saved.scale) && saved.scale > 0 &&
        Array.isArray(saved.point) && saved.point.length === 2 && saved.point.every(Number.isFinite)) {
      Object.assign(result, {scale: saved.scale, point: saved.point});
    }
  }
  return result;
}
