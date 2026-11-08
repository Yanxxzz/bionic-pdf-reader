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
from pypdf import PdfReader
from pypdf.generic import (ArrayObject as A, DictionaryObject as D, NameObject as N,
    FloatObject as F, TextStringObject as T,
    DecodedStreamObject)
from .embedded_font import EmbeddedFont
from .document import SignatureLossError, copy_pages, has_signature
from .pdf_text import GraphicsState, PageTextReader, matrix_multiply
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


def _edited_stream(data, edits):
    parts = []
    cursor = 0
    for start, end, replacement in sorted(edits):
        parts.extend((data[cursor:start], replacement))
        cursor = end
    parts.append(data[cursor:])
    stream = DecodedStreamObject()
    stream.set_data(b''.join(parts))
    return stream.flate_encode()


class OverlayBuilder:
    def __init__(self, writer, layer, weight, rule):
        self.writer, self.layer = writer, layer
        self.rule = rule
        self.text_reader = PageTextReader(writer)
        self.glyphs = GlyphLibrary(writer, weight)
        self.count = 0
        self.has_text = False

    def build_page(self, page):
        content = page.get_contents()
        if content is not None:
            result = self._build_stream(content, page.get('/Resources', D()), GraphicsState(), set())
            if result:
                stream, resources = result
                page[N('/Contents')] = self.writer._add_object(stream)
                page[N('/Resources')] = resources
                return True
        return False

    def _build_stream(self, content, original_resources, state, ancestors):
        # Each invocation can inherit a different colour, font or opacity. Edit only its copy.
        resources = D(original_resources.get_object())
        for group in ('/XObject', '/Properties'):
            if group in resources:
                resources[N(group)] = D(resources[group])
        data, records, forms = self.text_reader.read(content, resources, state)
        self.has_text |= bool(records)
        edits = []
        for (start, end), form, child in forms:
            key = id(form)
            if key in ancestors:
                continue
            child_resources = form.get('/Resources', original_resources)
            # A named colour selected in the caller may have a different binding in this Form.
            if child.fill_cs not in ('/DeviceGray', '/DeviceRGB', '/DeviceCMYK'):
                parent_cs = resources.get('/ColorSpace', {}).get(child.fill_cs)
                if child_resources.get('/ColorSpace', {}).get(child.fill_cs) != parent_cs:
                    child.fill_cs = '/Pattern'
            result = self._build_stream(form, child_resources, child, ancestors | {key})
            if result is None:
                continue
            edited, local_resources = result
            for field, value in form.items():
                if field not in ('/Length', '/DL', '/Filter', '/DecodeParms', '/F', '/FFilter', '/FDecodeParms', '/Resources'):
                    edited[field] = value
            edited[N('/Resources')] = local_resources
            name = _bind_resource(resources, '/XObject', N(f'/BRForm{start}'), self.writer._add_object(edited))
            edits.append((start, end, f'\n{name} Do'.encode('ascii')))
        strokes = self._strokes(records, resources)
        if strokes:
            begin, end = '\n', '\n'
            if self.layer is not None:
                tag = _bind_resource(resources, '/Properties', N('/BRBionic'), self.layer)
                begin, end = f'\n/OC {tag} BDC\n', '\nEMC\n'
            for offset, commands in strokes.items():
                edits.append((offset, offset, (begin + '\n'.join(commands) + end).encode('ascii')))
        if edits:
            return _edited_stream(data, edits), resources
        return None

    def _strokes(self, records, resources):
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
        return strokes


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
             progress: Callable[[int, int], None] | None = None, allow_signature_loss=False):
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
    if not allow_signature_loss and has_signature(reader):
        raise SignatureLossError()
    source_layers = reader.root_object.get('/OCProperties')
    if source_layers is not None:
        groups = source_layers.get_object().get('/OCGs', A()).get_object()
        if any(group.get_object().get('/Name') == LAYER_NAME for group in groups):
            raise ValueError('这份 PDF 已包含仿生开关，请直接在 WPS 中切换，或选择原始 PDF。')

    writer = copy_pages(reader, pages)
    writer.pdf_header = b'%PDF-1.6'
    if locale != 'auto':
        writer.root_object[N('/Lang')] = T(locale)

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
    unemphasized = []
    for number, page in enumerate(writer.pages, 1):
        if not builder.build_page(page):
            unemphasized.append(number)
        if progress is not None:
            progress(number, total)
    if builder.count == 0:
        if builder.glyphs.skipped_fonts or builder.text_reader.skipped_fonts:
            reason = '已读取文字，但没有可用于加粗的嵌入字体。'
        elif builder.has_text:
            reason = '已读取文字，当前规则没有选中可加粗的词首。'
        else:
            reason = '未找到可处理的文字层。如果页面是扫描图片，请先做 OCR。'
        raise ValueError(reason + page_summary(unemphasized))
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
        'unemphasized_pages': unemphasized,
        'skipped_fonts': sorted(builder.text_reader.skipped_fonts | builder.glyphs.skipped_fonts),
        'mode': mode, 'locale': locale, 'seconds': time.monotonic() - started,
    }


def page_summary(numbers):
    """Display physical output page numbers in compact inclusive ranges."""
    ranges = []
    for number in numbers:
        if ranges and ranges[-1][1] + 1 == number:
            ranges[-1][1] = number
        else:
            ranges.append([number, number])
    labels = [str(a) if a == b else f'{a}–{b}' for a, b in ranges]
    return '未加粗的页码（按副本顺序）：' + ('、'.join(labels) or '无') + '。'
