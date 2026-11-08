"""Generate original, redistributable reading samples; never use personal PDFs."""
from pathlib import Path
import json
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]

def create_sample(target, samples=None):
    samples = samples or json.loads((ROOT/'examples/languages.json').read_text(encoding='utf-8'))
    fonts=ROOT/'tests/assets/fonts'
    for label in {x['font'] for x in samples} | {'Latin'}:
        pdfmetrics.registerFont(TTFont('Demo'+label,str(fonts/(label+'.ttf')),shapable=True))
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(target),pagesize=(595,842),invariant=1)
    c.setTitle('Bionic PDF Reader - original multilingual samples')
    for item in samples:
        c.bookmarkPage(item['code']);c.addOutlineEntry(item['code'],item['code'])
        c.setFillColorRGB(.13,.32,.25);c.setFont('Helvetica-Bold',21)
        c.drawString(48,778,'A different rhythm for reading')
        c.setFillColorRGB(.45,.52,.48);c.setFont('Helvetica',10)
        c.drawString(48,750,'ORIGINAL SAMPLE  /  '+item['code'].upper()+'  /  LOCAL & PRIVATE')
        c.setFont('Demo'+item['font'],15);c.setFillColorRGB(.12,.16,.14)
        y=688;line=''
        def draw_line(text):
            c.drawString(48,y,text)
        # Keep each authored language sample within the page margins.
        for char in item['text']:
            if pdfmetrics.stringWidth(line+char,'Demo'+item['font'],15)>490:
                draw_line(line);y-=28;line=''
            line+=char
        if line:draw_line(line)
        c.setFont('DemoLatin',13)
        c.drawString(48,y-70,'Reading keeps the original text, page and spacing.')
        c.setFont('Helvetica',11);c.drawString(48,120,'Formula: y = 2 x + 1')
        c.linkURL('https://github.com/Yanxxzz/bionic-pdf-reader',(48,52,420,70),relative=0)
        c.setFont('Helvetica',9);c.drawString(48,58,'Bionic PDF Reader - original demo. Fonts: Noto, SIL Open Font License.')
        c.showPage()
    c.showPage();c.save()
    return target

if __name__=='__main__':
    from pypdf import PdfWriter
    from pypdf.generic import Destination, Fit

    sample = create_sample(ROOT/'.tmp/examples/multilingual.pdf')
    print(sample)
    with PdfWriter() as writer:
        writer.append(sample, pages=(0, 4))
        writer.add_named_destination_object(Destination('Methods + data', writer.pages[3].indirect_reference,
                                                        Fit.xyz(60, 460, 2)))
        writer.write(sample.with_name('named.pdf'))
    locked = canvas.Canvas(str(ROOT/'.tmp/examples/locked.pdf'), invariant=1, encrypt='reader-test')
    locked.drawString(48, 740, 'Password protected example')
    locked.save()

    from reportlab.lib.pdfencrypt import StandardEncryption
    restricted = canvas.Canvas(str(ROOT/'.tmp/examples/restricted.pdf'), pagesize=(300, 400), invariant=1,
                               encrypt=StandardEncryption('', 'example-owner', canCopy=0))
    restricted.setFont('DemoLatin', 14)
    restricted.drawString(30, 300, 'Read the next chapter')
    restricted.drawString(170, 240, 'multi-')
    restricted.drawString(30, 220, 'plicative Straße')
    restricted.linkRect('Next chapter', 'chapter-two', (30, 295, 190, 318), relative=0)
    restricted.showPage()
    restricted.bookmarkPage('chapter-two')
    restricted.setFont('DemoLatin', 14)
    restricted.drawString(30, 300, 'Second chapter')
    restricted.drawString(55, 220, 'Multiplicative STRASSE')
    restricted.save()
