import json
from pathlib import Path
import pytest
from bionic_pdf.layout import select_glyphs

CASES=json.loads((Path(__file__).with_name('layout-cases.json')).read_text(encoding='utf-8'))

@pytest.mark.parametrize('case',CASES,ids=lambda c:c['name'])
def test_layout_prefixes(case):
    records=[{'text':text,'x':i*10,'y':100,'w':10,'h':15,'font':'normal','eligible':True,'actual':case.get('actual',[None]*len(case['text']))[i]} for i,text in enumerate(case['text'])]
    assert sorted(select_glyphs(records,case['locale']))==case['selected']
