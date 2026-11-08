"""Document-level checks and navigation for reading copies."""
import re

from pypdf import PdfWriter
from pypdf.constants import FieldDictionaryAttributes
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


def _separate_widget(writer, reference):
    """Keep the field's identity in the field tree and give its page a separate widget."""
    field = reference.get_object()
    if field.get('/Subtype') != '/Widget':
        return reference
    if '/Parent' in field and '/T' not in field and field['/Parent'].get_inherited('/FT') is not None:
        return reference
    # A merged terminal field contains both the field settings and the visual annotation.
    field_keys = ('/FT', '/Parent', '/T', '/TU', '/TM', '/Ff', '/V', '/DV', '/AA', '/DA',
                  '/Q', '/DS', '/RV', '/MaxLen', '/Opt', '/TI', '/I', '/Lock', '/SV')
    widget = DictionaryObject({key: field.pop(key) for key in list(field) if key not in field_keys})
    if '/AA' in field:
        actions = field.pop('/AA').get_object()
        for event, action in actions.items():
            owner = field if event in ('/K', '/F', '/V', '/C') else widget
            owner.setdefault(NameObject('/AA'), DictionaryObject())[event] = action
    widget[NameObject('/Parent')] = reference
    child = writer._add_object(widget)
    field[NameObject('/Kids')] = ArrayObject([child])
    return child


def _local_link(annotation, original, copy, named):
    """A link to a paragraph on this page stays on this particular occurrence."""
    if annotation.get('/Subtype') != '/Link':
        return
    owner, key = annotation, '/Dest'
    if key not in owner:
        if '/A' not in annotation or annotation['/A'].get('/S') != '/GoTo':
            return
        owner, key = annotation['/A'], '/D'
    if key not in owner:
        return
    destination = owner[key]
    if isinstance(destination, str) and destination in named:
        destination = named[destination].dest_array
    if isinstance(destination, ArrayObject) and destination and destination[0] == original:
        if owner is not annotation:
            owner = DictionaryObject(owner)  # A GoTo action may be shared with another annotation.
            annotation[NameObject('/A')] = owner
        owner[NameObject(key)] = ArrayObject([copy, *destination[1:]])


def _button_options(reader, occurrences):
    """Button export values follow the field's kids, even when other pages are omitted."""
    options = {}
    def widgets(page):
        return (ref for ref in page.get('/Annots', []) if ref.get_object().get('/Subtype') == '/Widget')

    for index, pages in occurrences.items():
        for source, target in zip(widgets(reader.pages[index]), widgets(pages[-1])):
            parent = source.get_object().get('/Parent')
            if parent is None:
                continue
            field = parent.get_object()
            if '/Opt' in field and field.get_inherited('/FT') == '/Btn':
                values = options.setdefault(target.get_object().raw_get('/Parent'), {})
                values[target] = field['/Opt'][field['/Kids'].index(source)].get_object()
    for reference, values in options.items():
        field = reference.get_object()
        field[NameObject('/Opt')] = ArrayObject(values[child] for child in field['/Kids'])


def _repeat_annotations(writer, pages, named):
    # pypdf initially attaches all remapped annotations to the last occurrence.
    last = pages[-1]
    canonical = {ref: _separate_widget(writer, ref) for ref in last['/Annots']}
    for page in pages:
        refs = canonical if page is last else {
            ref: writer._add_object(DictionaryObject(base.get_object())) for ref, base in canonical.items()}
        for original, ref in refs.items():
            annotation = ref.get_object()
            annotation[NameObject('/P')] = page.indirect_reference
            is_widget = annotation.get('/Subtype') == '/Widget'
            if page is not last:
                _local_link(annotation, last.indirect_reference, page.indirect_reference, named)
                if is_widget:
                    field = annotation['/Parent']
                    kids = field['/Kids']
                    if field.get_inherited('/FT') == '/Btn':
                        if '/Opt' in field:
                            field['/Opt'].append(field['/Opt'][kids.index(canonical[original])])
                        flags = field.get_inherited('/Ff', 0)
                        bits = FieldDictionaryAttributes.FfBits
                        if flags & bits.Radio:
                            field[NameObject('/Ff')] = NumberObject(flags | bits.RadiosInUnison)
                    kids.append(ref)
            # A widget's parent is a field. A popup's parent is a page annotation.
            for key in (('/Popup', '/IRT') if is_widget else ('/Popup', '/IRT', '/Parent')):
                target = annotation.get(key)
                if isinstance(target, IndirectObject) and target in refs:
                    annotation[NameObject(key)] = refs[target]
        page[NameObject('/Annots')] = ArrayObject(refs.values())


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

    occurrences = {}
    for index, page in zip(indices, writer.pages):
        occurrences.setdefault(index, []).append(page)
    if '/AcroForm' in catalog:
        _button_options(reader, occurrences)
    if len(occurrences) < len(indices):
        named = writer.named_destinations
        for pages in occurrences.values():
            if len(pages) > 1 and '/Annots' in pages[-1]:
                _repeat_annotations(writer, pages, named)
    if '/StructTreeRoot' in catalog:
        copy_structure(reader, writer, indices, projected_forms)
    return writer
