"""Read positioned glyphs from PDF text and graphics operators."""
import math
import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from copy import copy
from dataclasses import dataclass
from io import BytesIO

from pypdf._cmap import get_encoding
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, NameObject, TextStringObject


IDENTITY = (1, 0, 0, 1, 0, 0)
STYLED_FONT = re.compile(r"bold|italic|oblique|black|heavy|demi|symbol|dingbat", re.I)
DEVICE_COLOR = {b'g': '/DeviceGray', b'rg': '/DeviceRGB', b'k': '/DeviceCMYK'}


def matrix_multiply(left, right):
    a, b, c, d, e, f = left
    g, h, i, j, k, l = right
    return (a*g + c*h, b*g + d*h, a*i + c*j, b*i + d*j, a*k + c*l + e, b*k + d*l + f)


def translated(matrix, x, y):
    a, b, c, d, e, f = matrix
    return (a, b, c, d, a*x + c*y + e, b*x + d*y + f)


@dataclass
class GraphicsState:
    ctm: tuple = IDENTITY
    text_matrix: tuple = IDENTITY
    line_matrix: tuple = IDENTITY
    position_known: bool = True
    font: str = ''
    font_size: float = 0
    char_spacing: float = 0
    word_spacing: float = 0
    horizontal_scale: float = 1
    rise: float = 0
    leading: float = 0
    fill_cs: str = '/DeviceGray'
    fill_values: tuple = (0,)
    render_mode: int = 0
    fill_alpha: float = 1
    stroke_alpha: float = 1
    paint_scope: int = 0

    def start_line(self, matrix):
        self.text_matrix = self.line_matrix = matrix
        self.position_known = True

    def update(self, op, args, resources):
        match op:
            case b'cm':
                self.ctm = matrix_multiply(self.ctm, tuple(map(float, args)))
            case b'BT':
                self.start_line(IDENTITY)
            case b'Tf':
                self.font, self.font_size = str(args[0]), float(args[1])
            case b'Tm':
                self.start_line(tuple(map(float, args)))
            case b'Td' | b'TD':
                x, y = map(float, args)
                if op == b'TD':
                    self.leading = -y
                self.start_line(translated(self.line_matrix, x, y))
            case b'T*' | b"'" | b'"':
                if op == b'"':
                    self.word_spacing, self.char_spacing = map(float, args[:2])
                self.start_line(translated(self.line_matrix, 0, -self.leading))
            case b'Tc':
                self.char_spacing = float(args[0])
            case b'Tw':
                self.word_spacing = float(args[0])
            case b'Tz':
                self.horizontal_scale = float(args[0]) / 100
            case b'Ts':
                self.rise = float(args[0])
            case b'TL':
                self.leading = float(args[0])
            case b'Tr':
                self.render_mode = int(args[0])
            case b'g' | b'rg' | b'k':
                self.fill_cs, self.fill_values = DEVICE_COLOR[op], tuple(args)
            case b'cs':
                self.fill_cs, self.fill_values = str(args[0]), (0,)
            case b'sc' | b'scn':
                self.fill_values = tuple(args)
            case b'gs':
                entry = resources.get('/ExtGState', {}).get(args[0])
                if entry:
                    entry = entry.get_object()
                    self.fill_alpha = float(entry.get('/ca', self.fill_alpha))
                    self.stroke_alpha = float(entry.get('/CA', self.stroke_alpha))

    def can_emphasize(self):
        size = abs(self.font_size) * math.hypot(self.text_matrix[2], self.text_matrix[3])
        return (self.position_known and self.render_mode == 0 and 6.8 <= size <= 24
                and self.fill_alpha == self.stroke_alpha == 1 and self.fill_cs != '/Pattern'
                and all(abs(skew) < 1e-5 for skew in (*self.text_matrix[1:3], *self.ctm[1:3])))


def character_map(font, cid):
    encoding, cmap = get_encoding(font)
    if cid:
        return {ord(k): v for k, v in cmap.items() if isinstance(k, str) and len(k) == 1}
    if cmap.get(-1, 1) != 1:
        return {}
    characters = []
    for code in range(256):
        if isinstance(encoding, dict):
            letter = encoding.get(code, chr(code))
        else:
            try:
                letter = bytes([code]).decode(encoding, errors='replace')
            except (LookupError, UnicodeError):
                letter = chr(code)
        characters.append(''.join(cmap.get(char, char) for char in letter))
    return characters


def font_width_lookup(font, cid):
    if not cid:
        first = int(font.get('/FirstChar', 0))
        widths = font['/Widths'] if '/Widths' in font else ()
        return lambda code: float(widths[code - first]) if first <= code < first + len(widths) else 0

    descendant = font['/DescendantFonts'][0].get_object()
    entries = iter(descendant['/W'] if '/W' in descendant else ())
    starts = [0]
    runs = [(0, float(descendant.get('/DW', 1000)))]
    try:
        for first in entries:
            first = int(first)
            value = next(entries).get_object()
            if isinstance(value, ArrayObject):
                stop = first + len(value)
            else:
                stop = int(value) + 1
                value = float(next(entries).get_object())
            start, stop = max(first, 0), min(stop, 0x10000)  # Identity-H uses two-byte codes.
            if start >= stop:
                continue
            left, right = bisect_left(starts, start), bisect_right(starts, stop)
            # Later declarations override only [start, stop). Resume the old run at stop.
            runs[left:right] = [(first, value), runs[right - 1]]
            starts[left:right] = [start, stop]
    except StopIteration:
        raise ValueError('PDF 字体的字宽表不完整。') from None

    def width_for(code):
        first, value = runs[bisect_right(starts, code) - 1]
        return float(value[code - first]) if isinstance(value, ArrayObject) else value

    return width_for


@dataclass
class TextFont:
    code_size: int
    styled: bool
    characters: list | dict
    width_for: Callable[[int], float]

    @classmethod
    def from_pdf(cls, font):
        subtype = font.get('/Subtype')
        cid = subtype == '/Type0' and str(font.get('/Encoding')) == '/Identity-H'
        if not cid and subtype not in ('/Type1', '/TrueType'):
            return None
        styled = bool(STYLED_FONT.search(str(font.get('/BaseFont', ''))))
        characters = {} if styled else character_map(font, cid)
        return cls(code_size=2 if cid else 1, styled=styled, characters=characters,
                   width_for=font_width_lookup(font, cid))

    def text_for(self, code):
        if isinstance(self.characters, list):
            return self.characters[code]
        return self.characters.get(code, '')


def marked_content(args, index, resources):
    properties = args[1] if len(args) > 1 else None
    layer = properties if args[0] == '/OC' else None
    if isinstance(properties, NameObject):
        properties = resources.get('/Properties', {}).get(properties)
    if properties is not None:
        properties = properties.get_object()
    text = properties.get('/ActualText') if isinstance(properties, DictionaryObject) else None
    actual = {'id': index, 'text': str(text)} if text is not None else None
    return layer, actual


class _TextOperations(list):
    """Record actual BT byte positions while pypdf tokenizes the original content."""

    def __init__(self, data, pdf):
        super().__init__()
        self.starts = {}
        with BytesIO(data) as self._cursor:
            parser = ContentStream(None, pdf)
            parser._operations = self
            parser._parse_content_stream(self._cursor)

    def append(self, operation):
        if operation[1] == b'BT':
            self.starts[len(self)] = self._cursor.tell() - len(b'BT')
        super().append(operation)


class PageTextReader:
    """Share decoded fonts across pages and keep drawing state local to each page."""
    def __init__(self):
        self.fonts = {}
        self.skipped_fonts = set()

    def read(self, content, resources):
        data = content.get_data()
        operations = _TextOperations(data, content.pdf)
        state = GraphicsState()
        saved, marked, records = [], [], []
        anchor = None
        for index, (args, op) in enumerate(operations):
            if op == b'q':
                # Inside a text object this includes both text matrices (ISO 32000-2 §9.4.1).
                saved.append(copy(state))
            elif op == b'Q':
                if saved:
                    state = saved.pop()
            elif op in (b'BDC', b'BMC'):
                marked.append((index, *marked_content(args, index, resources)))
            elif op == b'EMC':
                if marked:
                    marked.pop()
            else:
                state.update(op, args, resources)
                if op == b'BT':
                    anchor = (operations.starts[index], state.ctm, state.paint_scope, index)
                elif op == b'ET':
                    anchor = None
                elif op in (b'gs', b'W', b'W*'):
                    state.paint_scope = index + 1
                elif anchor is not None and op in (b'Tj', b'TJ', b"'", b'"'):
                    values = args[0] if op == b'TJ' else args[-1:]
                    records.extend(self._show_text(values, state, resources, marked, anchor))
        return data, records

    def _show_text(self, values, state, resources, marked, anchor):
        reference = resources.get('/Font', {}).get(state.font)
        if reference is None:
            state.position_known = False
            return
        font = reference.get_object()
        key = getattr(font, 'indirect_reference', None) or id(font)
        if key not in self.fonts:
            self.fonts[key] = TextFont.from_pdf(font)
        metrics = self.fonts[key]
        if metrics is None:
            self.skipped_fonts.add(str(font.get('/BaseFont', 'unknown')))
            state.position_known = False
            return

        text_start, initial_ctm, initial_scope, start_index = anchor
        layers = tuple(layer for index, layer, _ in marked if index > start_index and layer is not None)
        # Strokes are painted immediately before BT. An inner mask/clip cannot be lifted outside it.
        eligible = (not metrics.styled and state.can_emphasize()
                    and state.ctm == initial_ctm and state.paint_scope == initial_scope
                    and all(isinstance(layer, NameObject) for layer in layers))
        actual = next((text for _, _, text in marked if text is not None), None)
        size, scale = state.font_size, state.horizontal_scale
        for item in values:
            if isinstance(item, TextStringObject):
                raw = item.original_bytes
            elif isinstance(item, bytes):
                raw = item
            else:  # A number in a TJ array adjusts the position of the next glyph.
                adjustment = -float(item) * size * scale / 1000
                state.text_matrix = translated(state.text_matrix, adjustment, 0)
                continue
            for start in range(0, len(raw), metrics.code_size):
                code = int.from_bytes(raw[start:start + metrics.code_size], 'big')
                width = metrics.width_for(code)
                word_spacing = state.word_spacing if code == 32 else 0
                advance = (width * size / 1000 + state.char_spacing + word_spacing) * scale
                local = translated(state.text_matrix, 0, state.rise)
                matrix = matrix_multiply(state.ctm, local)
                yield {
                    'font': font, 'code': code, 'text': metrics.text_for(code),
                    'x': min(matrix[4], matrix[4] + matrix[0] * advance),
                    'y': matrix[5], 'w': abs(matrix[0] * advance), 'h': abs(size * matrix[3]),
                    'text_matrix': local, 'text_start': text_start, 'tz': scale, 'size': size, 'actual': actual,
                    'eligible': eligible, 'oc': layers, 'cs': state.fill_cs, 'color': state.fill_values,
                }
                state.text_matrix = translated(state.text_matrix, advance, 0)
