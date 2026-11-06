"""Unicode word prefixes. Work on grapheme clusters, never individual marks."""
import logging
import math
import regex

COMMON = set('the and in on at by with about against between into through during before after above below to from up down over under again further then once here there when where why how all any both each few more most other some'.split())
TOKENS = regex.compile(r'[\p{Han}\p{Hiragana}\p{Katakana}ー]+|[\p{L}\p{M}]+(?:[’\x27][\p{L}\p{M}]+)*')

def word_spans(text, locale='auto'):
    for match in TOKENS.finditer(text):
        token = match.group()
        if regex.search(r'[\p{Hiragana}\p{Katakana}]', token) or locale == 'ja' and regex.search(r'\p{Han}', token):
            from tinysegmenter import TinySegmenter
            pieces = TinySegmenter().tokenize(token)
        elif regex.search(r'\p{Han}', token):
            import jieba
            jieba.setLogLevel(logging.ERROR)
            pieces = jieba.lcut(token, HMM=False)
        else:
            pieces = [token]
        offset = match.start()
        for piece in pieces:
            yield offset, piece
            offset += len(piece)

def prefix_length(word, rule='half'):
    clusters = regex.findall(r'\X', word)
    if len(clusters) < 2: return 0
    if rule == 'reference' and regex.fullmatch(r'[A-Za-z]+', word):
        count = 1 if word.lower() in COMMON else 1 if len(clusters) <= 2 else 2 if len(clusters) <= 5 else 4
    else: count = math.ceil(len(clusters) / 2)
    return len(''.join(clusters[:count]))

def text_flags(text, rule='half', locale='auto'):
    flags = bytearray(len(text))
    for start, word in word_spans(text, locale):
        if word.isupper() and len(word) <= 5: continue
        count = prefix_length(word, rule)
        flags[start:start + count] = b'\x01' * count
    return flags
