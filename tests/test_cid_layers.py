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

    assert [b - a for a, b in zip(positions(0), positions(12))] == [0, 0, 12]


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
