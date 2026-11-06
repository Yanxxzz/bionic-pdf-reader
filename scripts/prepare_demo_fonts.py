"""Rebuild small OFL demo font subsets from Google's Noto font sources."""
from pathlib import Path
import json
import urllib.request
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools import subset

ROOT = Path(__file__).resolve().parents[1]
FONTS = {
    'Latin': ('notosans', 'NotoSans[wdth,wght].ttf'),
    'CJK': ('notosanssc', 'NotoSansSC[wght].ttf'),
    'Korean': ('notosanskr', 'NotoSansKR[wght].ttf'),
    'Arabic': ('notosansarabic', 'NotoSansArabic[wdth,wght].ttf'),
    'Hebrew': ('notosanshebrew', 'NotoSansHebrew[wdth,wght].ttf'),
    'Indic': ('notosansdevanagari', 'NotoSansDevanagari[wdth,wght].ttf'),
}

def main():
    cache = ROOT / '.tmp/font-sources'; cache.mkdir(parents=True,exist_ok=True)
    output = ROOT / 'tests/assets/fonts'; output.mkdir(parents=True,exist_ok=True)
    samples = json.loads((ROOT / 'examples/languages.json').read_text(encoding='utf-8'))
    for label,(directory,filename) in FONTS.items():
        url = 'https://raw.githubusercontent.com/google/fonts/main/ofl/' + directory + '/'
        local = cache / filename
        if not local.exists(): urllib.request.urlretrieve(url + urllib.parse.quote(filename), local)
        license_path = output / (label + '-OFL.txt')
        urllib.request.urlretrieve(url + 'OFL.txt', license_path)
        font = TTFont(local)
        if 'fvar' in font:
            font = instantiateVariableFont(font,{a.axisTag:a.defaultValue for a in font['fvar'].axes},inplace=True)
        corpus = ''.join(s['text'] for s in samples if s['font']==label) + ''.join(chr(c) for c in range(32,127))
        if label=='Latin': corpus += ''.join(chr(c) for c in range(160,0x530))
        options = subset.Options(); options.name_IDs = ['*']; options.name_legacy=True
        worker = subset.Subsetter(options=options); worker.populate(text=corpus); worker.subset(font)
        # Rename modified subsets; keep the upstream OFL notices.
        for record in font['name'].names:
            if record.nameID in (1,4,6,16,17):
                name = 'BionicDemo' + label if record.nameID==6 else 'Bionic Demo ' + label
                record.string = name.encode(record.getEncoding(),errors='replace')
        font.save(output / (label+'.ttf'))
        print(label, (output / (label+'.ttf')).stat().st_size,flush=True)

if __name__ == '__main__': main()
