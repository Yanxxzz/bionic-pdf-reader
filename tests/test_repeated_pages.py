"""A repeated physical page has its own local links and shares logical form values."""
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.constants import FieldDictionaryAttributes
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from bionic_pdf import make_pdf


def worksheet(folder, *, buttons=False):
    path = folder/'worksheet.pdf'
    pdfmetrics.registerFont(TTFont('Worksheet', str(Path(__file__).parent/'assets/fonts/Latin.ttf')))
    canvas = Canvas(str(path), pagesize=(320, 200), invariant=True)
    for number in (1, 2):
        canvas.setFont('Worksheet', 16)
        canvas.drawString(15, 152, f'Question number {number}')
        canvas.acroForm.textfield(name=f'Answer{number}', value=f'Original{number}', x=15, y=80, width=170)
        if buttons:
            canvas.acroForm.radio(name='Choice', value=f'Choice{number}', selected=number == 1, x=15, y=45)
            canvas.acroForm.checkbox(name=f'Agree{number}', checked=True, x=65, y=45)
        canvas.showPage()
    canvas.save()
    return path


def test_repeated_local_links_keep_their_own_page_and_coordinates(tmp_path):
    writer = PdfWriter(clone_from=worksheet(tmp_path))
    dest = ArrayObject([writer.pages[1].indirect_reference, NameObject('/XYZ'),
                        NumberObject(10), NumberObject(72), NumberObject(2)])
    title = TextStringObject('Footnote')
    writer.add_named_destination_array(title, dest)
    for use_action in (False, True):
        for value in (dest, title):
            link = writer.add_annotation(1, Link(rect=(0, 0, 50, 20), target_page_index=1))
            if use_action:
                del link['/Dest']
                link[NameObject('/A')] = writer._add_object(DictionaryObject({
                    NameObject('/S'): NameObject('/GoTo'), NameObject('/D'): value}))
            else:
                link[NameObject('/Dest')] = value
    writer.add_annotation(1, Link(rect=(60, 0, 110, 20), target_page_index=0))
    path, output = tmp_path/'local-links.pdf', tmp_path/'repeated.pdf'
    writer.write(path)
    make_pdf(path, output, pages='2,1,2')
    saved = PdfReader(output)
    named = saved.named_destinations
    for index in (0, 2):
        page = saved.pages[index]
        links = [ref.get_object() for ref in page['/Annots'] if ref.get_object()['/Subtype'] == '/Link']
        assert len(links) == 5
        for link in links[:4]:
            value = link['/Dest'] if '/Dest' in link else link['/A']['/D']
            target = named[value].dest_array if isinstance(value, str) else value
            assert list(target) == [page.indirect_reference, '/XYZ', 10, 72, 2]
        assert links[-1]['/Dest'][0] == saved.pages[1].indirect_reference


def test_repeated_widgets_remain_in_their_logical_fields(tmp_path):
    writer = PdfWriter(clone_from=worksheet(tmp_path))
    # Keep one combined field/widget inside a field group, and split the other
    # into the common representation with an existing terminal field and widget.
    fields = writer.root_object['/AcroForm']['/Fields']
    group = writer._add_object(DictionaryObject({NameObject('/T'): TextStringObject('Quiz'),
                                                  NameObject('/Kids'): ArrayObject(fields)}))
    writer.root_object['/AcroForm'][NameObject('/Fields')] = ArrayObject([group])
    first, second = (ref.get_object() for ref in fields)
    for field in (first, second):
        field[NameObject('/Parent')] = group
    child = DictionaryObject({key: second.pop(key) for key in list(second)
                              if key in ('/Subtype', '/Type', '/P', '/Rect', '/F', '/AP', '/BS', '/MK')})
    child[NameObject('/Parent')] = fields[1]
    widget = writer._add_object(child)
    second[NameObject('/Kids')] = ArrayObject([widget])
    writer.pages[1][NameObject('/Annots')] = ArrayObject([widget])
    writer.root_object['/AcroForm'][NameObject('/CO')] = ArrayObject(fields)
    path, target = tmp_path/'fields.pdf', tmp_path/'selected.pdf'
    writer.write(path)
    make_pdf(path, target, pages='2,1,2,1')
    saved = PdfReader(target)
    acro = saved.root_object['/AcroForm']
    registered = saved.get_fields()
    for number, positions in ((1, (1, 3)), (2, (0, 2))):
        name = f'Quiz.Answer{number}'
        parent = registered[name].indirect_reference
        children = parent.get_object()['/Kids']
        assert parent == acro['/CO'][number - 1]
        assert {saved.pages[i]['/Annots'][0] for i in positions} == set(children)
        for i in positions:
            widget = saved.pages[i]['/Annots'][0].get_object()
            assert widget.raw_get('/Parent') == parent
            assert widget.raw_get('/P') == saved.pages[i].indirect_reference
            assert '/V' not in widget and '/T' not in widget

    with pdfium.PdfDocument(path) as source, pdfium.PdfDocument(target) as result:
        source.init_forms()
        result.init_forms()
        for i, original in enumerate((1, 0, 1, 0)):
            assert source[original].render(scale=2).to_pil().tobytes() == result[i].render(scale=2).to_pil().tobytes()

    edit = PdfWriter(clone_from=target)
    edit.update_page_form_field_values(edit.pages[1], {'Quiz.Answer1': 'Filled'}, auto_regenerate=False)
    edit.write(tmp_path/'filled.pdf')
    assert PdfReader(tmp_path/'filled.pdf').get_fields()['Quiz.Answer1']['/V'] == 'Filled'


def test_button_values_follow_the_selected_and_repeated_widgets(tmp_path):
    writer = PdfWriter(clone_from=worksheet(tmp_path, buttons=True))
    radio = writer.get_fields()['Choice'].indirect_reference.get_object()
    radio[NameObject('/Opt')] = ArrayObject(map(TextStringObject, ('First answer', 'Second answer')))
    source, target = tmp_path/'buttons.pdf', tmp_path/'second-twice.pdf'
    writer.write(source)
    make_pdf(source, target, pages='2')
    assert PdfReader(target).get_fields()['Choice']['/Opt'] == ['Second answer']
    make_pdf(source, target, pages='2,2')
    saved = PdfReader(target)
    fields = saved.get_fields()
    radio = fields['Choice'].indirect_reference.get_object()
    assert radio['/Opt'] == ['Second answer', 'Second answer']
    assert radio['/Ff'] & FieldDictionaryAttributes.FfBits.RadiosInUnison
    assert {child.get_object()['/P'].indirect_reference for child in radio['/Kids']} == {
        page.indirect_reference for page in saved.pages}
    assert len(fields['Agree2']['/Kids']) == 2 and fields['Agree2']['/V'] == '/Yes'
