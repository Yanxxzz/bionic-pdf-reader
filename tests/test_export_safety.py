"""Regression cases for protected inputs, damaged PDFs and painted-over text."""
import subprocess
import sys
from pathlib import Path

import pypdfium2 as pdfium
import pytest
import reportlab
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.constants import UserAccessPermissions
from pypdf.generic import (ArrayObject, BooleanObject, ByteStringObject, ContentStream, DecodedStreamObject,
                           DictionaryObject, NameObject, NullObject, NumberObject, TextStringObject)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from bionic_pdf import make_pdf
from bionic_pdf.cli import main as run_cli
from bionic_pdf.document import SignatureLossError


@pytest.fixture
def source(tmp_path):
    source = tmp_path / "visibility.pdf"
    font_path = Path(__file__).parent / "assets/fonts/Latin.ttf"
    pdfmetrics.registerFont(TTFont("VisibilityTest", str(font_path)))
    page = Canvas(str(source), pagesize=(280, 160), invariant=True)
    for case in ("cover", "clip"):
        page.setFillColorRGB(1, 1, 1)
        page.rect(0, 0, 280, 160, stroke=0, fill=1)
        page.setFillColorRGB(0, 0, 0)
        page.setFont("VisibilityTest", 15)
        page.saveState()
        # Apply the same partial visibility using two different PDF mechanisms.
        page.translate(10, 0)
        if case == "clip":
            clip = page.beginPath()
            clip.rect(0, 96, 85, 40)
            page.clipPath(clip, stroke=0, fill=0)
        page.drawString(10, 110, "Visible hidden sample words")
        page.restoreState()
        if case == "cover":
            page.setFillColorRGB(1, 1, 1)
            page.rect(95, 96, 185, 40, stroke=0, fill=1)
        page.setFillColorRGB(0, 0, 0)
        page.drawString(20, 45, "Visible control words")
        page.showPage()
    page.save()
    return source


@pytest.mark.parametrize('weight', [-0.5, 0, 0.00499, 0.08001, float('nan'), float('inf'), -float('inf'), None, 'invalid'])
def test_invalid_weight_preserves_output(source, tmp_path, weight, capsys):
    target = tmp_path/'reading.pdf'
    original = source.read_bytes()
    for previous in (None, b'previous output'):
        if previous is not None:
            target.write_bytes(previous)
        with pytest.raises(ValueError, match='weight'):
            make_pdf(source, target, weight=weight)
        assert (target.read_bytes() if target.exists() else None) == previous
        with pytest.raises(SystemExit) as error:
            run_cli([str(source), str(target), f'--weight={weight}'])
        assert error.value.code == 2 and '--weight' in capsys.readouterr().err
        assert (target.read_bytes() if target.exists() else None) == previous
    assert source.read_bytes() == original


@pytest.mark.parametrize('weight', [0.005, 0.08])
def test_weight_endpoints_work_in_api_and_cli(source, tmp_path, weight):
    direct, cli = tmp_path/'direct.pdf', tmp_path/'cli.pdf'
    assert make_pdf(source, direct, mode='static', weight=weight)['glyphs'] > 0
    assert run_cli([str(source), str(cli), '--mode=static', f'--weight={weight}']) == 0
    with pdfium.PdfDocument(direct) as a, pdfium.PdfDocument(cli) as b:
        assert a[0].render(scale=2).to_pil().tobytes() == b[0].render(scale=2).to_pil().tobytes()


def test_damaged_xref_fails_promptly_and_preserves_target(tmp_path):
    source = tmp_path / "damaged.pdf"
    # A truncated xref with a forward startxref, from the upstream 6.21.4 regression.
    source.write_bytes(b"%PDF-1.4\nstartxref\n28\n%%EOF\nxref\n1 0\naaa")
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"keep existing output")
    result = subprocess.run(
        [sys.executable, "-m", "bionic_pdf", str(source), str(target)],
        capture_output=True, timeout=8,
    )
    assert result.returncode == 1 and result.stderr
    assert b"Traceback" not in result.stderr
    assert target.read_bytes() == b"keep existing output"


@pytest.mark.parametrize("mode", ["switchable", "static"])
@pytest.mark.parametrize("open_password", ["", "open-password"], ids=["owner-only", "open-password"])
def test_protected_inputs_never_create_an_unprotected_copy(source, tmp_path, mode, open_password):
    protected = tmp_path / "protected.pdf"
    writer = PdfWriter(clone_from=source)
    writer.encrypt(open_password, "owner-password", permissions_flag=UserAccessPermissions.PRINT)
    writer.write(protected)
    original = protected.read_bytes()
    target = tmp_path / "output.pdf"
    with pytest.raises(ValueError, match="加密"):
        make_pdf(protected, target, mode=mode)
    assert not target.exists()
    target.write_bytes(b"previous copy")
    with pytest.raises(ValueError, match="加密"):
        make_pdf(protected, target, pages=[1], mode=mode)
    assert protected.read_bytes() == original
    assert target.read_bytes() == b"previous copy"


@pytest.mark.parametrize('location', ['nested-field', 'certification'])
def test_signed_pdf_requires_consent_before_processing(source, tmp_path, location):
    writer = PdfWriter(clone_from=source)
    sig = writer._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Sig'), NameObject('/Contents'): ByteStringObject(b'signature'),
        NameObject('/ByteRange'): ArrayObject(map(NumberObject, [0, 50, 100, 20])),
    }))
    if location == 'certification':
        writer.root_object[NameObject('/Perms')] = DictionaryObject({NameObject('/DocMDP'): sig})
    else:
        field = DictionaryObject({NameObject('/FT'): NameObject('/Sig'), NameObject('/V'): sig})
        parent = DictionaryObject({NameObject('/Kids'): ArrayObject([writer._add_object(field)])})
        writer.root_object[NameObject('/AcroForm')] = DictionaryObject({NameObject('/Fields'): ArrayObject([parent])})
    signed, target = tmp_path/'signed.pdf', tmp_path/'existing.pdf'
    writer.write(signed)
    original = signed.read_bytes()
    target.write_bytes(b'previous copy')
    for mode in ('static', 'switchable'):
        with pytest.raises(SignatureLossError, match='签名失效'):
            make_pdf(signed, target, mode=mode, progress=lambda *_: pytest.fail('started before consent'))
        assert target.read_bytes() == b'previous copy'
    make_pdf(signed, target, allow_signature_loss=True)
    assert len(PdfReader(target).pages) == 2 and signed.read_bytes() == original


def test_empty_signature_field_can_be_exported(source, tmp_path):
    writer = PdfWriter(clone_from=source)
    field = DictionaryObject({NameObject('/FT'): NameObject('/Sig')})
    writer.root_object[NameObject('/AcroForm')] = DictionaryObject({NameObject('/Fields'): ArrayObject([field])})
    blank = tmp_path/'empty-signature.pdf'
    writer.write(blank)
    assert make_pdf(blank, tmp_path/'reading.pdf')['pages'] == 2


def test_selected_pages_preserve_labels_bookmarks_and_internal_links(source, tmp_path):
    writer = PdfWriter(clone_from=source)
    writer.add_outline_item('First', 0)
    writer.add_outline_item('Second', 1)
    writer.set_page_label(0, 1, style='/r', prefix='Sec-')
    writer.add_annotation(1, Link(rect=(20, 30, 100, 45), target_page_index=0))
    chapters, output = tmp_path/'chapters.pdf', tmp_path/'selected.pdf'
    writer.write(chapters)
    make_pdf(chapters, output, pages=[2, 1, 2])
    copied = PdfReader(output)
    assert copied.page_labels == ['Sec-ii', 'Sec-i', 'Sec-ii']
    bookmarks = {item.title: copied.get_destination_page_number(item) for item in copied.outline}
    assert bookmarks['First'] == 1 and bookmarks['Second'] in (0, 2)
    for i in (0, 2):
        link = copied.pages[i]['/Annots'][0].get_object()
        assert link['/Dest'][0] == copied.pages[1].indirect_reference
    make_pdf(chapters, output, pages=[2])
    copied = PdfReader(output)
    assert [b.title for b in copied.outline] == ['Second']
    assert not copied.pages[0].get('/Annots')


@pytest.fixture
def tagged(source, tmp_path):
    writer = PdfWriter(clone_from=source)
    writer.pdf_header = '%PDF-2.0'
    root = DictionaryObject({NameObject('/Type'): NameObject('/StructTreeRoot')})
    writer.root_object[NameObject('/StructTreeRoot')] = writer._add_object(root)
    writer.root_object[NameObject('/MarkInfo')] = DictionaryObject({NameObject('/Marked'): BooleanObject(True)})
    writer.root_object[NameObject('/Lang')] = TextStringObject('en')

    def child(parent, role):
        node = DictionaryObject({NameObject('/Type'): NameObject('/StructElem'), NameObject('/S'): NameObject(role),
                                 NameObject('/P'): parent.indirect_reference})
        parent.setdefault(NameObject('/K'), ArrayObject()).append(writer._add_object(node))
        return node

    document = child(root, '/Document')
    paragraph = child(document, '/P')
    numbers = ArrayObject()
    for i, page in enumerate(writer.pages):
        writer.add_outline_item(f'Page {i + 1}', i)
        span = child(paragraph, '/Span')
        span[NameObject('/Lang')] = TextStringObject(('en', 'fr')[i])
        page[NameObject('/StructParents')] = NumberObject(i)
        tagged_text = DecodedStreamObject()
        tagged_text.set_data(b'/Span <</MCID 1>> BDC\n' + page.get_contents().get_data() + b'\nEMC')
        page[NameObject('/Contents')] = writer._add_object(tagged_text)
        if i == 0:
            # Both forms of a marked-content reference are valid.
            span[NameObject('/Pg')] = page.indirect_reference
            span[NameObject('/K')] = NumberObject(1)
        else:
            span[NameObject('/K')] = DictionaryObject({NameObject('/Type'): NameObject('/MCR'),
                NameObject('/MCID'): NumberObject(1), NameObject('/Pg'): page.indirect_reference})
        numbers.extend((NumberObject(i), ArrayObject([NullObject(), span.indirect_reference])))
    annotation = writer.add_annotation(1, Link(rect=(20, 30, 100, 45), target_page_index=0))
    annotation[NameObject('/StructParent')] = NumberObject(2)
    link = child(paragraph, '/Link')
    link[NameObject('/Pg')] = writer.pages[1].indirect_reference
    link[NameObject('/K')] = DictionaryObject({NameObject('/Type'): NameObject('/OBJR'),
                                               NameObject('/Obj'): annotation.indirect_reference})
    numbers.extend((NumberObject(2), link.indirect_reference))
    leaf = writer._add_object(DictionaryObject({NameObject('/Nums'): numbers}))
    root[NameObject('/ParentTree')] = DictionaryObject({NameObject('/Kids'): ArrayObject([leaf])})
    writer.add_blank_page(280, 160)
    path = tmp_path/'tagged.pdf'
    writer.write(path)
    return path


@pytest.mark.parametrize('pages', [[2], [1, 2], [2, 1, 2]])
def test_selected_tags_match_content_annotations_and_reading_order(tagged, tmp_path, pages):
    output = tmp_path/'selected.pdf'
    make_pdf(tagged, output, pages=pages)
    reader = PdfReader(output)
    assert reader.pdf_header == '%PDF-2.0'
    assert reader.root_object['/MarkInfo']['/Marked']
    root = reader.root_object['/StructTreeRoot']
    numbers = root['/ParentTree']['/Nums']
    parents = dict(zip(numbers[::2], numbers[1::2]))
    document, = root['/K']
    paragraphs = document.get_object()['/K']
    assert len(paragraphs) == (2 if pages == [2, 1, 2] else 1)
    logical_pages = []
    for paragraph_ref in paragraphs:
        paragraph = paragraph_ref.get_object()
        assert paragraph.get('/P') == document
        for ref in paragraph['/K']:
            node = ref.get_object()
            assert node.get('/P') == paragraph_ref
            if node['/S'] == '/Span':
                content = node['/K'][0].get_object()
                pg = node['/Pg'] if isinstance(content, NumberObject) else content['/Pg']
                number = reader.get_page_number(pg)
                logical_pages.append(number)
                assert node['/Lang'] == ('en', 'fr')[pages[number] - 1]
                slots = parents[pg['/StructParents']].get_object()
                assert isinstance(slots[0], NullObject) and slots[1] == ref
            else:
                objr = node['/K'][0].get_object()
                pg = objr['/Pg']
                annotation = objr.raw_get('/Obj')
                assert annotation in pg['/Annots']
                assert parents[annotation.get_object()['/StructParent']] == ref
                assert annotation.get_object()['/Dest'][0] == reader.pages[pages.index(1)].indirect_reference
    assert logical_pages == list(range(len(pages)))
    assert sum(len(p.get('/Annots', [])) for p in reader.pages) == (pages.count(2) if 1 in pages else 0)
    assert len(reader.outline) == len(set(pages))
    all_pages = [n for n in reader.xref[0] if isinstance((obj := reader.get_object(n)), DictionaryObject)
                 and obj.get('/Type') == '/Page']
    assert len(all_pages) == len(pages)


@pytest.mark.parametrize('attribute,reason', [('/Ref', '交叉引用'), ('/A', '未选择的页面')])
def test_tagged_selection_refuses_unmapped_references_and_keeps_whole_copy(tagged, tmp_path, attribute, reason):
    writer = PdfWriter(clone_from=tagged)
    document = writer.root_object['/StructTreeRoot']['/K'][0].get_object()
    spans = document['/K'][0].get_object()['/K']
    extra = (ArrayObject([spans[1]]) if attribute == '/Ref' else
             DictionaryObject({NameObject('/O'): NameObject('/Custom'), NameObject('/Page'): writer.pages[2].indirect_reference}))
    spans[0].get_object()[NameObject(attribute)] = extra
    writer.root_object[NameObject('/Version')] = NameObject('/2.0')
    writer.pdf_header = '%PDF-1.7'
    path, target = tmp_path/'cross-reference.pdf', tmp_path/'existing.pdf'
    writer.write(path)
    target.write_bytes(b'keep')
    with pytest.raises(ValueError, match=reason + '.*整本'):
        make_pdf(path, target, pages=[1])
    assert target.read_bytes() == b'keep'
    for selection in (None, [1, 2, 3], [2]):
        make_pdf(path, target, pages=selection)
        result = PdfReader(target)
        assert result.pdf_header == '%PDF-1.7' and result.root_object['/Version'] == '/2.0'
        copied = result.root_object['/StructTreeRoot']['/K'][0].get_object()
        if selection != [2]:
            children = copied['/K'][0].get_object()['/K']
            saved = children[0].get_object()[attribute]
            if attribute == '/Ref':
                assert saved[0] == children[1]
            else:
                assert saved.get('/Page') == result.pages[2].indirect_reference


def test_tagged_form_only_document_can_be_emphasized(tagged, tmp_path):
    writer = PdfWriter(clone_from=tagged)
    page = writer.pages[0]
    form = DecodedStreamObject()
    form.set_data(page.get_contents().get_data())
    form.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                 NameObject('/Resources'): page['/Resources'], NameObject('/BBox'): page.mediabox,
                 NameObject('/StructParents'): page.pop('/StructParents')})
    reference = writer._add_object(form)
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/XObject'): DictionaryObject({NameObject('/TaggedForm'): reference})})
    invoke = DecodedStreamObject()
    invoke.set_data(b'q /TaggedForm Do Q')
    page[NameObject('/Contents')] = writer._add_object(invoke)
    document = writer.root_object['/StructTreeRoot']['/K'][0].get_object()
    span = document['/K'][0].get_object()['/K'][0].get_object()
    span[NameObject('/K')] = DictionaryObject({NameObject('/Type'): NameObject('/MCR'),
        NameObject('/MCID'): NumberObject(1), NameObject('/Pg'): page.indirect_reference, NameObject('/Stm'): reference})
    path, target = tmp_path/'tagged-form.pdf', tmp_path/'output.pdf'
    writer.pages[1].replace_contents(None)
    writer.write(path)
    result = make_pdf(path, target)
    assert result['glyphs'] > 0 and result['unemphasized_pages'] == [2, 3]
    assert make_pdf(path, target, pages=[1])['unemphasized_pages'] == []
    reader = PdfReader(target)
    page = reader.pages[0]
    name, = next(args for args, op in page.get_contents().operations if op == b'Do')
    document = reader.root_object['/StructTreeRoot']['/K'][0].get_object()
    span = document['/K'][0].get_object()['/K'][0].get_object()
    assert span['/K'][0].raw_get('/Stm') == page['/Resources']['/XObject'].raw_get(name)


@pytest.fixture
def shared_tagged_forms(source, tmp_path):
    writer = PdfWriter(clone_from=source)
    first = writer.pages[0]
    fonts = first['/Resources']['/Font']
    font = next(name for name in fonts if fonts[name]['/Subtype'] == '/TrueType')

    def form(data, resources):
        stream = DecodedStreamObject()
        stream.set_data(data)
        stream.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                       NameObject('/BBox'): first.mediabox, NameObject('/Resources'): resources})
        return writer._add_object(stream)

    inner = form(f'/Span <</MCID 0>> BDC BT {font} 18 Tf 24 60 Td (Reading together) Tj ET EMC'.encode(),
                 DictionaryObject({NameObject('/Font'): fonts}))
    inner.get_object()[NameObject('/StructParents')] = NumberObject(7)
    outer = form(b'/Text Do', DictionaryObject({
        NameObject('/XObject'): DictionaryObject({NameObject('/Text'): inner})}))
    outer.get_object()[NameObject('/StructParent')] = NumberObject(8)
    root = DictionaryObject({NameObject('/Type'): NameObject('/StructTreeRoot')})
    writer.root_object[NameObject('/StructTreeRoot')] = writer._add_object(root)
    writer.root_object[NameObject('/MarkInfo')] = DictionaryObject({NameObject('/Marked'): BooleanObject(True)})
    children = ArrayObject()
    paragraph = writer._add_object(DictionaryObject({NameObject('/Type'): NameObject('/StructElem'),
        NameObject('/S'): NameObject('/P'), NameObject('/P'): root.indirect_reference, NameObject('/K'): children}))
    root[NameObject('/K')] = paragraph
    root[NameObject('/ParentTree')] = DictionaryObject({NameObject('/Nums'): ArrayObject([
        NumberObject(7), ArrayObject([paragraph]), NumberObject(8), paragraph])})
    for page, colour in zip(writer.pages, (b'1 0 0', b'0 0 1')):
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/XObject'): DictionaryObject({NameObject('/Panel'): outer})})
        content = DecodedStreamObject()
        content.set_data(colour + b' rg /Panel Do')
        page[NameObject('/Contents')] = writer._add_object(content)
        children.extend((DictionaryObject({NameObject('/Type'): NameObject('/MCR'), NameObject('/MCID'): NumberObject(0),
            NameObject('/Pg'): page.indirect_reference, NameObject('/Stm'): inner, NameObject('/StmOwn'): outer}),
            DictionaryObject({NameObject('/Type'): NameObject('/OBJR'), NameObject('/Pg'): page.indirect_reference,
                              NameObject('/Obj'): outer})))
    path = tmp_path/'shared-tagged.pdf'
    writer.write(path)
    return path


@pytest.mark.parametrize('selection', [None, [2], [2, 1, 2]])
def test_shared_nested_tagged_forms_follow_the_painted_streams(shared_tagged_forms, tmp_path, selection):
    from PIL import ImageChops

    source = shared_tagged_forms
    off, bold = tmp_path/'switchable.pdf', tmp_path/'static.pdf'
    for mode, target in (('switchable', off), ('static', bold)):
        assert make_pdf(source, target, pages=selection, mode=mode)['unemphasized_pages'] == []
    reader = PdfReader(bold)
    root = reader.root_object['/StructTreeRoot']
    nums = root['/ParentTree']['/Nums']
    parents = dict(zip(nums[::2], nums[1::2]))
    physical = selection or [1, 2]
    assert len(parents) == 2 * len(physical)
    top = root['/K']
    paragraphs = list(top) if isinstance(top, ArrayObject) else [top.indirect_reference]
    structure = {}
    for paragraph in paragraphs:
        for kid in paragraph.get_object()['/K']:
            item = kid.get_object()
            structure[(item.get('/Pg'), item['/Type'])] = (item, paragraph)
    with pdfium.PdfDocument(source) as original, pdfium.PdfDocument(off) as off_doc, pdfium.PdfDocument(bold) as bold_doc:
        for i, page in enumerate(reader.pages):
            def painted_form(stream, resources):
                name, = next(args for args, op in ContentStream(stream, reader).operations if op == b'Do')
                return resources['/XObject'].raw_get(name)

            outer = painted_form(page.get_contents(), page['/Resources'])
            inner = painted_form(outer.get_object(), outer.get_object()['/Resources'])
            mark, paragraph = structure[page.indirect_reference, '/MCR']
            obj, _ = structure[page.indirect_reference, '/OBJR']
            assert mark.get('/Stm') == inner and mark.get('/StmOwn') == outer and obj.get('/Obj') == outer
            assert parents[inner.get_object()['/StructParents']][0] == paragraph
            assert parents[outer.get_object()['/StructParent']] == paragraph
            pages = [original[physical[i]-1], off_doc[i], bold_doc[i]]
            text = pages[0].get_textpage().get_text_bounded()
            assert text == 'Reading together' and all(p.get_textpage().get_text_bounded() == text for p in pages[1:])
            before, disabled, enabled = [p.render(scale=2).to_pil().convert('RGB') for p in pages]
            assert before.tobytes() == disabled.tobytes()
            difference = ImageChops.difference(before, enabled)
            assert difference.getbbox() and difference.getchannel('R' if physical[i] == 1 else 'B').getbbox() is None


def test_broken_form_parent_stops_before_writing(shared_tagged_forms, tmp_path):
    writer = PdfWriter(clone_from=shared_tagged_forms)
    numbers = writer.root_object['/StructTreeRoot']['/ParentTree']['/Nums']
    numbers[1] = ArrayObject([NullObject()])
    source, target = tmp_path/'invalid-parent.pdf', tmp_path/'previous.pdf'
    writer.write(source)
    target.write_bytes(b'keep')
    for pages in (None, [2], [2, 1, 2]):
        with pytest.raises(ValueError, match='父级索引'):
            make_pdf(source, target, pages=pages)
        assert target.read_bytes() == b'keep'


def test_shared_form_drops_keys_owned_only_by_an_omitted_page(shared_tagged_forms, tmp_path):
    writer = PdfWriter(clone_from=shared_tagged_forms)
    kids = writer.root_object['/StructTreeRoot']['/K']['/K']
    del kids[2:]  # Page 2 paints the same resources but the source tags only page 1.
    source, target = tmp_path/'one-tagged-placement.pdf', tmp_path/'second.pdf'
    writer.write(source)
    make_pdf(source, target, pages=[2])
    reader = PdfReader(target)
    assert not reader.root_object['/StructTreeRoot']['/ParentTree']['/Nums']
    for number in reader.xref[0]:
        obj = reader.get_object(number)
        if isinstance(obj, DictionaryObject) and obj.get('/Subtype') == '/Form':
            assert '/StructParent' not in obj and '/StructParents' not in obj


def test_same_page_form_reuses_matching_render_and_rejects_ambiguous_placements(shared_tagged_forms, tmp_path):
    writer = PdfWriter(clone_from=shared_tagged_forms)
    page = writer.pages[0]
    source, target = tmp_path/'twice.pdf', tmp_path/'previous.pdf'
    for colour in (b'1 0 0', b'0 0 1'):
        content = DecodedStreamObject()
        content.set_data(b'1 0 0 rg /Panel Do ' + colour + b' rg /Panel Do')
        page[NameObject('/Contents')] = writer._add_object(content)
        writer.write(source)
        if colour == b'1 0 0':
            make_pdf(source, target, pages=[1])
            output = PdfReader(target).pages[0]
            names = [args[0] for args, op in output.get_contents().operations if op == b'Do']
            refs = [output['/Resources']['/XObject'].raw_get(name) for name in names]
            assert len(refs) == 2 and refs[0] == refs[1]
        else:
            previous = target.read_bytes()
            with pytest.raises(ValueError, match='不同且标签无法区分'):
                make_pdf(source, target, pages=[1])
            assert target.read_bytes() == previous


@pytest.mark.parametrize('issue', ['missing', 'omitted-parent'])
def test_broken_structure_parent_index_stops_before_writing(tagged, tmp_path, issue):
    writer = PdfWriter(clone_from=tagged)
    root = writer.root_object['/StructTreeRoot']
    numbers = root['/ParentTree']['/Kids'][0].get_object()['/Nums']
    if issue == 'missing':
        del numbers[:2]
    else:
        numbers[1][1] = numbers[3][1]  # MCID on the first page points to the second page's span.
    path, target = tmp_path/'broken-tags.pdf', tmp_path/'output.pdf'
    writer.write(path)
    target.write_bytes(b'keep')
    with pytest.raises(ValueError, match='父级索引.*整本'):
        make_pdf(path, target, pages=[1])
    assert target.read_bytes() == b'keep'


def test_embedded_postscript_type1_uses_the_original_word_positions(tmp_path):
    fonts = Path(reportlab.__file__).parent/'fonts'
    face = pdfmetrics.EmbeddedType1Face(str(fonts/'DarkGardenMK.afm'), str(fonts/'DarkGardenMK.pfb'))
    pdfmetrics.registerTypeFace(face)
    font = pdfmetrics.Font('Type1OutlineTest', face.name, 'WinAnsiEncoding')
    pdfmetrics.registerFont(font)
    source, target = tmp_path/'type1.pdf', tmp_path/'type1-emphasis.pdf'
    canvas = Canvas(str(source), pagesize=(280, 120), invariant=True)
    canvas.setFont(font.fontName, 18)
    canvas.drawString(30, 55, 'Reading values')
    canvas.save()
    assert make_pdf(source, target, mode='static', locale='en')['glyphs'] == 8
    with pdfium.PdfDocument(source) as original, pdfium.PdfDocument(target) as copy:
        before, after = [doc[0].render(scale=3).to_pil() for doc in (original, copy)]
        boundary = int((30 + pdfmetrics.stringWidth('Read', font.fontName, 18)) * 3)
        end = int((30 + pdfmetrics.stringWidth('Reading', font.fontName, 18)) * 3)
        assert before.crop((90, 80, boundary-6, 270)).tobytes() != after.crop((90, 80, boundary-6, 270)).tobytes()
        assert before.crop((boundary+8, 80, end-5, 270)).tobytes() == after.crop((boundary+8, 80, end-5, 270)).tobytes()


def test_strokes_keep_paint_order_and_partial_clips(source, tmp_path):
    off, on, static = [tmp_path / f"{name}.pdf" for name in ("off", "on", "static")]
    make_pdf(source, off)
    make_pdf(source, static, mode="static")
    writer = PdfWriter(clone_from=off)
    properties = writer.root_object["/OCProperties"]
    properties["/D"][NameObject("/ON")] = ArrayObject(properties["/OCGs"])
    properties["/D"][NameObject("/OFF")] = ArrayObject()
    writer.write(on)
    with (pdfium.PdfDocument(source) as original, pdfium.PdfDocument(off) as disabled,
          pdfium.PdfDocument(on) as enabled, pdfium.PdfDocument(static) as permanent):
        for number in range(len(original)):
            pages = [doc[number] for doc in (original, disabled, enabled, permanent)]
            text = pages[0].get_textpage().get_text_range()
            assert all(page.get_textpage().get_text_range() == text for page in pages[1:])
            before, off_image, on_image, static_image = [page.render(scale=2).to_pil() for page in pages]
            assert before.tobytes() == off_image.tobytes()
            assert on_image.tobytes() == static_image.tobytes()
            hidden = (191, 48, 555, 130)
            assert before.crop(hidden).convert("L").getextrema() == (255, 255)
            assert on_image.crop(hidden).tobytes() == before.crop(hidden).tobytes()
            for visible in ((32, 48, 180, 130), (32, 191, 500, 252)):
                assert on_image.crop(visible).tobytes() != before.crop(visible).tobytes()


def test_strokes_cannot_escape_a_soft_mask_inside_a_text_object(source, tmp_path):
    writer = PdfWriter()
    page = writer.add_page(PdfReader(source).pages[0])
    resources = page['/Resources']
    font = next(name for name, ref in resources['/Font'].items()
                if ref.get_object()['/Subtype'] == '/TrueType')
    mask = DecodedStreamObject()
    mask.set_data(b'0 g 0 0 280 160 re f')
    mask.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                 NameObject('/BBox'): page.mediabox, NameObject('/Resources'): DictionaryObject(),
                 NameObject('/Group'): DictionaryObject({NameObject('/S'): NameObject('/Transparency'),
                                                         NameObject('/CS'): NameObject('/DeviceGray')})})
    soft_mask = DictionaryObject({NameObject('/S'): NameObject('/Luminosity'),
                                  NameObject('/G'): writer._add_object(mask)})
    resources[NameObject('/ExtGState')] = DictionaryObject({
        NameObject('/Hide'): DictionaryObject({NameObject('/SMask'): soft_mask})})
    text = DecodedStreamObject()
    text.set_data((f'BT {font} 15 Tf q /Hide gs 1 0 0 1 20 110 Tm (Hidden sample words) Tj Q '
                   '1 0 0 1 20 45 Tm (Visible control words) Tj ET').encode())
    page[NameObject('/Contents')] = writer._add_object(text)
    original, target = tmp_path/'masked.pdf', tmp_path/'masked-static.pdf'
    writer.write(original)
    make_pdf(original, target, mode='static')
    with pdfium.PdfDocument(original) as plain, pdfium.PdfDocument(target) as bold:
        before, after = [doc[0].render(scale=2).to_pil() for doc in (plain, bold)]
        hidden = (32, 48, 555, 130)
        assert before.crop(hidden).convert("L").getextrema() == (255, 255)
        assert before.crop(hidden).tobytes() == after.crop(hidden).tobytes()
        assert before.tobytes() != after.tobytes()
