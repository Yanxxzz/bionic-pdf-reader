"""Keep the logical reading order and its reverse index when selecting PDF pages."""
from collections import defaultdict
from copy import copy

from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NullObject, NumberObject


def _fields(source, writer, excluded):
    return DictionaryObject({key: value.clone(writer) for key, value in source.items() if key not in excluded})


def _number_tree(node):
    entries = node.get('/Nums', [])
    yield from zip(entries[::2], entries[1::2])
    for child in node.get('/Kids', []):
        yield from _number_tree(child.get_object())


def _unsupported(reason):
    raise ValueError(f'这份 PDF 的无障碍标签{reason}，无法保真地导出所选页。请改为导出整本 PDF。')


def _content_items(value, path=(), page=None):
    item = value.get_object()
    if isinstance(item, ArrayObject):
        for child in item:
            yield from _content_items(child, path, page)
        return
    if isinstance(item, DictionaryObject):
        page = item.get('/Pg', page)
        if '/S' in item:
            if any(ancestor is item for ancestor in path):
                raise ValueError('这份 PDF 的无障碍结构树含有循环引用。')
            path = (*path, item)
            if '/K' in item and item['/K'] != []:
                yield from _content_items(item['/K'], path, page)
                return
            item = None  # A page-bound element may have alternate text and no children.
        elif item.get('/Type') == '/OBJR' and page is None:
            page = item['/Obj'].get('/P')
    yield path, page, item


def _form_field(item):
    field = {'/MCR': '/Stm', '/OBJR': '/Obj'}.get(item.get('/Type'))
    if field in item and isinstance(item[field], DictionaryObject) and item[field].get('/Subtype') == '/Form':
        return field
    return None


def _check_form_parent(item, field, parent, numbers):
    """Verify the inverse mapping before using the forward structure-tree entry."""
    form = item[field]
    if field == '/Obj':
        slot = None
        original = numbers.get(form.get('/StructParent'))
    else:
        slot = item.get('/MCID')
        entry = numbers.get(form.get('/StructParents'))
        slots = entry.get_object() if entry is not None else None
        original = (slots[slot] if isinstance(slots, ArrayObject) and isinstance(slot, NumberObject)
                    and 0 <= slot < len(slots) else None)
    if original != parent.indirect_reference:
        raise ValueError('这份 PDF 的 Form 标签和父级索引不一致，无法安全生成阅读副本。')


class FormTags:
    """Bind a tagged Form to the exact object painted on each output page."""

    def __init__(self, writer, projected):
        self.writer = writer
        self.bindings = defaultdict(list)
        self.painted = {}
        self.repeated = set()
        self.original_keys = {}
        self.root = writer.root_object.get('/StructTreeRoot')
        if self.root is None:
            return
        self.root = self.root.get_object()
        self.numbers = dict(_number_tree(self.root.get('/ParentTree', DictionaryObject()).get_object()))

        for path, page, node in _content_items(self.root.get('/K', ArrayObject())):
            field = _form_field(node) if isinstance(node, DictionaryObject) else None
            if field is None:
                continue
            if not path or page is None:
                raise ValueError('这份 PDF 的 Form 标签缺少所属页或父级元素。')
            form = node.raw_get(field)
            if form not in projected:
                _check_form_parent(node, field, path[-1], self.numbers)
            # An annotation paints its appearance outside the page's Do operations.
            owner = node.get('/StmOwn')
            if owner is not None and owner.get_object().get('/Subtype') not in (None, '/Form'):
                if form in projected:
                    _unsupported('引用了批注的独立外观流')
                continue
            if form not in projected:
                self.original_keys[form] = form.get_object()['/StructParents' if field == '/Stm' else '/StructParent']
            self.bindings[page, form].append((node, field, node.get('/MCID'), path[-1].indirect_reference))
            if owner is not None and owner.get_object().get('/Subtype') == '/Form':
                self.bindings[page, owner].append((node, '/StmOwn', None, None))

    def paint(self, page, form, edited):
        """Return this invocation's Form reference, or None to keep the original Do."""
        key = (page, form.indirect_reference)
        if key not in self.bindings:
            return self.writer._add_object(edited) if edited is not None else None
        if edited is None:
            edited = copy(form)
            edited.indirect_reference = None
        edited.pop('/StructParents', None)
        edited.pop('/StructParent', None)
        previous = self.painted.get(key)
        if previous is not None:
            self.repeated.add(key)
            if previous._data != edited._data or previous != edited:
                raise ValueError('同一页多次绘制同一个带标签的 Form，绘图状态不同且标签无法区分各次绘制。')
            return previous.indirect_reference
        self.painted[key] = edited
        return self.writer._add_object(edited)

    def replace_painted(self, page, source, edited):
        """Retain a painted Form's deferred tag binding when OCR supplements that invocation."""
        key = next((key for key, painted in self.painted.items() if key[0] == page and painted is source), None)
        if key is not None:
            if key in self.repeated:
                raise ValueError('同一页多次绘制同一个带标签的 Form，标签无法区分各次 OCR 补字。')
            self.painted[key] = edited
        return self.writer._add_object(edited)

    def finish(self):
        if not self.bindings:
            return
        for form, key in self.original_keys.items():
            self.numbers.pop(key, None)
            form.get_object().pop('/StructParent', None)
            form.get_object().pop('/StructParents', None)
        next_key = max(self.numbers, default=-1) + 1
        for key, bindings in self.bindings.items():
            painted = self.painted.get(key)
            if painted is None:
                raise ValueError('无障碍标签引用的 Form 未在对应页面中绘制，无法安全生成阅读副本。')
            slots = {}
            for node, field, slot, parent in bindings:
                node[NameObject(field)] = painted.indirect_reference
                if field != '/StmOwn':
                    if slot in slots and slots[slot] != parent:
                        raise ValueError('同一 Form 内容有多个不同的结构父级，无法安全生成阅读副本。')
                    slots[slot] = parent
            if slots:
                if None in slots:
                    if len(slots) != 1:
                        raise ValueError('同一 Form 同时使用了对象标签和内容标签，无法安全生成阅读副本。')
                    field, entry = '/StructParent', slots[None]
                else:
                    field = '/StructParents'
                    entry = ArrayObject(slots.get(i, NullObject()) for i in range(max(slots) + 1))
                painted[NameObject(field)] = NumberObject(next_key)
                self.numbers[NumberObject(next_key)] = entry
                next_key += 1
        nums = ArrayObject(value for key in sorted(self.numbers) for value in (key, self.numbers[key]))
        self.root[NameObject('/ParentTree')] = self.writer._add_object(DictionaryObject({NameObject('/Nums'): nums}))
        self.root[NameObject('/ParentTreeNextKey')] = NumberObject(next_key)


def copy_structure(reader, writer, indices, projected_forms=None):
    if projected_forms is None:
        projected_forms = set()
    first_new_object = len(writer._objects)
    source = reader.root_object['/StructTreeRoot']
    selected = {reader.pages[i].indirect_reference for i in indices}
    items = defaultdict(list)
    for order, (ancestors, page, item) in enumerate(_content_items(source.get('/K', ArrayObject()))):
        if page in selected:
            items[page].append((order, ancestors, item))
        elif page is None and item is not None:
            _unsupported('中有无法定位到页面的内容')
    root = _fields(source, writer, {'/K', '/ParentTree', '/ParentTreeNextKey', '/IDTree'})
    writer.root_object[NameObject('/StructTreeRoot')] = writer._add_object(root)
    root[NameObject('/K')] = ArrayObject()
    original_parents = dict(_number_tree(source.get('/ParentTree', DictionaryObject()).get_object()))
    numbers = ArrayObject()
    identifiers = {}

    def link_parent(container, key, source_key, elements):
        entry = original_parents.get(source_key)
        if entry is None:
            _unsupported('缺少对应的父级索引')

        def remap(reference):
            parent = elements.get(id(reference.get_object()))
            if parent is None:
                _unsupported('的父级索引指向未保留的结构元素')
            return parent.indirect_reference

        if key == '/StructParents':
            slots = entry.get_object()
            if not isinstance(slots, ArrayObject):
                _unsupported('的页面父级索引不是数组')
            parent = ArrayObject(NullObject() if isinstance(ref.get_object(), NullObject) else remap(ref)
                                 for ref in slots)
        else:
            parent = remap(entry)
        container[NameObject(key)] = NumberObject(len(numbers) // 2)
        numbers.extend((container[key], parent))

    def add_element(element, parent):
        if '/Ref' in element:
            _unsupported('含有结构元素间的交叉引用')
        copied = _fields(element, writer, {'/P', '/Pg', '/K'})
        copied[NameObject('/P')] = parent.indirect_reference
        copied[NameObject('/K')] = ArrayObject()
        parent['/K'].append(writer._add_object(copied))
        if '/ID' in element:
            key = element['/ID']
            if key.original_bytes in identifiers:
                _unsupported('的选页顺序会重复一个结构标识符')
            identifiers[key.original_bytes] = (key.clone(writer), copied.indirect_reference)
        return copied

    # Keep one Document wrapper even when reordering pages restarts their source order.
    top = source.get('/K', ArrayObject()).get_object()
    if isinstance(top, ArrayObject):
        top = top[0].get_object() if len(top) == 1 else None
    document = add_element(top, root) if isinstance(top, DictionaryObject) and top.get('/S') == '/Document' else None

    # A forward run keeps elements that span pages (paragraphs, tables) together.
    # Once a page repeats or moves backward its content gets a separate set of parents.
    runs = [0]
    runs.extend(i for i in range(1, len(indices)) if indices[i] <= indices[i - 1])
    for start, end in zip(runs, [*runs[1:], len(indices)]):
        pages = {reader.pages[indices[i]].indirect_reference: writer.pages[i] for i in range(start, end)}
        annots = {page: {ref.get_object()['/StructParent']: ref for ref in target.get('/Annots', [])
                         if '/StructParent' in ref.get_object()} for page, target in pages.items()}
        elements = {id(top): document} if document is not None else {}
        ordered = sorted((n, page, path, item) for page in pages for n, path, item in items[page])
        for _, page, path, item in ordered:
            target_page = pages[page].indirect_reference
            if isinstance(item, DictionaryObject):
                field = _form_field(item)
                if field:
                    if not path:
                        _unsupported('的 Form 标签缺少父级元素')
                    _check_form_parent(item, field, path[-1], original_parents)
                    original = item
                    item = _fields(original, writer, {'/Pg', '/StmOwn'})
                    reference = item.raw_get(field)
                    projected_forms.add(reference)
                    if '/StmOwn' in original:
                        owner = original.raw_get('/StmOwn')
                        if owner == page:
                            item[NameObject('/StmOwn')] = target_page
                        elif owner.get_object().get('/Subtype') == '/Form':
                            item[NameObject('/StmOwn')] = owner.clone(writer)
                        else:
                            _unsupported('引用了批注的独立外观流')
                elif '/Stm' in item or '/StmOwn' in item:
                    _unsupported('引用了独立的标记内容流')
                elif item.get('/Type') == '/OBJR':
                    obj = item['/Obj']
                    annotation = annots[page].get(obj.get('/StructParent'))
                    if annotation is None:
                        if item.get('/Obj') in page.get_object().get('/Annots', []):
                            continue  # Its internal link pointed to an omitted page.
                        _unsupported('引用了页面批注以外的对象')
                    item = DictionaryObject({NameObject('/Type'): NameObject('/OBJR'), NameObject('/Obj'): annotation})
                elif item.get('/Type') == '/MCR':
                    item = _fields(item, writer, {'/Pg'})
                else:
                    _unsupported('含有未知的结构内容项')
                item[NameObject('/Pg')] = target_page
            parent = root
            for element in path:
                copied = elements.get(id(element))
                if copied is None:
                    copied = elements[id(element)] = add_element(element, parent)
                    source_page = element.get('/Pg')
                    if source_page in pages:
                        copied[NameObject('/Pg')] = pages[source_page].indirect_reference
                parent = copied
            if isinstance(item, NumberObject) and parent.setdefault(NameObject('/Pg'), target_page) != target_page:
                item = DictionaryObject({NameObject('/Type'): NameObject('/MCR'),
                                         NameObject('/MCID'): item, NameObject('/Pg'): target_page})
            if item is not None:
                parent['/K'].append(item)
        for page, target in pages.items():
            key = page.get_object().get('/StructParents')
            if key is not None:
                link_parent(target, '/StructParents', key, elements)
            for key, ref in annots[page].items():
                link_parent(ref.get_object(), '/StructParent', key, elements)
    root[NameObject('/ParentTree')] = writer._add_object(DictionaryObject({NameObject('/Nums'): numbers}))
    root[NameObject('/ParentTreeNextKey')] = NumberObject(len(numbers) // 2)
    if identifiers:
        names = ArrayObject(value for key in sorted(identifiers) for value in identifiers[key])
        root[NameObject('/IDTree')] = writer._add_object(DictionaryObject({NameObject('/Names'): names}))
    # Private tag attributes may themselves point to omitted pages or their page tree.
    if any(isinstance(obj, DictionaryObject) and obj.get('/Type') == '/Page'
           for obj in writer._objects[first_new_object:]):
        _unsupported('的附加属性引用了未选择的页面')
    # A shared resource can survive even when its only tagged placement was on an omitted page.
    # FormTags rebuilds the keys of the actual selected placements in the new parent tree.
    for obj in writer._objects:
        if isinstance(obj, DictionaryObject) and obj.get('/Subtype') == '/Form':
            obj.pop('/StructParents', None)
            obj.pop('/StructParent', None)
