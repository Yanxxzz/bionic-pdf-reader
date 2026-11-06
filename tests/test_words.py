import json
from pathlib import Path
import pytest
from bionic_pdf.words import text_flags, prefix_length, word_spans

SAMPLES=json.loads((Path(__file__).resolve().parents[1]/'examples/languages.json').read_text(encoding='utf-8'))

@pytest.mark.parametrize('sample',SAMPLES,ids=lambda x:x['code'])
def test_language_prefixes(sample):
    text=sample['text']
    flags=text_flags(text,locale=sample['code'])
    assert len(flags)==len(text)
    assert any(flags) and not all(flags)
    assert len(list(word_spans(text,sample['code'])))>1

def test_graphemes_and_reference():
    assert prefix_length('e\u0301cole')==4
    assert prefix_length('Reading','reference')==4
    assert prefix_length('the','reference')==1
    assert not any(text_flags('PDF X A'))

def test_support_scope_matches_language_controls():
    from bionic_pdf.words import LANGUAGES
    assert list(LANGUAGES)==[s['code'] for s in SAMPLES]
    assert not any(text_flags('中文 日本語 한국어 العربية עברית हिन्दी'))
