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


def create_scaled_text(target):
    """Identical 12-point lines written with different font and graphics scales."""
    pdfmetrics.registerFont(TTFont('ScaleBody', str(ROOT/'tests/assets/fonts/Latin.ttf')))
    pdf = canvas.Canvas(str(target), pagesize=(290, 148), invariant=True)
    for scale in (1, 2, .5, .25):
        pdf.translate(25, 80)
        pdf.scale(scale, scale)
        pdf.setFont('ScaleBody', 12 / scale)
        pdf.drawString(0, 0, 'Reading improves with practice.')
        pdf.showPage()
    pdf.save()
    return target


def create_partial_scan(target, layouts):
    """Scanned sentences with gaps in their authored, selectable text."""
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader

    font = ImageFont.truetype(str(ROOT/'tests/assets/fonts/Latin.ttf'), 64)
    pdf = canvas.Canvas(str(target), pagesize=(480, 150), invariant=1)
    start, baseline = 22, 150 - 165/4

    def hidden_text(x, size):
        text = pdf.beginText(x, baseline)
        text.setFont('Helvetica', size)
        text.setTextRenderMode(3)
        return text

    for layout in layouts:
        if layout == 'wider-font':
            body, second = 'I found a pressed fern between two pages.', 'The next line stays separate.'
            words, size = ('pressed', 'between'), 18.2
        else:
            body, second = 'Reading together readers', 'Research papers retain their words.'
            words, size = ('Reading', 'readers'), 16
        image = Image.new('RGB', (1920, 600), 'white')
        draw = ImageDraw.Draw(image)
        for y, line in ((165, body), (340, second)):
            draw.text((88, y), line, font=font, fill='black', anchor='ls')
        pdf.drawImage(ImageReader(image), 0, 0, 480, 150)
        pdf.saveState()
        if layout == 'one-TJ':
            # One original show operator positions both words around the missing word.
            gap = font.getlength('Reading together ')/4 - pdfmetrics.stringWidth('Reading ', 'Helvetica', 16)
            text = hidden_text(start, size)
            text._code.append(f'[(Reading ) {-1000*gap/16:.4f} (readers)] TJ')
            pdf.drawText(text)
        else:
            for word in words:
                text = hidden_text(start + font.getlength(body[:body.index(word)])/4, size)
                text.textOut(word)
                pdf.drawText(text)
        pdf.restoreState()
        if layout == 'wider-font':
            pdf.drawString(410, 10, '1')
        pdf.showPage()
    pdf.save()
    return target


if __name__=='__main__':
    from pypdf import PdfWriter
    from pypdf.generic import Destination, DictionaryObject, Fit, NameObject, RectangleObject, TextStringObject

    sample = create_sample(ROOT/'.tmp/examples/multilingual.pdf')
    create_scaled_text(sample.with_name('scaled-text.pdf'))
    create_partial_scan(sample.with_name('partial-scan.pdf'), ['one-TJ', 'wider-font'])
    print(sample)
    with PdfWriter() as writer:
        writer.append(sample, pages=(0, 4))
        writer.add_named_destination_object(Destination('Methods + data', writer.pages[3].indirect_reference,
                                                        Fit.xyz(60, 460, 2)))
        for page_index, action in enumerate(('NextPage', 'LastPage', 'FirstPage', 'PrevPage')):
            named_action = DictionaryObject({NameObject('/S'): NameObject('/Named'), NameObject('/N'): NameObject('/' + action)})
            writer.add_annotation(page_index, DictionaryObject({
                NameObject('/Subtype'): NameObject('/Link'), NameObject('/Rect'): RectangleObject((48, 700, 200, 730)),
                NameObject('/Contents'): TextStringObject(action), NameObject('/A'): named_action,
            }))
            if action == 'NextPage':
                writer.add_outline_item('Next slide', None).get_object()[NameObject('/A')] = named_action
        writer.write(sample.with_name('named.pdf'))
    numbers = canvas.Canvas(str(sample.with_name('numbers.pdf')), invariant=1)
    numbers.drawString(48, 700, '12345 67890')
    numbers.save()
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
