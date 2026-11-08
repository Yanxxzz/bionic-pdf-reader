"""Document-level checks and navigation for reading copies."""
import re

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject, NumberObject, TextStringObject

from .tagged import copy_structure


def bind_resource(resources, group, preferred, reference):
    """Bind a resource without displacing one used by the original document."""
    entries = resources.setdefault(NameObject(group), DictionaryObject()).get_object()
    name = preferred
    suffix = 1
    while name in entries and entries.raw_get(name) != reference:
        name = NameObject(f'{preferred}_{suffix}')
        suffix += 1
    entries[name] = reference
    return name


class SignatureLossError(ValueError):
    message = '这份 PDF 已有数字签名。导出阅读副本会使副本中的原签名失效。请保留原件用于验签。'

    def __init__(self):
        super().__init__(self.message)


def has_signature(reader):
    def signed(value):
        value = value.get_object()
        return (isinstance(value, DictionaryObject) and '/ByteRange' in value
                and bool(value.get('/Contents')) and any(value['/ByteRange']))

    catalog = reader.root_object
    permissions = catalog.get('/Perms', DictionaryObject()).get_object()
    if isinstance(permissions, DictionaryObject) and any(signed(value) for value in permissions.values()):
        return True
    form = catalog.get('/AcroForm', DictionaryObject()).get_object()
    if not isinstance(form, DictionaryObject) or '/Fields' not in form:
        return False
    pending = list(form['/Fields'])
    visited = set()
    while pending:
        field = pending.pop().get_object()
        if not isinstance(field, DictionaryObject) or id(field) in visited:
            continue
        visited.add(id(field))
        if '/V' in field and signed(field['/V']):
            return True
        if '/Kids' in field:
            pending.extend(field['/Kids'])
    return False


class PageSelectionError(ValueError):
    """The requested physical page numbers cannot be exported."""


def page_indices(pages, total):
    if pages is None:
        return range(total)

    def index(number):
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= total:
            raise PageSelectionError(f'页码必须是 1 到 {total} 之间的整数。')
        return number - 1

    if isinstance(pages, str):
        indices = []
        for part in re.split('[,，]', pages):
            match = re.fullmatch(r'\s*([0-9]+)(?:\s*[-–]\s*([0-9]+))?\s*', part)
            if not match:
                raise PageSelectionError('页码格式有误，例如 1-3,7,5-4。')
            first = index(int(match[1]))
            last = index(int(match[2])) if match[2] else first
            step = 1 if first <= last else -1
            indices.extend(range(first, last + step, step))
    else:
        indices = [index(number) for number in pages]
    if not indices:
        raise PageSelectionError('请至少选择一页。')
    return indices


def copy_pages(reader, indices, *, projected_forms=None):
    total = len(reader.pages)
    if indices == range(total) or (len(indices) == total and all(i == page for i, page in enumerate(indices))):
        return PdfWriter(clone_from=reader)

    writer = PdfWriter()
    writer.append(reader, pages=indices)  # Remap destinations and keep bookmarks for included pages.
    catalog = reader.root_object
    for key in ('/OCProperties', '/Lang', '/MarkInfo', '/Version'):
        if key in catalog:
            writer.root_object[NameObject(key)] = catalog[key].clone(writer)
    if '/PageLabels' in catalog:
        labels = reader.page_labels
        nums = ArrayObject()
        for position, index in enumerate(indices):
            nums.extend((NumberObject(position), DictionaryObject({NameObject('/P'): TextStringObject(labels[index])})))
        writer.root_object[NameObject('/PageLabels')] = DictionaryObject({NameObject('/Nums'): nums})

    # pypdf puts remapped annotations on the last instance of a repeated page.
    last = {index: i for i, index in enumerate(indices)}
    for i, index in enumerate(indices):
        if i == last[index]:
            continue
        original = writer.pages[last[index]]
        if '/Annots' in original:
            page = writer.pages[i]
            annotations = {}
            for ref in original['/Annots']:
                annotation = DictionaryObject(ref.get_object())
                annotation[NameObject('/P')] = page.indirect_reference
                annotations[ref] = writer._add_object(annotation)
            for ref in annotations.values():
                annotation = ref.get_object()
                for key in ('/Popup', '/Parent', '/IRT'):
                    target = annotation.get(key)
                    if isinstance(target, IndirectObject) and target in annotations:
                        annotation[NameObject(key)] = annotations[target]
            page[NameObject('/Annots')] = ArrayObject(annotations.values())
    if '/StructTreeRoot' in catalog:
        copy_structure(reader, writer, indices, projected_forms)
    return writer
