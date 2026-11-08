"""Resolve a PDF character code to the outline the embedded font actually draws."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO

from fontTools import agl
from fontTools.cffLib import CFFFontSet
from fontTools.pens.pointPen import PointToSegmentPen
from fontTools.ttLib import TTFont, TTLibError
from freetype import Face, FT_Exception, FT_LOAD_NO_SCALE
from pypdf._codecs import charset_encoding
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
class _Type1Glyph:
    face: Face
    index: int

    def draw(self, pen):
        try:
            self.face.load_glyph(self.index, FT_LOAD_NO_SCALE)
        except FT_Exception:
            return
        outline = self.face.glyph.outline
        points, tags = outline.points, outline.tags
        contours = PointToSegmentPen(pen)
        start = 0
        for end in outline.contours:
            contours.beginPath()
            for i in range(start, end + 1):
                # PostScript outlines use on-curve points and cubic control points.
                segment = None
                if tags[i] & 1:
                    previous = end if i == start else i - 1
                    segment = 'line' if tags[previous] & 1 else 'curve'
                contours.addPoint(points[i], segmentType=segment)
            contours.endPath()
            start = end + 1


@dataclass
class EmbeddedFont:
    glyphs: Mapping
    matrix: tuple
    bbox: tuple
    encoded_names: dict[int, str] = field(default_factory=dict)
    unicode_names: dict[int, str] = field(default_factory=dict)
    indexed_names: list[str] | dict[int, str] | None = None
    cid_map: bytes | None = None

    @classmethod
    def _type1(cls, font, stream):
        data = stream.get_data()
        if not data.startswith(b'%!'):
            return None
        face = Face.from_bytes(data)
        names = [face.get_glyph_name(i).decode('ascii') for i in range(face.num_glyphs)]
        glyphs = {name: _Type1Glyph(face, i) for i, name in enumerate(names) if i}
        encoding = font.get('/Encoding', DictionaryObject()).get_object()
        base = encoding.get('/BaseEncoding') if isinstance(encoding, DictionaryObject) else encoding
        encoded = {}
        if base in charset_encoding:
            encoded = {i: agl.UV2AGL.get(ord(char)) for i, char in enumerate(charset_encoding[base]) if len(char) == 1}
        else:
            for charmap in face.charmaps:
                if charmap.platform_id == 7:  # The original Adobe character encoding.
                    face.set_charmap(charmap)
                    encoded = {code: names[gid] for code, gid in face.get_chars() if gid}
                    break
        encoded.update(_encoding_differences(font))
        unit, box = 1 / face.units_per_EM, face.bbox
        return cls(glyphs, (unit, 0, 0, unit, 0, 0), (box.xMin, box.yMin, box.xMax, box.yMax), encoded)

    @classmethod
    def _cff(cls, font, stream, cid):
        data = BytesIO(stream.get_data())
        if stream.get('/Subtype') == '/OpenType':
            opentype = TTFont(data)
            if 'CFF ' not in opentype:
                return None
            cff = opentype['CFF '].cff
        else:
            cff = CFFFontSet()
            cff.decompile(data, None)
        if cff.major != 1 or len(cff.fontNames) != 1:
            return None
        top = cff[cff.fontNames[0]]
        if any(tuple(getattr(fd, 'FontMatrix', (1, 0, 0, 1, 0, 0))) != (1, 0, 0, 1, 0, 0)
               for fd in getattr(top, 'FDArray', ())):
            return None  # These outlines need an additional per-FD transform.
        embedded = cls(top.CharStrings, tuple(top.FontMatrix), tuple(top.FontBBox))
        if cid:
            # ISO 32000-1 §9.7.4.2. fontTools exposes a CID charset as cidNNNNN names.
            if hasattr(top, 'ROS'):
                names = {}
                for gid, name in enumerate(top.charset[1:], 1):
                    cid_number = int(name[3:])
                    # PDFium and Poppler render the OpenType wrapper by GID for these sparse CIDs.
                    if stream.get('/Subtype') != '/OpenType' or cid_number == gid:
                        names[cid_number] = name
                embedded.indexed_names = names
            else:
                embedded.indexed_names = top.charset
        else:
            embedded.encoded_names = _encoding_differences(font)
        return embedded

    @classmethod
    def from_pdf(cls, font):
        cid = font.get('/Subtype') == '/Type0'
        descendant = font['/DescendantFonts'][0].get_object() if cid else font
        if '/FontDescriptor' not in descendant:
            return None
        descriptor = descendant['/FontDescriptor']
        try:
            if not cid and font.get('/Subtype') == '/Type1' and '/FontFile' in descriptor:
                return cls._type1(font, descriptor['/FontFile'])
            if '/FontFile3' in descriptor:
                stream = descriptor['/FontFile3']
                if not cid and stream.get('/Subtype') == '/Type1C':
                    return cls._cff(font, stream, False)
                if (cid and str(font.get('/Encoding')) == '/Identity-H' and descendant.get('/Subtype') == '/CIDFontType0'
                        and stream.get('/Subtype') in ('/CIDFontType0C', '/OpenType')):
                    return cls._cff(font, stream, True)
            if '/FontFile2' not in descriptor:
                return None
            tt = TTFont(BytesIO(descriptor['/FontFile2'].get_data()))
            head = tt['head']
            unit = 1 / head.unitsPerEm
            embedded = cls(tt.getGlyphSet(), (unit, 0, 0, unit, 0, 0),
                           (head.xMin, head.yMin, head.xMax, head.yMax), unicode_names=tt.getBestCmap() or {})
            if cid:
                embedded.indexed_names = tt.getGlyphOrder()
                cid_map = descendant['/CIDToGIDMap'] if '/CIDToGIDMap' in descendant else None
                if hasattr(cid_map, 'get_data'):
                    embedded.cid_map = cid_map.get_data()
            else:
                mac = next((table.cmap for table in tt['cmap'].tables
                            if table.platformID == 1 and table.platEncID == 0), {})
                embedded.encoded_names = {**mac, **_encoding_differences(font)}
            return embedded
        except (KeyError, ValueError, AssertionError, TTLibError, FT_Exception):
            return None

    def glyph_name(self, code, text):
        if self.indexed_names is not None:
            index = code
            if self.cid_map is not None:
                offset = 2 * code
                if offset + 2 > len(self.cid_map):
                    return None
                index = int.from_bytes(self.cid_map[offset:offset + 2], 'big')
            try:
                name = self.indexed_names[index]
            except (KeyError, IndexError):
                return None
            return name if name != '.notdef' and name in self.glyphs else None
        name = self.encoded_names.get(code)
        if not name and len(text) == 1:
            name = self.unicode_names.get(ord(text)) or agl.UV2AGL.get(ord(text))
        elif not name and text in ('fi', 'fl', 'ff', 'ffi', 'ffl'):
            name = text
        return name if name and name in self.glyphs else None
