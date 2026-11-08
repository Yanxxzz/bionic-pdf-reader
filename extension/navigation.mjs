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
