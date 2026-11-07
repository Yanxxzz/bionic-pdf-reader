// English reference rule: yitong2333/Bionic-Reading (MIT), see notices.
const commonWords = new Set('the and in on at by with about against between into through during before after above below to from up down over under again further then once here there when where why how all any both each few more most other some'.split(' '));
const segmenters = new Map();
const supportedLetter = /[\p{Script=Latin}\p{Script=Cyrillic}\p{Script=Greek}]/u;
const unsupportedCharacter = /[^\p{Script=Latin}\p{Script=Cyrillic}\p{Script=Greek}\p{M}’'\d]/u;
function segmenter(locale, granularity) {
  const key = `${locale}:${granularity}`;
  if (!segmenters.has(key)) segmenters.set(key, new Intl.Segmenter(locale === 'auto' ? undefined : locale, { granularity }));
  return segmenters.get(key);
}
export function wordSpans(text, locale = 'auto') {
  return [...segmenter(locale, 'word').segment(text)].filter(({isWordLike, segment}) =>
    isWordLike && supportedLetter.test(segment) && !unsupportedCharacter.test(segment));
}
export function prefixLength(word, rule = 'reference', locale = 'auto') {
  if (rule === 'reference' && (locale === 'auto' || locale.startsWith('en')) && /^[A-Za-z]+$/.test(word)) {
    if (word.length < 2) return 0;
    if (word.length === 2 || commonWords.has(word.toLowerCase())) return 1;
    return word.length <= 5 ? 2 : 4;
  }
  const graphemes = [...segmenter('auto', 'grapheme').segment(word)];
  if (graphemes.length < 2) return 0;
  return graphemes[Math.ceil(graphemes.length / 2)].index;
}

export function segmentFlags(text, {rule = 'reference', locale = 'auto'} = {}) {
  const flags = new Uint8Array(text.length);
  if (/[\0=+<>∑∫√±×÷≤≥∞@_]|https?:\/\/|www\./iu.test(text) || /^[A-Za-z]{1,4}$/.test(text)) return flags;
  for (const {segment, index} of wordSpans(text, locale)) {
    const shortUppercase = [...segment].length <= 5
      && segment === segment.toUpperCase() && segment !== segment.toLowerCase();
    if (shortUppercase) continue;
    flags.fill(1, index, index + prefixLength(segment, rule, locale));
  }
  return flags;
}
