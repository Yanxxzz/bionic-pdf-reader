"""Resolve a PDF character code to the outline the embedded font actually draws."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO

from fontTools import agl
from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTFont
from pypdf.generic import DictionaryObject


def _encoding_differences(font):
    if '/Encoding' not in font:
        return {}
    encoding = font['/Encoding']  # pypdf resolves an indirect encoding dictionary here.
    if not isinstance(encoding, DictionaryObject) or '/Differences' not in encoding:
        return {}
    names = {}
    code = 0
    for item in encoding['/Differences']:
        if isinstance(item, int):
            code = int(item)
        else:
            names[code] = str(item)[1:]
            code += 1
    return names


@dataclass
class EmbeddedFont:
    glyphs: Mapping
    matrix: tuple
    bbox: tuple
    encoded_names: dict[int, str] = field(default_factory=dict)
    unicode_names: dict[int, str] = field(default_factory=dict)
    glyph_order: list[str] | None = None
    cid_map: bytes | None = None

    @classmethod
    def from_pdf(cls, font):
        cid = font.get('/Subtype') == '/Type0'
        descendant = font['/DescendantFonts'][0].get_object() if cid else font
        if '/FontDescriptor' not in descendant:
            return None
        descriptor = descendant['/FontDescriptor']
        try:
            if '/FontFile3' in descriptor and descriptor['/FontFile3'].get('/Subtype') == '/Type1C':
                cff = CFFFontSet()
                cff.decompile(BytesIO(descriptor['/FontFile3'].get_data()), None)
                top = cff[cff.fontNames[0]]
                return cls(top.CharStrings, tuple(top.FontMatrix), tuple(top.FontBBox), _encoding_differences(font))
            if '/FontFile2' not in descriptor:
                return None
            tt = TTFont(BytesIO(descriptor['/FontFile2'].get_data()))
            head = tt['head']
            unit = 1 / head.unitsPerEm
            embedded = cls(tt.getGlyphSet(), (unit, 0, 0, unit, 0, 0),
                           (head.xMin, head.yMin, head.xMax, head.yMax), unicode_names=tt.getBestCmap() or {})
            if cid:
                embedded.glyph_order = tt.getGlyphOrder()
                cid_map = descendant['/CIDToGIDMap'] if '/CIDToGIDMap' in descendant else None
                if hasattr(cid_map, 'get_data'):
                    embedded.cid_map = cid_map.get_data()
            else:
                mac = next((table.cmap for table in tt['cmap'].tables
                            if table.platformID == 1 and table.platEncID == 0), {})
                embedded.encoded_names = {**mac, **_encoding_differences(font)}
            return embedded
        except (KeyError, ValueError, AssertionError):
            return None

    def glyph_name(self, code, text):
        if self.glyph_order is None:
            name = self.encoded_names.get(code)
        else:
            offset = 2 * code
            gid = code if self.cid_map is None else int.from_bytes(self.cid_map[offset:offset + 2], 'big')
            name = self.glyph_order[gid] if gid < len(self.glyph_order) else None
        if not name and len(text) == 1:
            name = self.unicode_names.get(ord(text)) or agl.UV2AGL.get(ord(text))
        elif not name and text in ('fi', 'fl', 'ff', 'ffi', 'ffl'):
            name = text
        return name if name and name in self.glyphs else None
