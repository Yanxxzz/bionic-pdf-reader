"""Complete partially searchable scans while retaining their authored text and reading order."""
from codecs import getincrementaldecoder
from contextlib import closing
from copy import copy
from ctypes import c_double, c_uint
from dataclasses import dataclass
from difflib import SequenceMatcher
from io import BytesIO
import re
import unicodedata

from pypdf import PdfReader
from pypdf._cmap import get_encoding
from pypdf.generic import (ArrayObject, ByteStringObject, ContentStream, DecodedStreamObject,
                           DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject)

from .document import bind_resource
from .pdf_text import GraphicsState, IDENTITY, font_width_lookup, matrix_multiply, translated


def _word_key(text):
    return unicodedata.normalize('NFKC', text).casefold()


def paints_text(obj):
    """A text object may select invisible text rendering or make its fill/stroke transparent."""
    from pypdfium2 import raw

    mode = raw.FPDFTextObj_GetTextRenderMode(obj)
    if mode in (3, 7):  # Invisible and clipping-only text draw no ink.
        return False
    rgba = [c_uint() for _ in range(4)]
    for modes, get_color in (((0, 2, 4, 6), raw.FPDFPageObj_GetFillColor),
                             ((1, 2, 5, 6), raw.FPDFPageObj_GetStrokeColor)):
        if mode in modes and (not get_color(obj, *rgba) or rgba[3].value):
            return True  # An unavailable paint color is conservatively treated as visible.
    return mode < 0  # Unknown rendering mode.


def existing_words(page, coords, *, mask_visible=None):
    """Read authored words in content order, optionally excluding their visible ink from OCR."""
    from pypdfium2 import raw

    result = []
    letters, boxes = [], []
    with closing(page.get_textpage()) as text:
        count = text.count_chars()
        for i in range(count + 1):
            char = chr(raw.FPDFText_GetUnicode(text, i)) if i < count else ' '
            if char.isspace() or char == '\x00':
                if letters:
                    result.append((_word_key(''.join(letters)), (min(p[0] for p in boxes), min(p[1] for p in boxes),
                                   max(p[0] for p in boxes), max(p[1] for p in boxes)), origin))
                    letters, boxes = [], []
                continue
            if not letters:
                x, y = c_double(), c_double()
                raw.FPDFText_GetCharOrigin(text, i, x, y)
                origin = x.value, y.value
            left, bottom, right, top = text.get_charbox(i)
            corners = coords.to_bitmap(left, bottom), coords.to_bitmap(right, top)
            if mask_visible is not None:
                obj = raw.FPDFText_GetTextObject(text, i)
                if obj and paints_text(obj):
                    mask_visible(*corners)
            letters.append(char)
            boxes.extend(corners)
    return result


def _covered(word, box, existing):
    left, top, right, bottom = box
    for i, (original, (x, y, r, b), _) in enumerate(existing):
        overlap_x = min(right, r) - max(left, x)
        overlap_y = min(bottom, b) - max(top, y)
        if overlap_x <= 0 or overlap_y <= 0:
            continue
        if word == original or (overlap_x >= .65*(right-left) and overlap_y >= .45*(bottom-top)):
            return i
    return None


def _before(box, other):
    left, top, right, bottom = box
    x, y, r, b = other
    if min(bottom, b) - max(top, y) >= .4 * min(bottom-top, b-y):
        return left + right < x + r
    return top + bottom < y + b


@dataclass(frozen=True)
class _Cut:
    """A byte boundary in an original text-show operation at this particular Form call."""
    path: tuple
    operation: int
    item: int
    offset: int
    transform: tuple
    line: tuple | None = None
    advance: float = 0


def _raw(item):
    return item.original_bytes if isinstance(item, TextStringObject) else item


def _decoded(data, encoding):
    if isinstance(encoding, dict):
        for i, code in enumerate(data):
            yield i, i+1, encoding.get(code, chr(code))
        return
    decoder = getincrementaldecoder(encoding)(errors='replace')
    start = 0
    for end in range(1, len(data)+1):
        char = decoder.decode(data[end-1:end], final=end == len(data))
        if char:
            yield start, end, char
            start = end


def _text_anchors(page, existing):
    """Match PDFium's words to their encoded glyphs, including words separated by TJ kerning."""
    letters, locations, fonts, starts, ends = [], [], {}, {}, {}
    spaced = set()

    def walk(stream, resources, state, path, ancestors):
        saved, text_object = [], None
        for index, (args, op) in enumerate(stream.operations):
            if op == b'q':
                saved.append(copy(state))
            elif op == b'Q' and saved:
                state = saved.pop()
            elif op == b'BT':
                text_object = (path, index)
                starts[text_object] = len(locations), _Cut(path, index, -1, 0, state.ctm)
                state.update(op, args, resources)
            elif op == b'ET':
                ends[text_object] = _Cut(path, index+1, -1, 0, state.ctm)
            elif op == b'Do':
                ref = resources.get('/XObject', DictionaryObject()).get_object().get(args[0])
                form = ref.get_object() if ref is not None else {}
                if form.get('/Subtype') == '/Form' and ref not in ancestors:
                    child = copy(state)
                    child.ctm = matrix_multiply(state.ctm, form.get('/Matrix', IDENTITY))
                    walk(ContentStream(form, page.pdf), form.get('/Resources', resources).get_object(),
                         child, path+(index,), ancestors | {ref})
            elif op in (b'Tj', b'TJ', b"'", b'"') and state.font is not None:
                state.update(op, args, resources)
                font = state.font.get_object()
                key = getattr(font, 'indirect_reference', None) or id(font)
                if key not in fonts:
                    fonts[key] = get_encoding(font)
                encoding, cmap = fonts[key]
                values = args[0] if op == b'TJ' else args[-1:]
                for item, value in enumerate(values):
                    data = _raw(value)
                    if isinstance(data, bytes):
                        for start, end, char in _decoded(data, encoding):
                            value = _word_key(''.join(cmap.get(c, c) for c in char))
                            for c in value:
                                if not c.isspace():
                                    letters.append(c)
                                    locations.append((path, index, item, start, state.ctm, state.line_matrix,
                                                      state.font_size * state.horizontal_scale, text_object))
                                elif locations:
                                    spaced.add(locations[-1])
            else:
                state.update(op, args, resources)

    walk(page.get_contents(), page['/Resources'], GraphicsState(), (), set())
    native = ''.join(word for word, _, _ in existing)
    drawn = ''.join(letters)
    if native == drawn:
        matched = locations
    else:
        matched = [None] * len(native)
        for a, b, n in SequenceMatcher(None, native, drawn, autojunk=False).get_matching_blocks():
            matched[a:a+n] = locations[b:b+n]

    def cut(pos, origin):
        if matched[pos] is not None:
            path, op, item, start, transform, line, scale, text_object = matched[pos]
            first, opening = starts[text_object]
            if matched[pos] is locations[first]:
                # Insert before the new BT moves to its native word (possibly on a later line).
                return opening
            # PDFium gives the original baseline position in page space, including TJ, Tc and Tw.
            # Restore Tlm explicitly, then advance Tm alone in the original font's text units.
            a,b,c,d,e,f = matrix_multiply(transform, line)
            det = a*d-b*c
            if det and scale:
                x,y = origin
                advance = -1000*((x-e)*d - (y-f)*c)/(det*scale)
                return _Cut(path, op, item, start, transform, line, advance)
        return None

    anchors, has_space, pos = [], set(), 0
    for index, (word, _, origin) in enumerate(existing):
        anchors.append(cut(pos, origin))
        pos += len(word)
        if matched[pos-1] in spaced:
            has_space.add(index)
    return anchors, ends.get(matched[-1][-1]) if matched[-1] else None, has_space


def _prepend_space(fragment, fonts):
    # Give the separator a physical glyph and logical text. Some readers discard a space
    # when the previous native font's advance overlaps the first OCR letter.
    (matrix, _), ((name, size), _), ((percent,), _), show = fragment
    font = fonts[name]
    if font.get('/Encoding') != '/Identity-H':
        return fragment
    args, op = show
    values = args[0] if op == b'TJ' else args
    for index, value in enumerate(values):
        data = _raw(value)
        if isinstance(data, bytes) and len(data) >= 2:
            break
    else:
        return fragment
    first = data.decode('utf-16-be')[0]
    offset = len(first.encode('utf-16-be'))
    actual = DictionaryObject({NameObject('/ActualText'): TextStringObject(' '+first)})
    head = ArrayObject([*values[:index], ByteStringObject(data[:offset])])
    rest = ArrayObject([ByteStringObject(data[offset:]), *values[index+1:]])
    width = font_width_lookup(font, True)(32)
    start = translated(matrix, -width * float(size) * float(percent) / 100000, 0)
    return [(_pdf_matrix(start), b'Tm'), *fragment[1:3], ([NameObject('/Span'), actual], b'BDC'),
            ([ByteStringObject(b'\x00 ')], b'Tj'), ([head], b'TJ'), ([], b'EMC'), ([rest], b'TJ')]


def _text_groups(text, hocr, page, existing):
    """Keep Tesseract's word encoding and positions. Group additions ahead of their next authored word."""
    if not existing:
        return {None: text.get_contents().operations} if hocr.find(".//*[@class='ocrx_word']") is not None else {}
    # Tesseract writes one TJ per hOCR word, positioned with Tm/Td rather than the previous word's advance.
    words = hocr.findall(".//*[@class='ocrx_word']")
    state = GraphicsState()
    font = None
    positioned = []
    for args, op in text.get_contents().operations:
        if op == b'Tf':
            font = args
        if op in (b'Tj', b'TJ'):
            if font is None:
                return {}
            positioned.append([([FloatObject(v) for v in state.line_matrix], b'Tm'), (font, b'Tf'),
                               ([FloatObject(100*state.horizontal_scale)], b'Tz'), (args, op)])
        else:
            state.update(op, args, text['/Resources'])
    if len(positioned) != len(words):
        return {}  # Cannot safely distinguish already-authored words in this Tesseract output.
    recognized, recognized_words = [], []
    for word, fragment in zip(words, positioned):
        box = re.search(r'\bbbox (\d+) (\d+) (\d+) (\d+)', word.get('title',''))
        if box is None:
            continue
        chars = word.findall(".//*[@class='ocrx_cinfo']")
        key = _word_key(''.join(''.join(c.itertext()) for c in chars))
        bounds = tuple(map(int, box.groups()))
        recognized.append((_covered(key, bounds, existing), bounds, fragment))
        recognized_words.append(word)
    covered = {old for old, _, _ in recognized}
    if None not in covered:
        return {}
    anchors, tail, has_space = _text_anchors(page, existing)
    # hOCR marks genuine word boundaries. A line break or a split inside an authored word
    # should never acquire a separator from the native-to-OCR transition.
    lines = {word: line for line in hocr.iterfind(".//*[@class='ocr_line']")
             for word in line.iterfind(".//*[@class='ocrx_word']")}
    for i in range(1, len(recognized)):
        previous = recognized[i-1][0]
        old, box, fragment = recognized[i]
        line = lines.get(recognized_words[i])
        if (old is None and previous is not None and previous not in has_space
                and line is not None and line is lines.get(recognized_words[i-1])):
            recognized[i] = (old, box, _prepend_space(fragment, text['/Resources']['/Font']))
    # Authored notes and corrections can have no OCR match. Keep them at their geometric position.
    extra = [(i, box) for i, (_, box, _) in enumerate(existing) if i not in covered and anchors[i] is not None]
    groups = {}
    next_old = len(existing)
    for old, box, fragment in reversed(recognized):
        if old is not None:
            next_old = old
            continue
        index = next((i for i, author_box in extra if i < next_old and _before(box, author_box)), next_old)
        anchor = anchors[index] if index < len(anchors) else tail
        groups.setdefault(anchor, []).append(fragment)
    result = {}
    for anchor, fragments in groups.items():
        ops = [op for part in reversed(fragments) for op in part]
        if anchor is not None and anchor != tail:
            # Tesseract omits the space after its final word. When authored text follows it,
            # retain a real word boundary even in extractors that ignore restored matrices.
            (font, _), (args, op) = fragments[0][1], fragments[0][-1]
            last = _raw(args[0][-1] if op == b'TJ' else args[0])
            if (text['/Resources']['/Font'][font[0]].get('/Encoding') == '/Identity-H'
                    and isinstance(last, bytes) and not last.endswith(b'\x00 ')):
                ops.append(([ByteStringObject(b'\x00 ')], b'Tj'))
        result[anchor] = ops
        if anchor is None:
            result[anchor] = [([], b'BT'), ([NumberObject(3)], b'Tr'), *result[anchor], ([], b'ET')]
    return result


def prepare_text(text_pdf, hocr, page, existing):
    text = PdfReader(BytesIO(text_pdf)).pages[0]
    groups = _text_groups(text, hocr, page, existing)
    return text, groups


def _validate_font(text):
    # Tesseract can exit successfully with an unresolved pdf.ttf symlink on Windows.
    for font in text['/Resources']['/Font'].values():
        for child in font.get_object().get('/DescendantFonts', ()):
            descriptor = child.get_object().get('/FontDescriptor')
            if descriptor and '/FontFile2' in descriptor.get_object():
                data = descriptor.get_object()['/FontFile2'].get_data()
                if data[:4] not in (b'\x00\x01\x00\x00', b'true', b'ttcf'):
                    raise ValueError('Tesseract 的 pdf.ttf 无效。请恢复语言数据目录里的实际字体文件后再导出。')


def _pdf_matrix(matrix):
    return [FloatObject(v) for v in matrix]


def _splice_show(operation, cuts):
    """Split only at matched glyph boundaries; every original byte and kerning adjustment is retained."""
    args, op = operation
    values = args[0] if op == b'TJ' else args[-1:]
    result, chunk = [], []
    if op == b'"':
        result.extend([([args[0]], b'Tw'), ([args[1]], b'Tc')])
    if op in (b"'", b'"'):
        result.append(([], b'T*'))
    for item, value in enumerate(values):
        if item not in cuts:
            chunk.append(value)
            continue
        raw = _raw(value)
        start = 0
        for end, extra in sorted(cuts[item], key=lambda c: c[0]):
            if end > start:
                chunk.append(ByteStringObject(raw[start:end]))
            if chunk:
                result.append(([ArrayObject(chunk)], b'TJ'))
                chunk = []
            result.extend(extra)
            start = end
        if start < len(raw):
            chunk.append(ByteStringObject(raw[start:]))
    if chunk:
        result.append(([ArrayObject(chunk)], b'TJ'))
    return result


def _inline_text(resources, fonts, cut, transform, fragment):
    # Keeping the OCR in the *same* text stream lets readers recognize word gaps and line breaks
    # across the seam. Some readers do not restore the text matrices across q/Q inside BT.
    zero = [NumberObject(0)]
    ops = [([], b'q'), ([NumberObject(3)], b'Tr'), (zero, b'Tc'), (zero, b'Tw'), (zero, b'Ts')]
    for args, op in fragment:
        if op == b'Tm':
            args = _pdf_matrix(matrix_multiply(transform, args))
        elif op == b'Tf':
            name = bind_resource(resources, '/Font', NameObject('/BROcrFont'), fonts.raw_get(args[0]))
            args = [name, args[1]]
        ops.append((args, op))
    if cut.line is None:
        return [([], b'BT'), *ops, ([], b'Q'), ([], b'ET')]
    ops.extend([([], b'Q'), (_pdf_matrix(cut.line), b'Tm')])
    if cut.advance:
        ops.append(([ArrayObject([FloatObject(cut.advance)])], b'TJ'))
    return ops


def _edit_stream(writer, original, resources, additions, fonts, replace_form):
    """Clone just the Form invocation being supplemented. Other calls retain the original."""
    ops = list(original.operations)
    children = {}
    local = {}
    for path, cut, transform, fragment in additions:
        if path:
            children.setdefault(path[0], []).append((path[1:], cut, transform, fragment))
            continue
        if not local and '/Font' in resources:
            resources[NameObject('/Font')] = DictionaryObject(resources['/Font'])
        items = local.setdefault(cut.operation, {})
        items.setdefault(cut.item, []).append((cut.offset, _inline_text(resources, fonts, cut, transform, fragment)))
    for index, child_edits in children.items():
        name = ops[index][0][0]
        source = resources['/XObject'][name]
        child_resources = DictionaryObject(source.get('/Resources', resources).get_object())
        if '/XObject' in child_resources:
            child_resources[NameObject('/XObject')] = DictionaryObject(child_resources['/XObject'])
        child = ContentStream(source, writer)
        painted = _edit_stream(writer, child, child_resources, child_edits, fonts, replace_form)
        for key, value in source.items():
            if key not in ('/Length','/Filter','/DecodeParms','/Resources'):
                painted[key] = value
        painted[NameObject('/Resources')] = child_resources
        fresh = bind_resource(resources, '/XObject', NameObject('/BROcrSource'), replace_form(source, painted))
        ops[index] = ([fresh], b'Do')
    for index in sorted(local, reverse=True):
        if -1 in local[index]:
            ops[index:index] = local[index][-1][0][1]
        else:
            ops[index:index+1] = _splice_show(ops[index], local[index])
    original.operations = ops
    output = DecodedStreamObject()
    output.set_data(original.get_data())
    return output.flate_encode()


def place_text(writer, page, matrix, text, groups, form_tags):
    _validate_font(text)
    form_matrix = (1/float(text.mediabox.width), 0, 0, 1/float(text.mediabox.height), 0, 0)
    resources = text['/Resources'].clone(writer)
    additions, trailing = [], []
    for anchor, fragment in groups.items():
        if anchor is None:
            content = ContentStream(None, text.pdf)
            content.operations = fragment
            form = DecodedStreamObject()
            form.set_data(content.get_data())
            form.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                         NameObject('/BBox'): text.mediabox.clone(writer), NameObject('/Resources'): resources})
            ref = writer._add_object(form.flate_encode())
            name = bind_resource(page['/Resources'], '/XObject', NameObject('/BROcrText'), ref)
            trailing.append(f'q {form_matrix[0]:.10f} 0 0 {form_matrix[3]:.10f} 0 0 cm {name} Do Q')
            continue
        a,b,c,d,e,f = anchor.transform
        det = a*d-b*c
        if det:
            inverse = (d/det, -b/det, -c/det, a/det, (c*f-d*e)/det, (b*e-a*f)/det)
            transform = matrix_multiply(inverse, matrix_multiply(matrix, form_matrix))
            additions.append((anchor.path, anchor, transform, fragment))
    if additions:
        def replace_form(source, edited):
            return form_tags.replace_painted(page.indirect_reference, source, edited)
        original = _edit_stream(writer, page.get_contents(), page['/Resources'], additions, resources['/Font'], replace_form)
        page[NameObject('/Contents')] = writer._add_object(original)
    return trailing
