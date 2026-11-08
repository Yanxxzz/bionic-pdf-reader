"""Keep the logical reading order and its reverse index when selecting PDF pages."""
from collections import defaultdict

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


def copy_structure(reader, writer, indices):
    first_new_object = len(writer._objects)
    source = reader.root_object['/StructTreeRoot']
    selected = {reader.pages[i].indirect_reference for i in indices}
    items = defaultdict(list)
    order = 0

    def index(value, ancestors=(), page=None):
        nonlocal order
        item = value.get_object()
        if isinstance(item, DictionaryObject):
            page = item.get('/Pg', page)
            if '/S' in item:
                if any(ancestor is item for ancestor in ancestors):
                    _unsupported('含有循环引用')
                ancestors = (*ancestors, item)
                if '/K' in item and item['/K'] != []:
                    index(item['/K'], ancestors, page)
                    return
                item = None  # A page-bound element can have alternate text and no children.
            elif item.get('/Type') == '/OBJR' and page is None:
                page = item['/Obj'].get('/P')
        if isinstance(item, ArrayObject):
            for child in item:
                index(child, ancestors, page)
        elif page in selected:
            items[page].append((order, ancestors, item))
            order += 1
        elif page is None and item is not None:
            _unsupported('中有无法定位到页面的内容')

    if '/K' in source:
        index(source['/K'])
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
                if '/Stm' in item or '/StmOwn' in item:
                    _unsupported('引用了独立的标记内容流')
                if item.get('/Type') == '/OBJR':
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
