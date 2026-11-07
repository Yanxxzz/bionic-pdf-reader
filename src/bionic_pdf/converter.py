"""Create a WPS-switchable reading copy with one optional vector stroke layer.

Original PDF text remains the only text. Embedded glyph outlines are reused as
vector Form XObjects; no duplicate text or rasterized pages are introduced.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from fontTools.pens.basePen import BasePen
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject as A, DictionaryObject as D, NameObject as N,
    FloatObject as F, TextStringObject as T,
    DecodedStreamObject)
from .embedded_font import EmbeddedFont
from .pdf_text import PageTextReader, matrix_multiply
from .layout import select_glyphs
from .words import LANGUAGES


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

    def glyph(self, font, code, text):
        font_key = getattr(font, 'indirect_reference', None) or id(font)
        if font_key not in self.fonts:
            self.fonts[font_key] = EmbeddedFont.from_pdf(font)
        embedded = self.fonts[font_key]
        if embedded is None:
            self.skipped_fonts.add(str(font.get('/BaseFont')))
            return None
        name = embedded.glyph_name(code, text)
        if name is None:
            return None
        key = (font_key, name)
        if key not in self.forms:
            pen = PathPen(embedded.glyphs)
            embedded.glyphs[name].draw(pen)
            if not pen.commands: return None
            # Width is in the glyph's units, so all text sizes share this form.
            em_scale = max(abs(embedded.matrix[0]), abs(embedded.matrix[3]))
            line_width = self.weight / em_scale
            content = ('q ' + num(line_width) + ' w 1 j 1 J [] 0 d\n' + '\n'.join(pen.commands) + '\nS Q\n').encode('ascii')
            form = DecodedStreamObject()
            form.set_data(content)
            x0,y0,x1,y1 = embedded.bbox
            form.update({N('/Type'): N('/XObject'), N('/Subtype'): N('/Form'),
                N('/BBox'): A(F(x) for x in (x0-line_width,y0-line_width,x1+line_width,y1+line_width)),
                N('/Resources'): D()})
            self.forms[key] = (N('/BRGlyph' + str(len(self.forms))), self.writer._add_object(form.flate_encode()))
        name, reference = self.forms[key]
        return name, reference, embedded.matrix


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


def _page_stream_with_strokes(data, strokes, layer_tag):
    """Insert strokes before their text objects without re-encoding any source bytes."""
    begin, end = b'\n', b'\n'
    if layer_tag is not None:
        begin, end = f'\n/OC {layer_tag} BDC\n'.encode('ascii'), b'\nEMC\n'
    parts = []
    cursor = 0
    for offset in sorted(strokes):
        commands = '\n'.join(strokes[offset]).encode('ascii')
        parts.extend((data[cursor:offset], begin, commands, end))
        cursor = offset
    parts.append(data[cursor:])
    stream = DecodedStreamObject()
    stream.set_data(b''.join(parts))
    return stream.flate_encode()


class OverlayBuilder:
    def __init__(self, writer, layer, weight, rule):
        self.writer, self.layer = writer, layer
        self.rule = rule
        self.text_reader = PageTextReader()
        self.glyphs = GlyphLibrary(writer, weight)
        self.count = 0

    def build_page(self, page):
        content = page.get_contents()
        if content is None:
            return
        resources = page.get('/Resources', D())
        data, records = self.text_reader.read(content, resources)
        strokes, glyph_names = {}, {}
        for index in sorted(select_glyphs(records, self.rule)):
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
            transform = matrix_multiply(record['text_matrix'], matrix_multiply(scale, font_matrix))
            matrix = ' '.join(map(num, transform))
            color = ' '.join(map(str, record['color']))
            color_space = N(record['cs']).renumber().decode('ascii')
            draw = f"q {matrix} cm {color_space} CS {color} SCN {name} Do Q"
            layers = record['oc']
            open_layers = ''.join(f'/OC {tag.renumber().decode("ascii")} BDC ' for tag in layers)
            strokes.setdefault(record['text_start'], []).append(open_layers + draw + ' EMC' * len(layers))
            self.count += 1
        if not strokes:
            return
        layer_tag = None
        if self.layer is not None:
            layer_tag = _bind_resource(resources, '/Properties', N('/BRBionic'), self.layer)
        # Do not mutate the source stream: pages can share it but use different resources.
        stream = _page_stream_with_strokes(data, strokes, layer_tag)
        page[N('/Contents')] = self.writer._add_object(stream)


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
    if locale != 'auto' and locale not in LANGUAGES:
        raise ValueError(f'不支持的文档语言：{locale}')
    if source.resolve() == target.resolve():
        raise ValueError('请为阅读副本选择不同文件名，不能覆盖原 PDF。')
    reader = PdfReader(source)
    if reader.is_encrypted:
        raise ValueError('这份 PDF 已加密。制作工具无法保留原有密码和权限，已停止导出。')
    source_layers = reader.root_object.get('/OCProperties')
    if source_layers is not None:
        groups = source_layers.get_object().get('/OCGs', A()).get_object()
        if any(group.get_object().get('/Name') == LAYER_NAME for group in groups):
            raise ValueError('这份 PDF 已包含仿生开关，请直接在 WPS 中切换，或选择原始 PDF。')

    writer = PdfWriter(clone_from=reader) if pages is None else PdfWriter()
    writer.pdf_header = b'%PDF-1.6'
    if pages is not None:
        source_pages = reader.pages
        page_count = len(source_pages)
        for number in pages:
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= page_count:
                raise ValueError(f'页码必须是 1 到 {page_count} 之间的整数。')
            writer.add_page(source_pages[number - 1])
        if not writer.pages:
            raise ValueError('请至少选择一页。')
        # Page resources refer to layers whose controls live in the document catalog.
        if source_layers is not None:
            writer.root_object[N('/OCProperties')] = source_layers.clone(writer)

    if locale != 'auto':
        writer.root_object[N('/Lang')] = T(locale)
    elif pages is not None and '/Lang' in reader.root_object:
        writer.root_object[N('/Lang')] = reader.root_object['/Lang'].clone(writer)

    if mode == 'switchable':
        layer = _add_reading_layer(writer)
        suffix = ' - Switchable Reading'
        subject = ('Original PDF text plus optional vector word-prefix emphasis. '
                   'Toggle the Bionic Reading layer in your reader.')
    else:
        layer = None
        suffix = ' - Bionic Reading'
        subject = 'Original PDF text plus always-visible vector word-prefix emphasis.'
    builder = OverlayBuilder(writer, layer, weight, 'reference' if locale == 'en' else 'half')
    total = len(writer.pages)
    for number, page in enumerate(writer.pages, 1):
        builder.build_page(page)
        if progress is not None:
            progress(number, total)
    if builder.count == 0:
        raise ValueError('未找到可处理的文字层或可用嵌入字体；扫描版需先做 OCR。')
    title = reader.metadata.title if reader.metadata else None
    writer.add_metadata({'/Title': str(title or source.stem) + suffix, '/Subject': subject})
    # Drop replaced page streams only when no other page, Form or resource uses them.
    writer.compress_identical_objects(remove_duplicates=False, remove_unreferenced=True)
    with TemporaryDirectory(dir=target.parent) as staging:
        temporary = Path(staging) / 'reading.pdf'
        writer.write(temporary)
        temporary.replace(target)
    return {
        'pages': total, 'glyphs': builder.count, 'glyph_forms': len(builder.glyphs.forms),
        'skipped_fonts': sorted(builder.text_reader.skipped_fonts | builder.glyphs.skipped_fonts),
        'mode': mode, 'locale': locale, 'seconds': time.monotonic() - started,
    }
