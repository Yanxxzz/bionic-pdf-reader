"""An independently built Identity-H font fixture, including an existing layer."""
from pathlib import Path
from io import BytesIO
from fontTools.ttLib import TTFont
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject as N,DictionaryObject as D,ArrayObject as A,FloatObject as F,NumberObject as I,TextStringObject as T,DecodedStreamObject
import pypdfium2 as pdfium
import pytest
from bionic_pdf import make_pdf

ROOT=Path(__file__).resolve().parents[1]

def stream(writer,data):
    obj=DecodedStreamObject();obj.set_data(data);return writer._add_object(obj)


def cff_fixture(writer, cid_keyed, wrapper, fd_matrix=None):
    from fontTools.cffLib import FDArrayIndex, FDSelect, FontDict
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    names = (['.notdef', 'cid00101', 'cid00003', 'cid00002', 'cid00004'] if cid_keyed
             else ['.notdef', 'bar', 'r', 's', 'second'])
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({ord('r'): names[2]})
    outlines = {}
    for i, name in enumerate(names):
        pen = T2CharStringPen(600, None)
        if i:
            left = 120 * i
            pen.moveTo((left, 40))
            pen.lineTo((left + 65, 40))
            pen.lineTo((left + 65, 650))
            pen.lineTo((left, 650))
            pen.closePath()
        outlines[name] = pen.getCharString()
    builder.setupCFF('ReadingBars', {'FullName': 'Reading Bars'}, outlines, {})
    builder.setupHorizontalMetrics({name: (600, 0) for name in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({'familyName': 'ReadingBars', 'styleName': 'Regular'})
    builder.setupOS2()
    builder.setupPost()
    builder.setupMaxp()
    top = builder.font['CFF '].cff.topDictIndex[0]
    if cid_keyed:
        top.ROS, top.CIDCount = ('Adobe', 'Identity', 0), 102
        fd = FontDict()
        fd.FontName, fd.Private = 'ReadingBars-FD', top.Private
        del top.Private
        if fd_matrix:
            fd.FontMatrix = fd_matrix
        top.FDArray, top.FDSelect = FDArrayIndex(), FDSelect()
        top.FDArray.append(fd)
        top.FDSelect.gidArray = [0] * len(names)
        top.CharStrings.fdArray, top.CharStrings.fdSelect = top.FDArray, top.FDSelect
    buffer = BytesIO()
    builder.save(buffer)
    data = buffer.getvalue() if wrapper == '/OpenType' else TTFont(BytesIO(buffer.getvalue())).getTableData('CFF ')
    program = stream(writer, data)
    program.get_object()[N('/Subtype')] = N(wrapper)
    descriptor = writer._add_object(D({N('/Type'): N('/FontDescriptor'), N('/FontName'): N('/ReadingBars'),
        N('/Flags'): I(4), N('/FontBBox'): A(map(I, [0, 0, 600, 700])), N('/ItalicAngle'): I(0),
        N('/Ascent'): I(800), N('/Descent'): I(-200), N('/CapHeight'): I(650), N('/StemV'): I(65), N('/FontFile3'): program}))
    child = writer._add_object(D({N('/Type'): N('/Font'), N('/Subtype'): N('/CIDFontType0'), N('/BaseFont'): N('/ReadingBars'),
        N('/CIDSystemInfo'): D({N('/Registry'): T('Adobe'), N('/Ordering'): T('Identity'), N('/Supplement'): I(0)}),
        N('/DW'): I(600), N('/FontDescriptor'): descriptor}))
    code = 3 if cid_keyed else 1
    mapping = (f'/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CMapType 2 def '
               f'1 begincodespacerange <0000> <FFFF> endcodespacerange '
               f'2 beginbfchar\n<{code:04x}> <0072>\n<0004> <0072>\nendbfchar endcmap end end')
    font = writer._add_object(D({N('/Type'): N('/Font'), N('/Subtype'): N('/Type0'), N('/BaseFont'): N('/ReadingBars'),
        N('/Encoding'): N('/Identity-H'), N('/DescendantFonts'): A([child]), N('/ToUnicode'): stream(writer, mapping.encode())}))
    return font, code


@pytest.mark.parametrize('cid_keyed', [True, False], ids=['CID-charset', 'GID'])
@pytest.mark.parametrize('wrapper', ['/CIDFontType0C', '/OpenType'])
def test_cff_identity_h_uses_the_font_indices_instead_of_unicode(tmp_path, cid_keyed, wrapper):
    from PIL import ImageChops
    from bionic_pdf.embedded_font import EmbeddedFont

    writer = PdfWriter()
    font, code = cff_fixture(writer, cid_keyed, wrapper)
    embedded = EmbeddedFont.from_pdf(font.get_object())
    sparse_opentype = cid_keyed and wrapper == '/OpenType'
    expected = None if sparse_opentype else ('cid00003' if cid_keyed else 'bar')
    assert embedded.glyph_name(code, 'r') == expected
    assert embedded.glyph_name(4, 'r') == ('cid00004' if cid_keyed else 'second')
    if cid_keyed:
        assert embedded.glyph_name(101, 'r') == (None if sparse_opentype else 'cid00101')
    assert embedded.glyph_name(20000, 'r') is None
    page = writer.add_blank_page(140, 110)
    page[N('/Resources')] = D({N('/Font'): D({N('/F0'): font})})
    encoded = f'{code:04x}' * 5
    control = '0004' * 5
    page[N('/Contents')] = stream(writer, f'BT /F0 20 Tf 20 60 Td <{encoded}> Tj 0 -38 Td <{control}> Tj ET'.encode())
    original, off, static = (tmp_path/name for name in ('source.pdf', 'off.pdf', 'static.pdf'))
    writer.write(original)
    selected = 2 if sparse_opentype else 4
    assert make_pdf(original, off)['glyphs'] == selected and make_pdf(original, static, mode='static')['glyphs'] == selected
    with pdfium.PdfDocument(original) as a, pdfium.PdfDocument(off) as b, pdfium.PdfDocument(static) as c:
        pages = [doc[0] for doc in (a, b, c)]
        assert all(p.get_textpage().get_text_bounded().split() == ['rrrrr', 'rrrrr'] for p in pages)
        before, disabled, enabled = [p.render(scale=4).to_pil().convert('RGB') for p in pages]
        assert before.tobytes() == disabled.tobytes()
        delta = ImageChops.difference(before, enabled)
        # Both source lines have visible ink, including the fallback renderer's sparse-CID glyph.
        assert ImageChops.invert(before.crop((0, 130, 560, 210))).getbbox()
        assert ImageChops.invert(before.crop((0, 280, 560, 370))).getbbox()
        assert bool(delta.crop((0, 130, 560, 210)).getbbox()) == (not sparse_opentype)
        if not sparse_opentype:
            # The glyph's design x is 240 in the CID charset, 120 in the name-keyed GID list.
            left = 99 if cid_keyed else 89
            assert delta.crop((left - 2, 130, left + 8, 210)).getbbox()
            assert not delta.crop((left + 8, 130, left + 15, 210)).getbbox()
        assert delta.crop((0, 280, 176, 370)).getbbox() and not delta.crop((176, 0, 560, 440)).getbbox()


def test_cff_with_nonidentity_fd_transform_is_left_untouched():
    from bionic_pdf.embedded_font import EmbeddedFont

    font, _ = cff_fixture(PdfWriter(), True, '/CIDFontType0C', [1.1, 0, 0, 1, 0, 0])
    assert EmbeddedFont.from_pdf(font.get_object()) is None


def test_cid_width_ranges_use_space_proportional_to_the_table():
    import tracemalloc
    from bionic_pdf.pdf_text import TextFont

    # A wide range, two narrower overrides and gaps using the default width.
    entries = A([I(8), I(199999), I(500), I(20), A([I(610), I(620), I(630)]),
                 I(21), I(21), I(700), I(3), A([I(410)])])
    font = D({N('/Subtype'): N('/Type0'), N('/Encoding'): N('/Identity-H'),
              N('/DescendantFonts'): A([D({N('/W'): entries, N('/DW'): I(900)})])})
    tracemalloc.start()
    try:
        metrics = TextFont.from_pdf(font)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 2 * 1024**2, 'A compact CID range must not allocate one entry per code'
    assert [metrics.width_for(c) for c in (0, 3, 7, 8, 19, 20, 21, 22, 23, 65535)] == [
        900, 410, 900, 500, 500, 610, 700, 630, 500, 500]

def identity_h_font(writer, text):
    font_path=ROOT/'tests/assets/fonts/Latin.ttf';font=TTFont(font_path)
    cmap=font.getBestCmap();upem=font['head'].unitsPerEm
    codes={ord(c):font.getGlyphID(cmap[ord(c)]) for c in text}
    descriptor=writer._add_object(D({N('/Type'):N('/FontDescriptor'),N('/FontName'):N('/BionicDemoLatin'),N('/Flags'):I(4),N('/FontBBox'):A([I(-1000),I(-1000),I(2000),I(2000)]),N('/ItalicAngle'):I(0),N('/Ascent'):I(1000),N('/Descent'):I(-300),N('/CapHeight'):I(750),N('/StemV'):I(80),N('/FontFile2'):stream(writer,font_path.read_bytes())}))
    widths=A()
    for char,gid in codes.items():widths.extend([I(gid),A([F(font['hmtx'][cmap[char]][0]*1000/upem)])])
    child=writer._add_object(D({N('/Type'):N('/Font'),N('/Subtype'):N('/CIDFontType2'),N('/BaseFont'):N('/BionicDemoLatin'),N('/CIDSystemInfo'):D({N('/Registry'):T('Adobe'),N('/Ordering'):T('Identity'),N('/Supplement'):I(0)}),N('/FontDescriptor'):descriptor,N('/CIDToGIDMap'):N('/Identity'),N('/W'):widths}))
    entries='\n'.join(f'<{gid:04x}> <{chr(char).encode("utf-16-be").hex()}>' for char,gid in codes.items())
    to_unicode=f'/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def /CMapName /Demo def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange {len(codes)} beginbfchar\n{entries}\nendbfchar endcmap CMapName currentdict /CMap defineresource pop end end'
    parent=writer._add_object(D({N('/Type'):N('/Font'),N('/Subtype'):N('/Type0'),N('/BaseFont'):N('/BionicDemoLatin'),N('/Encoding'):N('/Identity-H'),N('/DescendantFonts'):A([child]),N('/ToUnicode'):stream(writer,to_unicode.encode())}))
    return parent, ''.join(f'{codes[ord(c)]:04x}' for c in text)


def test_word_spacing_ignores_two_byte_code_0020(tmp_path):
    writer = PdfWriter()
    font, encoded = identity_h_font(writer, 'Reading? More words follow.')
    assert '0020' in [encoded[i:i + 4] for i in range(0, len(encoded), 4)]  # The question mark.
    for spacing in (0, 12):
        page = writer.add_blank_page(320, 90)
        page[N('/Resources')] = D({N('/Font'): D({N('/F0'): font})})
        page[N('/Contents')] = stream(writer, f'BT /F0 15 Tf {spacing} Tw 20 40 Td <{encoded}> Tj ET'.encode())
    source, static, off, on = [tmp_path / name for name in ('source.pdf', 'static.pdf', 'off.pdf', 'on.pdf')]
    writer.write(source)
    make_pdf(source, static, mode='static')
    make_pdf(source, off)
    active = PdfWriter(clone_from=off)
    layers = active.root_object['/OCProperties']
    layers['/D'][N('/ON')] = A(layers['/OCGs'])
    layers['/D'][N('/OFF')] = A()
    active.write(on)

    def render(path):
        with pdfium.PdfDocument(path) as doc:
            return [page.render(scale=2).to_pil().tobytes() for page in doc]

    original, fixed, disabled, enabled = map(render, (source, static, off, on))
    assert original[0] == original[1] and disabled == original
    assert fixed[0] == fixed[1] and enabled == fixed
    assert enabled[0] != original[0]


def test_single_byte_space_moves_the_following_glyph():
    from bionic_pdf.pdf_text import GraphicsState, PageTextReader

    writer = PdfWriter()
    font = D({N('/Type'): N('/Font'), N('/Subtype'): N('/Type1'), N('/BaseFont'): N('/Helvetica')})
    resources = D({N('/Font'): D({N('/F0'): writer._add_object(font)})})
    reader = PageTextReader(writer)

    def positions(word_spacing):
        content = stream(writer, f'BT /F0 15 Tf {word_spacing} Tw (a b) Tj ET'.encode())
        _, glyphs, _ = reader.read(content.get_object(), resources, GraphicsState())
        return [glyph['text_matrix'][4] for glyph in glyphs]

    assert [b - a for a, b in zip(positions(0), positions(12))] == pytest.approx([0, 0, 12])


def test_font_widths_use_drawing_codes_and_recover_after_unknown_advance():
    from bionic_pdf.pdf_text import GraphicsState, PageTextReader, font_width_lookup

    writer = PdfWriter()
    encoding = D({N('/Differences'): A([I(65), N('/W')])})
    font = D({N('/Type'): N('/Font'), N('/Subtype'): N('/Type1'), N('/BaseFont'): N('/Helvetica'),
              N('/Encoding'): encoding})
    assert font_width_lookup(font, False)(65) == 944
    explicit = D({N('/FirstChar'): I(65), N('/Widths'): A([I(0)]),
                  N('/FontDescriptor'): D({N('/MissingWidth'): I(425)})})
    width = font_width_lookup(explicit, False)
    assert width(65) == 0 and width(66) == 425

    unknown = D({N('/Subtype'): N('/Type1'), N('/BaseFont'): N('/Unknown')})
    resources = D({N('/Font'): D({N('/F1'): writer._add_object(unknown), N('/F2'): writer._add_object(font)})})
    content = stream(writer, b'BT /F1 12 Tf (unknown) Tj /F2 12 Tf (wrong) Tj 30 20 Td (known) Tj ET')
    _, glyphs, _ = PageTextReader(writer).read(content.get_object(), resources, GraphicsState())
    assert ''.join(g['text'] for g in glyphs) == 'known'
    assert glyphs[0]['x'] == 30 and all(g['eligible'] for g in glyphs)


@pytest.mark.parametrize('pages', [None, [1]], ids=['whole-document', 'selected-page'])
@pytest.mark.parametrize('layer_inside_text', [False, True], ids=['outer-layer', 'inner-layer'])
def test_identity_h_and_existing_optional_content(tmp_path, pages, layer_inside_text):
    writer=PdfWriter();page=writer.add_blank_page(595,842)
    text='Reading languages preserves original characters.'
    parent, encoded = identity_h_font(writer, text)
    layer=writer._add_object(D({N('/Type'):N('/OCG'),N('/Name'):T('Source notes')}))
    writer.root_object[N('/OCProperties')] = writer._add_object(D({
        N('/OCGs'): A([layer]), N('/D'): D({N('/ON'): A([layer]), N('/Order'): A([layer])}),
    }))
    # Both names are valid in a source PDF and can already be used by its artwork.
    stamp = DecodedStreamObject()
    stamp.set_data(b'48 700 16 16 re f')
    stamp.update({N('/Type'): N('/XObject'), N('/Subtype'): N('/Form'),
                  N('/BBox'): A(map(I, [0, 0, 595, 842])), N('/Resources'): D()})
    page[N('/Resources')] = D({
        N('/Font'): D({N('/F0'): parent}), N('/Properties'): D({N('/BRBionic'): layer}),
        N('/XObject'): writer._add_object(D({N('/BRGlyph0'): writer._add_object(stamp)})),
    })
    text_setup = 'BT /F0 14 Tf 1 0 0 1 48 740 Tm'
    if layer_inside_text:
        drawing = f'/OC /BRBionic BDC /BRGlyph0 Do EMC {text_setup} /OC /BRBionic BDC <{encoded}> Tj EMC ET'
    else:
        drawing = f'/OC /BRBionic BDC /BRGlyph0 Do {text_setup} <{encoded}> Tj ET EMC'
    page[N('/Contents')] = stream(writer, drawing.encode())
    source,target,on,hidden=[tmp_path/name for name in ('cid.pdf','converted.pdf','on.pdf','hidden.pdf')]
    writer.write(source)
    report=make_pdf(source,target,pages=pages);assert report['glyphs']>10
    changed=PdfWriter(clone_from=target);props=changed._root_object['/OCProperties'];all_layers=props['/OCGs']
    assert [str(x.get_object()['/Name']) for x in all_layers]==['Source notes','仿生阅读 · Bionic Reading']
    assert props['/D']['/Order'] == all_layers
    assert props['/D']['/OFF'] == [all_layers[-1]]
    resources = changed.pages[0]['/Resources']
    assert resources['/Properties']['/BRBionic']['/Name'] == 'Source notes'
    assert resources['/XObject']['/BRGlyph0'].get_data() == stamp.get_data()
    props['/D'][N('/ON')]=A(all_layers);props['/D'][N('/OFF')]=A();changed.write(on)
    props['/D'][N('/ON')]=A([all_layers[-1]]);props['/D'][N('/OFF')]=A([all_layers[0]]);changed.write(hidden)
    before,off,active,blank=[pdfium.PdfDocument(p) for p in (source,target,on,hidden)]
    assert text in before[0].get_textpage().get_text_range()
    assert before[0].get_textpage().get_text_range()==active[0].get_textpage().get_text_range()
    raster=lambda d:d[0].render(scale=1.5).to_pil().tobytes()
    assert raster(before)==raster(off)
    assert raster(active)!=raster(off)
    assert len(set(raster(blank)))==1
    static = tmp_path/'static.pdf'
    make_pdf(source, static, pages=pages, mode='static')
    with pdfium.PdfDocument(static) as permanent:
        assert raster(permanent) == raster(active)
    for d in (before,off,active,blank):d.close()
