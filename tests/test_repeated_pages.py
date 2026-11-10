"""A repeated physical page has its own local links and shares logical form values."""
import os
import subprocess
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.constants import FieldDictionaryAttributes
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject, IndirectObject,
                           NameObject, NumberObject, StreamObject, TextStringObject)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from bionic_pdf import make_pdf


def worksheet(folder, *, buttons=False, page_count=2):
    path = folder/'worksheet.pdf'
    pdfmetrics.registerFont(TTFont('Worksheet', str(Path(__file__).parent/'assets/fonts/Latin.ttf')))
    canvas = Canvas(str(path), pagesize=(320, 200), invariant=True)
    for number in range(1, page_count + 1):
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


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('mode', ['static', 'switchable'])
def test_selected_calculations_cannot_recover_omitted_fields_or_pages(tmp_path, mode, nested):
    writer = PdfWriter(clone_from=worksheet(tmp_path, page_count=3))
    form = writer.root_object['/AcroForm']
    fields = list(form['/Fields'])
    if nested:
        group = writer._add_object(DictionaryObject({NameObject('/T'): TextStringObject('Quiz'),
                                                     NameObject('/Kids'): ArrayObject(fields)}))
        for field in fields:
            field.get_object()[NameObject('/Parent')] = group
        form[NameObject('/Fields')] = ArrayObject([group])
    for n, field in enumerate(fields, 1):
        field.get_object()[NameObject('/AA')] = DictionaryObject({NameObject('/C'): DictionaryObject({
            NameObject('/S'): NameObject('/JavaScript'), NameObject('/JS'): TextStringObject(f'event.value = {n}73;')})})
    form[NameObject('/CO')] = writer._add_object(ArrayObject(reversed(fields)))
    source = tmp_path/'calculations.pdf'
    writer.write(source)
    executable = os.environ.get('BIONIC_FORM_TEST_EXE')

    for pages in ('1', '2', '1,1', '2,1,2', '2,3', '3,1,2', '1,2,3'):
        selected = list(map(int, pages.split(',')))
        output = tmp_path/f'{pages}.pdf'
        if executable:
            subprocess.run([executable, '--cli', str(source), str(output), '--pages', pages, '--mode', mode],
                           check=True, timeout=90)
        else:
            make_pdf(source, output, pages=pages, mode=mode)
        saved = PdfReader(output)
        order = saved.root_object['/AcroForm']['/CO']
        assert [ref.get_object()['/T'] for ref in order] == [f'Answer{n}' for n in (3, 2, 1) if n in selected]
        registered = saved.get_fields()
        for n in (1, 2, 3):
            name = ('Quiz.' if nested else '') + f'Answer{n}'
            if n not in selected:
                assert name not in registered
                continue
            field = registered[name].indirect_reference
            assert field in order and field.get_object()['/V'] == f'Original{n}'
            assert field.get_object()['/AA']['/C']['/JS'] == f'event.value = {n}73;'

        visible = {page.indirect_reference for page in saved.pages}
        assert len(visible) == len(selected)
        del saved.root_object['/Pages']  # Recover objects using the xref alone, as a recipient could.
        for generation, entries in saved.xref.items():
            if generation == 65535:
                continue
            for number in entries:
                ref = IndirectObject(number, generation, saved)
                obj = ref.get_object()
                if isinstance(obj, DictionaryObject) and obj.get('/Type') == '/Page':
                    assert ref in visible
                data = obj.get_data() if isinstance(obj, StreamObject) else str(obj).encode()
                for n in {1, 2, 3} - set(selected):
                    for marker in (f'Question number {n}', f'Answer{n}', f'Original{n}', f'event.value = {n}73;'):
                        assert marker.encode() not in data


@pytest.mark.parametrize('dependency', ['XFA', 'cross-field action', 'field without page pointer'])
def test_inseparable_form_refuses_partial_export_atomically(tmp_path, dependency):
    writer = PdfWriter(clone_from=worksheet(tmp_path))
    form = writer.root_object['/AcroForm']
    first, second = form['/Fields']
    if dependency == 'XFA':
        packet = DecodedStreamObject()
        packet.set_data(b'<datasets><private>Original2</private></datasets>')
        form[NameObject('/XFA')] = writer._add_object(packet)
    else:
        first.get_object()[NameObject('/AA')] = DictionaryObject({NameObject('/K'): DictionaryObject({
            NameObject('/S'): NameObject('/ResetForm'), NameObject('/Fields'): ArrayObject([second])})})
        form[NameObject('/CO')] = ArrayObject([first, second])
        if dependency == 'field without page pointer':
            del second.get_object()['/P']
    source, target = tmp_path/'shared-form.pdf', tmp_path/'previous.pdf'
    writer.write(source)
    target.write_bytes(b'previous')
    with pytest.raises(ValueError, match='导出全部页面'):
        make_pdf(source, target, pages='1')
    assert target.read_bytes() == b'previous'
    make_pdf(source, target)
    assert PdfReader(target).get_fields()['Answer2']['/V'] == 'Original2'
