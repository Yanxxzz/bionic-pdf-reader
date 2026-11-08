"""Unicode word prefixes. Work on grapheme clusters, never individual marks."""
import regex

LANGUAGES = {'en':'英语','fr':'法语','de':'德语','es':'西班牙语','pt':'葡萄牙语','it':'意大利语','nl':'荷兰语','pl':'波兰语','tr':'土耳其语','vi':'越南语','ru':'俄语','uk':'乌克兰语','el':'希腊语'}
COMMON = set('the and in on at by with about against between into through during before after above below to from up down over under again further then once here there when where why how all any both each few more most other some'.split())
TOKENS = regex.compile(r'[\p{Latin}\p{Cyrillic}\p{Greek}][\p{Latin}\p{Cyrillic}\p{Greek}\p{M}]*(?:[’\x27][\p{Latin}\p{Cyrillic}\p{Greek}\p{M}]+)*')
INLINE_TOKENS = regex.compile(r'(?:https?://|www\.)[^\s<>()]+|[\p{L}\p{M}\p{N}._%+-]+@[\p{L}\p{M}\p{N}.-]+|[\p{L}\p{M}\p{N}_]+|\S', regex.I)
OPERATORS = frozenset('=+<>∑∫√±×÷≤≥∞')

def word_spans(text):
    for match in TOKENS.finditer(text):
        yield match.start(), match.group()

def prefix_length(word, rule='half'):
    if rule == 'reference' and word.isascii() and word.isalpha():
        if len(word) < 2:
            return 0
        if len(word) == 2 or word.lower() in COMMON:
            return 1
        return 2 if len(word) <= 5 else 4
    starts = [match.start() for match in regex.finditer(r'\X', word)]
    if len(starts) < 2:
        return 0
    return starts[(len(starts) + 1) // 2]

def text_flags(text, rule='half'):
    flags = bytearray(len(text))
    for start, word in word_spans(text):
        if word.isupper() and len(word) <= 5:
            continue
        count = prefix_length(word, rule)
        flags[start:start + count] = b'\x01' * count
    return flags


def segment_flags(text, rule='half'):
    if '\0' in text or regex.fullmatch(r'[A-Za-z]{1,4}', text):
        return bytearray(len(text))
    flags = text_flags(text, rule)
    if not regex.search(r'[=+<>∑∫√±×÷≤≥∞@_]|https?://|www\.', text, regex.I):
        return flags
    tokens = list(INLINE_TOKENS.finditer(text))
    for i, match in enumerate(tokens):
        token = match.group()
        if ('@' in token or '_' in token or token.lower().startswith(('https://', 'http://', 'www.'))
                or (i > 0 and tokens[i - 1].group() in OPERATORS)
                or (i + 1 < len(tokens) and tokens[i + 1].group() in OPERATORS)):
            flags[match.start():match.end()] = bytes(len(token))
    return flags
