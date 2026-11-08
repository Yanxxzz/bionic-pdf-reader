"""Complete partially searchable scans while retaining their authored text and reading order."""
from contextlib import closing
from dataclasses import dataclass
from difflib import SequenceMatcher
from io import BytesIO
import re
import unicodedata

from pypdf import PdfReader
from pypdf.generic import (ContentStream, DecodedStreamObject, DictionaryObject,
                           FloatObject, NameObject, NumberObject)

from .document import bind_resource
from .pdf_text import GraphicsState, IDENTITY, matrix_multiply


def _word_key(text):
    return unicodedata.normalize('NFKC', text).casefold()


def existing_words(page, coords):
    """Read authored words in content order, with boxes in the OCR bitmap."""
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
                                   max(p[0] for p in boxes), max(p[1] for p in boxes))))
                    letters, boxes = [], []
                continue
            left, bottom, right, top = text.get_charbox(i)
            letters.append(char)
            boxes.extend((coords.to_bitmap(left, bottom), coords.to_bitmap(right, top)))
    return result


def _covered(word, box, existing):
    left, top, right, bottom = box
    for i, (original, (x, y, r, b)) in enumerate(existing):
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


@dataclass
class _SourceStream:
    path: tuple
    resources: DictionaryObject
    transform: tuple
    anchor: tuple | None = None
    index: int = -1


def _text_anchors(page, existing):
    """Find safe insertion points at the original Form or start of a positioned line."""
    groups = []
    stack = [_SourceStream((), page['/Resources'], IDENTITY)]
    def before(op, args, cm, tm):
        source = stack[-1]
        source.index += 1
        transform = matrix_multiply(source.transform, cm)
        if op in (b'BT', b'Do'):
            source.anchor = (source.path, source.index, transform, None)
        if op == b'Do':
            forms = source.resources.get('/XObject', DictionaryObject()).get_object()
            form = forms.get(args[0])
            form = form.get_object() if form is not None else {}
            stack.append(_SourceStream(source.path+(source.index,), form.get('/Resources', source.resources),
                                       matrix_multiply(transform, form.get('/Matrix', IDENTITY)), source.anchor))
    def after(op, args, cm, tm):
        source = stack[-1]
        if op == b'Do':
            stack.pop()
        elif op in (b'Tm', b'Td', b'TD', b'T*'):
            # These operators set the text matrix and text line matrix to the same value.
            # Both can be restored with a single Tm when resuming the original text object.
            source.anchor = (source.path, source.index+1, matrix_multiply(source.transform, cm), tuple(tm))
    def visit(text, cm, tm, font, size):
        groups.extend((_word_key(word), stack[-1].anchor) for word in text.split())
    page.extract_text(visitor_operand_before=before, visitor_operand_after=after, visitor_text=visit)
    matcher = SequenceMatcher(None, [text for text, _ in existing], [text for text, _ in groups], autojunk=False)
    anchors = [None] * len(existing)
    for a, b, n in matcher.get_matching_blocks():
        anchors[a:a+n] = [anchor for _, anchor in groups[b:b+n]]
    return anchors


def _text_groups(text, hocr, page, existing):
    """Keep Tesseract's word encoding and positions. Group additions ahead of their next authored word."""
    if not existing:
        return {None: text.get_contents().get_data()} if hocr.find(".//*[@class='ocrx_word']") is not None else {}
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
    anchors = _text_anchors(page, existing)
    recognized = []
    for word, fragment in zip(words, positioned):
        box = re.search(r'\bbbox (\d+) (\d+) (\d+) (\d+)', word.get('title',''))
        if box is None:
            continue
        chars = word.findall(".//*[@class='ocrx_cinfo']")
        key = _word_key(''.join(''.join(c.itertext()) for c in chars))
        bounds = tuple(map(int, box.groups()))
        recognized.append((_covered(key, bounds, existing), bounds, fragment))
    covered = {old for old, _, _ in recognized}
    # Authored notes and corrections can have no OCR match. Keep them at their geometric position.
    extra = [(i, box) for i, (_, box) in enumerate(existing) if i not in covered and anchors[i] is not None]
    groups = {}
    next_old = len(existing)
    for old, box, fragment in reversed(recognized):
        if old is not None:
            next_old = old
            continue
        index = next((i for i, author_box in extra if i < next_old and _before(box, author_box)), next_old)
        anchor = anchors[index] if index < len(anchors) else None
        groups.setdefault(anchor, []).append(fragment)
    result = {}
    for anchor, fragments in groups.items():
        filtered = ContentStream(None, text.pdf)
        filtered.operations = [([], b'BT'), ([NumberObject(3)], b'Tr'),
                               *(op for part in reversed(fragments) for op in part), ([], b'ET')]
        result[anchor] = filtered.get_data()
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


def _edit_stream(writer, original, resources, additions, replace_form):
    """Clone just the Form invocation being supplemented. Other calls retain the original."""
    ops = list(original.operations)
    children = {}
    local = []
    for path, index, matrices, resume, form in additions:
        if path:
            children.setdefault(path[0], []).append((path[1:], index, matrices, resume, form))
            continue
        name = bind_resource(resources, '/XObject', NameObject('/BROcrText'), form)
        extra = [([], b'q'), *[(_pdf_matrix(m), b'cm') for m in matrices], ([name], b'Do'), ([], b'Q')]
        if resume is not None:
            extra = [([], b'ET'), *extra, ([], b'BT'), (_pdf_matrix(resume), b'Tm')]
        local.append((index, extra))
    for index, child_edits in children.items():
        name = ops[index][0][0]
        source = resources['/XObject'][name]
        child_resources = DictionaryObject(source.get('/Resources', resources).get_object())
        if '/XObject' in child_resources:
            child_resources[NameObject('/XObject')] = DictionaryObject(child_resources['/XObject'])
        child = ContentStream(source, writer)
        painted = _edit_stream(writer, child, child_resources, child_edits, replace_form)
        for key, value in source.items():
            if key not in ('/Length','/Filter','/DecodeParms','/Resources'):
                painted[key] = value
        painted[NameObject('/Resources')] = child_resources
        fresh = bind_resource(resources, '/XObject', NameObject('/BROcrSource'), replace_form(source, painted))
        ops[index] = ([fresh], b'Do')
    for index, extra in sorted(local, reverse=True):
        ops[index:index] = extra
    original.operations = ops
    output = DecodedStreamObject()
    output.set_data(original.get_data())
    return output.flate_encode()


def place_text(writer, page, matrix, text, groups, form_tags):
    _validate_font(text)
    form_matrix = (1/float(text.mediabox.width), 0, 0, 1/float(text.mediabox.height), 0, 0)
    resources = text['/Resources'].clone(writer)
    additions, trailing = [], []
    for anchor, data in groups.items():
        form = DecodedStreamObject()
        form.set_data(data)
        form.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                     NameObject('/BBox'): text.mediabox.clone(writer), NameObject('/Resources'): resources})
        ref = writer._add_object(form.flate_encode())
        if anchor is None:
            name = bind_resource(page['/Resources'], '/XObject', NameObject('/BROcrText'), ref)
            trailing.append(f'q {form_matrix[0]:.10f} 0 0 {form_matrix[3]:.10f} 0 0 cm {name} Do Q')
            continue
        path, index, (a,b,c,d,e,f), resume = anchor
        det = a*d-b*c
        if det:
            inverse = (d/det, -b/det, -c/det, a/det, (c*f-d*e)/det, (b*e-a*f)/det)
            additions.append((path, index, (inverse, matrix, form_matrix), resume, ref))
    if additions:
        def replace_form(source, edited):
            return form_tags.replace_painted(page.indirect_reference, source, edited)
        original = _edit_stream(writer, page.get_contents(), page['/Resources'], additions, replace_form)
        page[NameObject('/Contents')] = writer._add_object(original)
    return trailing
