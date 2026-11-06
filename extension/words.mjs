// English reference rule: yitong2333/Bionic-Reading (MIT), see notices.
const commonWords = new Set('the and in on at by with about against between into through during before after above below to from up down over under again further then once here there when where why how all any both each few more most other some'.split(' '));
const segmenters = new Map();
function segmenter(locale, granularity) {
  const key = `${locale}:${granularity}`;
  if (!segmenters.has(key)) segmenters.set(key, new Intl.Segmenter(locale === 'auto' ? undefined : locale, { granularity }));
  return segmenters.get(key);
}
export function wordSpans(text, locale = 'auto') {
  return [...segmenter(locale, 'word').segment(text)].filter(s => s.isWordLike && /[\p{Script=Latin}\p{Script=Cyrillic}\p{Script=Greek}]/u.test(s.segment) && !/[^\p{Script=Latin}\p{Script=Cyrillic}\p{Script=Greek}\p{M}’'\d]/u.test(s.segment));
}
export function prefixLength(word, rule = 'reference', locale = 'auto') {
  const units = [...segmenter('auto', 'grapheme').segment(word)].map(s => s.segment);
  if (units.length < 2) return 0;
  let count = Math.ceil(units.length / 2);
  if (rule === 'reference' && (locale === 'auto' || locale.startsWith('en')) && /^[A-Za-z]+$/.test(word)) count = commonWords.has(word.toLowerCase()) ? 1 : units.length <= 2 ? 1 : units.length <= 5 ? 2 : 4;
  return units.slice(0, count).join('').length;
}
