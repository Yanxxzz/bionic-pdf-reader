// Word-length and common-word rules inspired by yitong2333/Bionic-Reading.
// See THIRD_PARTY_NOTICES.txt for the original MIT attribution.
import { wordSpans, prefixLength } from './words.mjs';
export { prefixLength, wordSpans } from './words.mjs';

export function glyphMask(glyphs, current, settings) {
  const font = current.font;
  const matrix = current.textMatrix;
  const height = current.fontSize * Math.hypot(matrix[2], matrix[3]);
  if (!settings.enabled || font.bold || font.black || font.italic || font.vertical ||
      current.textRenderingMode !== 0 || current.patternFill ||
      Math.abs(matrix[1]) > 1e-5 || Math.abs(matrix[2]) > 1e-5 ||
      height < 6.8 || height > 25) return null;
  const units = glyphs.map(g => typeof g === 'number' ? '' : g.unicode || '');
  const text = units.join('');
  if (/[=+<>∑∫√±×÷≤≥∞]/u.test(text) || /https?:\/\/|www\.|@|_/i.test(text)) return null;
  const words = wordSpans(text, settings.locale || 'auto');
  if (words.length === 1 && /^[A-Za-z]{1,4}$/.test(words[0].segment) && !/\s/u.test(text)) return null;
  const flags = new Uint8Array(text.length);
  for (const { segment: word, index } of words) {
    if (/^[A-ZА-ЯЁΑ-Ω]{1,5}$/u.test(word)) continue;
    flags.fill(1, index, index + prefixLength(word, settings.rule));
  }
  let position = 0;
  return units.map(unit => {
    const selected = unit.length > 0 && flags.slice(position, position + unit.length).some(Boolean);
    position += unit.length;
    return selected;
  });
}
