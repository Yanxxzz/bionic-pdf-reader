import {segmentFlags} from './words.mjs';

const rtl = /[\p{Script=Arabic}\p{Script=Hebrew}]/u;
const letter = /[\p{L}\p{N}]/u;
const styledFont = /bold|italic|oblique|black|heavy|demi|symbol|dingbat/i;

export class GlyphCapture {
  constructor() {
    this.enabled = true;
    this.runs = [];
    this.records = [];
    this.scopes = [];
    this.serial = 0;
  }

  beginMarkedContent(text) {
    this.scopes.push(typeof text === 'string' ? {id: this.serial++, text} : null);
  }

  endMarkedContent() {
    this.scopes.pop();
  }

  mask(glyphs, current, matrix, visible = true) {
    const run = this.runs.length;
    this.runs.push(glyphs.length);
    if (!visible) return;

    const actual = this.scopes.find(scope => scope !== null) ?? null;
    const {font, fontSize, fontSizeScale} = current;
    const advance = fontSize * current.fontMatrix[0];
    const size = fontSize * Math.hypot(current.textMatrix[2], current.textMatrix[3]);
    const eligible = !font.bold && !font.black && !font.italic && !font.vertical && !styledFont.test(font.name || '')
      && current.textRenderingMode === 0 && !current.patternFill && size >= 6.8 && size <= 25
      && Math.abs(matrix.b) < 1e-5 && Math.abs(matrix.c) < 1e-5;

    let x = 0;
    for (const [index, glyph] of glyphs.entries()) {
      if (typeof glyph === 'number') {
        x -= glyph * fontSize / 1000;
        continue;
      }
      const spacing = current.charSpacing + (glyph.isSpace ? current.wordSpacing : 0);
      const width = glyph.width * advance + spacing * current.fontDirection;
      const left = matrix.a * x / fontSizeScale + matrix.e;
      const right = matrix.a * (x + width) / fontSizeScale + matrix.e;
      this.records.push({
        run, index, text: glyph.unicode || '', font: font.loadedName || font.name, actual, eligible,
        x: Math.min(left, right), w: Math.abs(right - left),
        y: matrix.b * x / fontSizeScale + matrix.f, h: Math.abs(matrix.d * fontSize / fontSizeScale),
      });
      x += width;
    }
  }
}

function sameLine(first, other) {
  return Math.abs(first.y - other.y) <= Math.max(first.h, other.h) * 0.32
    && Math.abs(first.h - other.h) < Math.max(1, other.h * 0.15);
}

function splitColumns(line) {
  const columns = [];
  let edge = -Infinity;
  for (const item of [...line].sort((a, b) => a.x - b.x)) {
    if (!columns.length || item.x - edge > 2 * item.h) columns.push([]);
    columns.at(-1).push(item);
    edge = Math.max(edge, item.x + item.w);
  }
  return columns;
}

function* glyphAtoms(records) {
  const clusters = new Map();
  for (const record of records) {
    const key = record.actual?.id ?? record;
    if (!clusters.has(key)) clusters.set(key, []);
    clusters.get(key).push(record);
  }

  for (const members of clusters.values()) {
    const base = members.reduce((first, other) => first.w >= other.w ? first : other);
    const text = base.actual?.text ?? base.text;
    if (base.actual && (/[\r\n\u0085\u2028\u2029]/u.test(text)
      || !members.every(r => sameLine(base, r)) || splitColumns(members).length > 1)) {
      // Keep the physical positions so each affected line keeps its own source text.
      for (const r of members) yield {...r, text: '\0', records: [r], actual: false, eligible: false};
      continue;
    }
    let left = base.x, right = base.x + base.w;
    for (const r of members) {
      left = Math.min(left, r.x);
      right = Math.max(right, r.x + r.w);
    }
    yield {
      text, records: members, actual: Boolean(base.actual), font: base.font,
      x: left, w: right - left, y: base.y, h: base.h,
      eligible: members.every(r => r.eligible) && !/\s/u.test(text.trim()),
    };
  }
}

function* visualSegments(records) {
  const fonts = new Map();
  for (const atom of glyphAtoms(records)) {
    if (!fonts.has(atom.font)) fonts.set(atom.font, []);
    fonts.get(atom.font).push(atom);
  }
  for (const atoms of fonts.values()) {
    const lines = [];
    for (const atom of atoms.sort((a, b) => a.y - b.y || a.x - b.x)) {
      const line = lines.slice(-3).reverse().find(line => sameLine(line[0], atom));
      if (line) line.push(atom);
      else lines.push([atom]);
    }
    for (const line of lines) yield* splitColumns(line);
  }
}

function logicalText(atoms){
  const count=atoms.reduce((n,a)=>n+(rtl.test(a.text)?a.text.length:0),0);
  const total=atoms.reduce((n,a)=>n+([...a.text].filter(c=>letter.test(c)).length),0);
  const direction=count>total/2?'rtl':'ltr';
  const ordered=direction==='rtl'?[...atoms].reverse():[...atoms];
  const strong=a=>rtl.test(a.text)?'rtl':letter.test(a.text)?'ltr':null;
  let output='',pending=[];
  const flush=()=>{output+=pending.reverse().map(a=>a.text).join('');pending=[];};
  ordered.forEach((atom,i)=>{
    let d=strong(atom);
    if(!d){const left=[...ordered.slice(0,i)].reverse().find(a=>strong(a)),right=ordered.slice(i+1).find(a=>strong(a));d=left&&right&&strong(left)===strong(right)?strong(left):direction;}
    if(d!==direction)pending.push(atom);else{flush();output+=atom.text;}
  });flush();
  return {text:output,dir:direction};
}

export function planGlyphs(capture, settings) {
  const masks = capture.runs.map(length => Array(length).fill(false));
  const repairs = [];
  for (const segment of visualSegments(capture.records)) {
    const ordered = [];
    let edge = -Infinity;
    for (const atom of segment) {
      if (ordered.length && atom.x - edge > atom.h * 0.18 && !/\s$/u.test(ordered.at(-1).text)) {
        ordered.push({text: ' '});
      }
      ordered.push(atom);
      edge = Math.max(edge, atom.x + atom.w);
    }

    const text = ordered.map(atom => atom.text).join('');
    if (text.includes('\0')) continue;
    const flags = segmentFlags(text, settings);
    let start = 0;
    for (const atom of ordered) {
      const end = start + atom.text.length;
      if (atom.eligible && flags.subarray(start, end).includes(1)) {
        for (const r of atom.records) masks[r.run][r.index] = true;
      }
      start = end;
    }
    if (segment.some(a => a.actual) && segment.every(a => a.records.every(r => r.h > 0))) {
      const logical = rtl.test(text) ? logicalText(ordered) : {text, dir: 'ltr'};
      const first = segment[0];
      repairs.push({str: logical.text, dir: logical.dir, x: first.x, y: first.y,
        width: edge - first.x, height: first.h, fontName: first.font});
    }
  }
  return {masks, repairs};
}

export function repairTextContent(content, repairs, viewport) {
  if (!repairs.length) return content;
  const replaced = new Set(), insertions = new Map();
  for (const repair of repairs) {
    const left = repair.x - repair.height * 0.2;
    const right = repair.x + repair.width + repair.height * 0.2;
    const indices = [];
    let crossesEdge = false;
    for (const [index, item] of content.items.entries()) {
      if (typeof item.str !== 'string' || !item.transform) continue;
      const [x, y] = viewport.convertToViewportPoint(item.transform[4], item.transform[5]);
      if (Math.abs(y - repair.y) > repair.height * 0.4 || x + item.width < left || x > right) continue;
      if (x < left || x + item.width > right) {
        crossesEdge = true;
        break;
      }
      indices.push(index);
    }
    if (crossesEdge || !indices.length) continue;

    const first = indices[0];
    const fontName = content.styles[repair.fontName] ? repair.fontName : content.items[first].fontName;
    const [x, y] = viewport.convertToPdfPoint(repair.x, repair.y);
    for (const index of indices) replaced.add(index);
    insertions.set(first, {
      str: repair.str, dir: repair.dir, width: repair.width, height: repair.height,
      transform: [repair.height, 0, 0, repair.height, x, y], fontName, hasEOL: true,
    });
  }
  if (!insertions.size) return content;

  // Place repairs in the original item order, including across columns.
  const items = [];
  for (const [index, item] of content.items.entries()) {
    if (insertions.has(index)) items.push(insertions.get(index));
    else if (!replaced.has(index)) items.push(item);
  }
  return {...content, items};
}
