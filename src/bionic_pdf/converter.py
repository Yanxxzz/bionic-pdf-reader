"""Create a WPS-switchable reading copy with one optional vector stroke layer.

Original PDF text remains the only text. Embedded glyph outlines are reused as
vector Form XObjects; no duplicate text or rasterized pages are introduced.
"""
from __future__ import annotations

import io
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
from fontTools import agl
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject as A, DictionaryObject as D, NameObject as N,
    NumberObject as I, FloatObject as F, TextStringObject as T,
    DecodedStreamObject)
from .pdf_text import PageTextReader, matrix_multiply
from .layout import select_glyphs


LAYER_NAME = '仿生阅读 · Bionic Reading'


def num(value):
    return f'{float(value):.7f}'.rstrip('0').rstrip('.') or '0'


class PathPen(BasePen):
    def __init__(self, glyph_set):
        super().__init__(glyph_set)
        self.commands = []
    def _moveTo(self, point): self.commands.append(' '.join(map(num, point)) + ' m')
    def _lineTo(self, point): self.commands.append(' '.join(map(num, point)) + ' l')
    def _curveToOne(self, a, b, d): self.commands.append(' '.join(map(num, (*a,*b,*d))) + ' c')
    def _closePath(self): self.commands.append('h')
    def _endPath(self): pass


class GlyphLibrary:
    def __init__(self, writer, weight):
        self.writer, self.weight = writer, weight
        self.fonts, self.forms = {}, {}
        self.skipped_fonts = set()
    def font(self, font):
        key = font.indirect_reference.idnum if getattr(font, 'indirect_reference', None) else id(font)
        if key in self.fonts: return self.fonts[key]
        info = None
        cid = font.get('/Subtype') == '/Type0'
        descendant = font['/DescendantFonts'][0].get_object() if cid else font
        descriptor = descendant.get('/FontDescriptor')
        descriptor = descriptor.get_object() if descriptor else {}
        try:
            if '/FontFile3' in descriptor and descriptor['/FontFile3'].get('/Subtype') == '/Type1C':
                cff = CFFFontSet()
                cff.decompile(io.BytesIO(descriptor['/FontFile3'].get_data()), None)
                top = cff[cff.fontNames[0]]
                info = {'glyphs': top.CharStrings, 'matrix': tuple(top.FontMatrix), 'bbox': tuple(top.FontBBox), 'owner': cff}
            elif '/FontFile2' in descriptor:
                tt = TTFont(io.BytesIO(descriptor['/FontFile2'].get_data()))
                upem = tt['head'].unitsPerEm
                info = {'glyphs': tt.getGlyphSet(), 'matrix': (1/upem,0,0,1/upem,0,0),
                    'bbox': (tt['head'].xMin,tt['head'].yMin,tt['head'].xMax,tt['head'].yMax), 'owner': tt,
                    'cmap': tt.getBestCmap() or {},
                    'byte_cmap': next((t.cmap for t in tt['cmap'].tables if t.platformID==1 and t.platEncID==0),{})}
                if cid:
                    cidmap = descendant.get('/CIDToGIDMap')
                    info['cidmap'] = cidmap.get_object().get_data() if cidmap is not None and hasattr(cidmap.get_object(),'get_data') else None
                    info['glyph_order'] = tt.getGlyphOrder()
            if info:
                encoding = font.get('/Encoding')
                differences, index = {}, 0
                if isinstance(encoding, D):
                    for item in encoding.get('/Differences', []):
                        if isinstance(item, (int, I)): index = int(item)
                        else: differences[index] = str(item)[1:]; index += 1
                info['differences'] = differences
                info['key'] = key
        except (KeyError, ValueError, AssertionError):
            info = None
        self.fonts[key] = info
        return info
    def glyph(self, font, byte, unicode_text):
        info = self.font(font)
        if not info:
            self.skipped_fonts.add(str(font.get('/BaseFont')))
            return None
        name = info['differences'].get(byte)
        if not name and 'glyph_order' not in info:
            name = info.get('byte_cmap',{}).get(byte)
        if 'glyph_order' in info:
            cidmap = info['cidmap']
            gid = int.from_bytes(cidmap[byte*2:byte*2+2],'big') if cidmap is not None else byte
            name = info['glyph_order'][gid] if gid < len(info['glyph_order']) else None
        if not name:
            if len(unicode_text) == 1:
                name = info.get('cmap', {}).get(ord(unicode_text)) or agl.UV2AGL.get(ord(unicode_text))
            elif unicode_text in ('fi', 'fl', 'ff', 'ffi', 'ffl'):
                name = unicode_text
        if not name or name not in info['glyphs']: return None
        key = (info['key'], name)
        if key not in self.forms:
            pen = PathPen(info['glyphs'])
            info['glyphs'][name].draw(pen)
            if not pen.commands: return None
            # Width is in the glyph's units, so all text sizes share this form.
            em_scale = max(abs(info['matrix'][0]), abs(info['matrix'][3]))
            line_width = self.weight / em_scale
            content = ('q ' + num(line_width) + ' w 1 j 1 J\n' + '\n'.join(pen.commands) + '\nS Q\n').encode('ascii')
            form = DecodedStreamObject()
            form.set_data(content)
            x0,y0,x1,y1 = info['bbox']
            form.update({N('/Type'): N('/XObject'), N('/Subtype'): N('/Form'),
                N('/BBox'): A(F(x) for x in (x0-line_width,y0-line_width,x1+line_width,y1+line_width)),
                N('/Resources'): D()})
            self.forms[key] = (N('/BRGlyph' + str(len(self.forms))), self.writer._add_object(form.flate_encode()))
        name, reference = self.forms[key]
        return name, reference, info['matrix']


def _bind_resource(resources, group, preferred, reference):
    """Bind the object without displacing a resource used by the original page."""
    entries = resources.setdefault(N(group), D()).get_object()
    name = preferred
    suffix = 1
    while name in entries and entries.raw_get(name) != reference:
        name = N(f'{preferred}_{suffix}')
        suffix += 1
    entries[name] = reference
    return name


class OverlayBuilder:
    def __init__(self, writer, layer, weight=0.026):
        self.writer, self.layer = writer, layer
        self.text_reader = PageTextReader()
        self.glyphs = GlyphLibrary(writer, weight)
        self.count = 0
        save = DecodedStreamObject()
        save.set_data(b'q\n')
        self.save_graphics_state = writer._add_object(save)

    def build_page(self, page):
        content = page.get_contents()
        if content is None:
            return
        resources = page.get('/Resources', D())
        records = self.text_reader.read(content.operations, resources)
        commands, glyph_names = [], {}
        for index in sorted(select_glyphs(records)):
            record = records[index]
            glyph = self.glyphs.glyph(record['font'], record['code'], record['text'])
            if glyph is None:
                continue
            preferred, reference, font_matrix = glyph
            if preferred not in glyph_names:
                glyph_names[preferred] = _bind_resource(resources, '/XObject', preferred, reference)
            name = glyph_names[preferred]
            size = record['size']
            scale = (size * record['tz'], 0, 0, size, 0, 0)
            transform = matrix_multiply(record['matrix'], matrix_multiply(scale, font_matrix))
            matrix = ' '.join(map(num, transform))
            color = ' '.join(map(str, record['color']))
            draw = f"q {matrix} cm {record['cs']} CS {color} SCN {name} Do Q"
            layers = record['oc']
            begin = ' '.join(f'/OC {tag} BDC' for tag in layers)
            commands.append(f'{begin} {draw}' + ' EMC' * len(layers))
        if not commands:
            return
        self.count += len(commands)
        if self.layer is not None:
            tag = _bind_resource(resources, '/Properties', N('/BRBionic'), self.layer)
            commands.insert(0, f'/OC {tag} BDC')
            commands.append('EMC')
        stream = DecodedStreamObject()
        stream.set_data(('\nQ\n' + '\n'.join(commands) + '\n').encode('ascii'))
        # Keep shared source streams untouched by giving this page its own array.
        original = page['/Contents']
        parts = original if isinstance(original, A) else [page.raw_get('/Contents')]
        page[N('/Contents')] = A([self.save_graphics_state, *parts, self.writer._add_object(stream.flate_encode())])


def _add_reading_layer(writer):
    catalog = writer.root_object
    properties = catalog.setdefault(N('/OCProperties'), D()).get_object()
    default = D({N('/Name'): T('Reading mode'), N('/BaseState'): N('/ON')})
    config = properties.setdefault(N('/D'), default).get_object()
    layer = writer._add_object(D({N('/Type'): N('/OCG'), N('/Name'): T(LAYER_NAME)}))
    properties.setdefault(N('/OCGs'), A()).get_object().append(layer)
    for key in ('/OFF', '/Order'):
        config.setdefault(N(key), A()).get_object().append(layer)
    catalog[N('/PageMode')] = N('/UseOC')
    return layer


def make_pdf(source, target, pages=None, weight=0.026, mode='switchable', locale='auto', *,
             progress: Callable[[int, int], None] | None = None):
    """Create a reading copy; optionally report each processed page as (current, total)."""
    started = time.monotonic()
    source, target = Path(source), Path(target)
    if mode not in ('switchable', 'static'):
        raise ValueError('mode must be switchable or static')
    if source.resolve() == target.resolve():
        raise ValueError('请为阅读副本选择不同文件名，不能覆盖原 PDF。')
    reader = PdfReader(source)
    if reader.is_encrypted and not reader.decrypt(''):
        raise ValueError('请先打开并另存为未加密的 PDF。')
    source_layers = reader.root_object.get('/OCProperties')
    if source_layers is not None:
        groups = source_layers.get_object().get('/OCGs', A()).get_object()
        if any(group.get_object().get('/Name') == LAYER_NAME for group in groups):
            raise ValueError('这份 PDF 已包含仿生开关，请直接在 WPS 中切换，或选择原始 PDF。')

    writer = PdfWriter(clone_from=reader) if pages is None else PdfWriter()
    writer.pdf_header = b'%PDF-1.6'
    if pages is not None:
        for number in pages:
            writer.add_page(reader.pages[number - 1])
        # Page resources refer to layers whose controls live in the document catalog.
        if source_layers is not None:
            writer.root_object[N('/OCProperties')] = source_layers.clone(writer)

    if mode == 'switchable':
        layer = _add_reading_layer(writer)
        suffix = ' - Switchable Reading'
        subject = ('Original PDF text plus optional vector word-prefix emphasis. '
                   'Toggle the Bionic Reading layer in your reader.')
    else:
        layer = None
        suffix = ' - Bionic Reading'
        subject = 'Original PDF text plus always-visible vector word-prefix emphasis.'
    builder = OverlayBuilder(writer, layer, weight)
    total = len(writer.pages)
    for number, page in enumerate(writer.pages, 1):
        builder.build_page(page)
        if progress is not None:
            progress(number, total)
    if builder.count == 0:
        raise ValueError('未找到可处理的文字层或可用嵌入字体；扫描版需先做 OCR。')
    title = reader.metadata.title if reader.metadata else None
    writer.add_metadata({'/Title': str(title or source.stem) + suffix, '/Subject': subject})
    with TemporaryDirectory(dir=target.parent) as staging:
        temporary = Path(staging) / 'reading.pdf'
        writer.write(temporary)
        temporary.replace(target)
    return {
        'pages': total, 'glyphs': builder.count, 'glyph_forms': len(builder.glyphs.forms),
        'skipped_fonts': sorted(builder.text_reader.skipped_fonts | builder.glyphs.skipped_fonts),
        'mode': mode, 'locale': locale, 'seconds': time.monotonic() - started,
    }
