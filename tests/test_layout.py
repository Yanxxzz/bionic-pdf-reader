import json
from pathlib import Path
import pytest
from bionic_pdf.layout import select_glyphs
from bionic_pdf.pdf_text import GraphicsState

CASES=json.loads((Path(__file__).with_name('layout-cases.json')).read_text(encoding='utf-8'))

@pytest.mark.parametrize('case',CASES,ids=lambda c:c['name'])
def test_layout_prefixes(case):
    size = case.get('fontSize', 15)
    eligible = GraphicsState(font_size=size).can_emphasize()
    records = [{
        'text': text, 'x': case['x'][i] if 'x' in case else i*10,
        'y': case['y'][i] if 'y' in case else 100,
        'w': 10, 'h': size, 'font': 'normal', 'eligible': eligible,
        'actual': case['actual'][i] if 'actual' in case else None,
    } for i, text in enumerate(case['text'])]
    assert sorted(select_glyphs(records, case.get('rule', 'half'))) == case['selected']
