"""Generate original, redistributable reading samples; never use personal PDFs."""
from pathlib import Path
import json
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]

def create_first_read(target):
    """Build the two original pages bundled with the reader's first-use guide."""
    pdfmetrics.registerFont(TTFont('FirstRead', str(ROOT/'tests/assets/fonts/Latin.ttf')))
    pdf = canvas.Canvas(str(target), pagesize=(432, 420), invariant=True)
    pdf.setTitle('A closer reading')
    pdf.setAuthor('Bionic PDF Reader')
    pages = [
        ('A closer reading', 'opening', 'A place to begin',
         ['Reading begins with a single clear line.',
          'Follow the first letters of each word, then read',
          'the same sentence again at your own pace.'],
         'Compare the first letters in Original and Bionic mode.',
         'Read the field note on page two', 'field-note'),
        ('The field note', 'field-note', 'A place to return',
         ['Reading can feel different on a familiar page.',
          'Look for the word reading on both pages, then',
          'return to the line where you started.'],
         'Try Find, then use the return button to go back.',
         'Return to the opening page', 'opening'),
    ]
    for number, (title, destination, section, lines, hint, link, target_name) in enumerate(pages, 1):
        pdf.bookmarkPage(destination)
        pdf.addOutlineEntry(title, destination)
        pdf.setFillColorRGB(.985, .978, .95)
        pdf.rect(0, 0, 432, 420, fill=1, stroke=0)
        pdf.setFillColorRGB(.095, .235, .19)
        pdf.setFont('FirstRead', 10)
        pdf.drawString(34, 383, 'Bionic PDF Reader')
        pdf.drawRightString(398, 383, f'{number} / 2')
        pdf.setStrokeColorRGB(.68, .71, .62)
        pdf.line(34, 370, 398, 370)
        pdf.setFont('Times-Roman', 34)
        pdf.drawString(33, 310, title)
        pdf.setFont('FirstRead', 11)
        pdf.drawString(35, 282, section)
        pdf.setFillColorRGB(.14, .18, .16)
        pdf.setFont('FirstRead', 14)
        for row, line in enumerate(lines):
            pdf.drawString(35, 223 - row * 22, line)
        pdf.setFont('FirstRead', 10)
        pdf.drawString(35, 120, hint)
        pdf.setFillColorRGB(.095, .30, .22)
        pdf.setFont('FirstRead', 12)
        pdf.drawString(35, 65, link)
        end = 35 + pdf.stringWidth(link, 'FirstRead', 12)
        pdf.line(35, 61, end, 61)
        pdf.linkRect(link, target_name, (32, 56, end + 2, 81), thickness=0)
        pdf.showPage()
    pdf.save()


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


def create_rotated_text(target):
    """Four visually identical pages with different PDF page and text rotations."""
    width, height = 320, 210
    pdfmetrics.registerFont(TTFont('RotationBody', str(ROOT/'tests/assets/fonts/Latin.ttf')))
    pdf = canvas.Canvas(str(target), pagesize=(width, height), invariant=True)
    for angle, matrix in ((0, (1, 0, 0, 1, 0, 0)), (90, (0, 1, -1, 0, height, 0)),
                          (180, (-1, 0, 0, -1, width, height)), (270, (0, -1, 1, 0, 0, width))):
        pdf.setPageRotation(angle)
        pdf.transform(*matrix)
        pdf.setFont('RotationBody', 15)
        pdf.drawString(34, 69, 'Reading together improves recall.')
        pdf.showPage()
    pdf.save()
    return target


def create_reading_order(target):
    """The second page paints the right word before the left one, with exact tagged spellings."""
    pdf = canvas.Canvas(str(target), pagesize=(320, 210), invariant=True)
    pdf.drawString(34, 69, 'Opening page.')
    pdf.showPage()
    pdf.setPageRotation(90)
    pdf.transform(0, 1, -1, 0, 210, 0)
    pdf.setFont('Helvetica', 15)
    for word, offset in (('together.', pdfmetrics.stringWidth('Reading ', 'Helvetica', 15)), ('Reading', 0)):
        pdf.addLiteral(f'/Span << /ActualText ({word}) >> BDC')
        pdf.drawString(34 + offset, 69, word)
        pdf.addLiteral('EMC')
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
    create_rotated_text(sample.with_name('rotated-text.pdf'))
    create_reading_order(sample.with_name('reading-order.pdf'))
    create_partial_scan(sample.with_name('partial-scan.pdf'), ['one-TJ', 'wider-font'])
    print(sample)
    with PdfWriter() as writer:
        writer.append(sample, pages=(0, 4))
        methods = Fit.xyz(60, 460, 2)
        writer.add_named_destination_object(Destination('Methods + data', writer.pages[3].indirect_reference, methods))
        writer.add_outline_item('Methods paragraph', 3, fit=methods)
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
