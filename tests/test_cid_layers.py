"""An independently built Identity-H font fixture, including an existing layer."""
from pathlib import Path
from io import BytesIO
from fontTools.ttLib import TTFont
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject as N,DictionaryObject as D,ArrayObject as A,FloatObject as F,NumberObject as I,TextStringObject as T,DecodedStreamObject
import pypdfium2 as pdfium
from bionic_pdf import make_pdf

ROOT=Path(__file__).resolve().parents[1]

def stream(writer,data):
    obj=DecodedStreamObject();obj.set_data(data);return writer._add_object(obj)

def test_identity_h_and_existing_optional_content(tmp_path):
    font_path=ROOT/'tests/assets/fonts/Latin.ttf';font=TTFont(font_path)
    cmap=font.getBestCmap();upem=font['head'].unitsPerEm
    text='Reading languages preserves original characters.'
    codes={ord(c):font.getGlyphID(cmap[ord(c)]) for c in text}
    writer=PdfWriter();page=writer.add_blank_page(595,842)
    layer=writer._add_object(D({N('/Type'):N('/OCG'),N('/Name'):T('Source notes')}))
    writer._root_object[N('/OCProperties')]=D({N('/OCGs'):A([layer]),N('/D'):D({N('/ON'):A([layer]),N('/Order'):A([layer])})})
    descriptor=writer._add_object(D({N('/Type'):N('/FontDescriptor'),N('/FontName'):N('/BionicDemoLatin'),N('/Flags'):I(4),N('/FontBBox'):A([I(-1000),I(-1000),I(2000),I(2000)]),N('/ItalicAngle'):I(0),N('/Ascent'):I(1000),N('/Descent'):I(-300),N('/CapHeight'):I(750),N('/StemV'):I(80),N('/FontFile2'):stream(writer,font_path.read_bytes())}))
    widths=A()
    for char,gid in codes.items():widths.extend([I(gid),A([F(font['hmtx'][cmap[char]][0]*1000/upem)])])
    child=writer._add_object(D({N('/Type'):N('/Font'),N('/Subtype'):N('/CIDFontType2'),N('/BaseFont'):N('/BionicDemoLatin'),N('/CIDSystemInfo'):D({N('/Registry'):T('Adobe'),N('/Ordering'):T('Identity'),N('/Supplement'):I(0)}),N('/FontDescriptor'):descriptor,N('/CIDToGIDMap'):N('/Identity'),N('/W'):widths}))
    entries='\n'.join(f'<{gid:04x}> <{chr(char).encode("utf-16-be").hex()}>' for char,gid in codes.items())
    to_unicode=f'/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def /CMapName /Demo def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange {len(codes)} beginbfchar\n{entries}\nendbfchar endcmap CMapName currentdict /CMap defineresource pop end end'
    parent=writer._add_object(D({N('/Type'):N('/Font'),N('/Subtype'):N('/Type0'),N('/BaseFont'):N('/BionicDemoLatin'),N('/Encoding'):N('/Identity-H'),N('/DescendantFonts'):A([child]),N('/ToUnicode'):stream(writer,to_unicode.encode())}))
    page[N('/Resources')]=D({N('/Font'):D({N('/F0'):parent}),N('/Properties'):D({N('/SourceNotes'):layer})})
    encoded=''.join(f'{codes[ord(c)]:04x}' for c in text)
    page[N('/Contents')]=stream(writer,f'/OC /SourceNotes BDC BT /F0 14 Tf 1 0 0 1 48 740 Tm <{encoded}> Tj ET EMC'.encode())
    source,target,on,hidden=[tmp_path/name for name in ('cid.pdf','converted.pdf','on.pdf','hidden.pdf')]
    writer.write(source)
    report=make_pdf(source,target);assert report['glyphs']>10
    changed=PdfWriter(clone_from=target);props=changed._root_object['/OCProperties'];all_layers=props['/OCGs']
    assert [str(x.get_object()['/Name']) for x in all_layers]==['Source notes','仿生阅读 · Bionic Reading']
    props['/D'][N('/ON')]=A(all_layers);props['/D'][N('/OFF')]=A();changed.write(on)
    props['/D'][N('/ON')]=A([all_layers[-1]]);props['/D'][N('/OFF')]=A([all_layers[0]]);changed.write(hidden)
    before,off,active,blank=[pdfium.PdfDocument(p) for p in (source,target,on,hidden)]
    assert text in before[0].get_textpage().get_text_range()
    assert before[0].get_textpage().get_text_range()==active[0].get_textpage().get_text_range()
    raster=lambda d:d[0].render(scale=1.5).to_pil().tobytes()
    assert raster(before)==raster(off)
    assert raster(active)!=raster(off)
    assert len(set(raster(blank)))==1
    for d in (before,off,active,blank):d.close()
