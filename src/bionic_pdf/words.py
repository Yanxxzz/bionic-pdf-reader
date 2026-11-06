"""Unicode word prefixes. Work on grapheme clusters, never individual marks."""
import math
import regex

LANGUAGES = {'en':'英语','fr':'法语','de':'德语','es':'西班牙语','pt':'葡萄牙语','it':'意大利语','nl':'荷兰语','pl':'波兰语','tr':'土耳其语','vi':'越南语','ru':'俄语','uk':'乌克兰语','el':'希腊语'}
COMMON = set('the and in on at by with about against between into through during before after above below to from up down over under again further then once here there when where why how all any both each few more most other some'.split())
TOKENS = regex.compile(r'[\p{Latin}\p{Cyrillic}\p{Greek}][\p{Latin}\p{Cyrillic}\p{Greek}\p{M}]*(?:[’\x27][\p{Latin}\p{Cyrillic}\p{Greek}\p{M}]+)*')

def word_spans(text, locale='auto'):
    for match in TOKENS.finditer(text):
        yield match.start(), match.group()

def prefix_length(word, rule='half'):
    clusters = regex.findall(r'\X', word)
    if len(clusters) < 2: return 0
    if rule == 'reference' and regex.fullmatch(r'[A-Za-z]+', word):
        count = 1 if word.lower() in COMMON else 1 if len(clusters) <= 2 else 2 if len(clusters) <= 5 else 4
    else: count = math.ceil(len(clusters) / 2)
    return len(''.join(clusters[:count]))

def text_flags(text, rule='half', locale='auto', visual=False):
    flags = bytearray(len(text))
    for start, word in word_spans(text, locale):
        if word.isupper() and len(word) <= 5: continue
        if visual and regex.search(r'[\p{Arabic}\p{Hebrew}]',word):
            clusters=regex.findall(r'\X',word)
            count=len(''.join(clusters[-math.ceil(len(clusters)/2):])) if len(clusters)>1 else 0
            position=start+len(word)-count
        else:
            count=prefix_length(word,rule);position=start
        flags[position:position + count] = b'\x01' * count
    return flags
