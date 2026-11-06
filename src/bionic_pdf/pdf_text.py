"""Decode original PDF character codes and track the text state used by overlays."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from pypdf._cmap import get_encoding
from pypdf.generic import ByteStringObject, NumberObject, TextStringObject

STYLED_FONT = re.compile(r"bold|italic|oblique|black|heavy|demi|symbol|dingbat", re.I)


def raw_string(value):
    if isinstance(value, ByteStringObject):
        return bytes(value)
    if isinstance(value, TextStringObject):
        return value.original_bytes
    raise TypeError(type(value))


@dataclass
class State:
    font: str = ""
    font_size: float = 0.0
    matrix: tuple = (1, 0, 0, 1, 0, 0)
    fill_cs: str = "/DeviceGray"
    fill_values: tuple = (NumberObject(0),)
    render_mode: int = 0
    fill_alpha: float = 1.0
    stroke_alpha: float = 1.0

    @property
    def size(self):
        return abs(self.font_size) * math.hypot(float(self.matrix[2]), float(self.matrix[3]))


class FontDecoder:
    def __init__(self):
        self.fonts = {}

    def font_map(self, resources, font_name):
        font_ref = resources.get("/Font", {}).get(font_name)
        if font_ref is None:
            return None
        font = font_ref.get_object()
        reference = getattr(font, "indirect_reference", None)
        key = (reference.idnum, reference.generation) if reference else id(font)
        if key not in self.fonts:
            name = str(font.get("/BaseFont", ""))
            cid = font.get('/Subtype') == '/Type0' and str(font.get('/Encoding')) == '/Identity-H'
            if STYLED_FONT.search(name) or not (cid or font.get("/Subtype") in ("/Type1", "/TrueType")):
                self.fonts[key] = None
            else:
                encoding, cmap = get_encoding(font)
                if cid:
                    mapping = {ord(k): v for k, v in cmap.items() if isinstance(k, str) and len(k) == 1}
                    self.fonts[key] = (name, mapping) if mapping else None
                elif cmap.get(-1, 1) != 1:
                    self.fonts[key] = None
                else:
                    mapping = []
                    for value in range(256):
                        if isinstance(encoding, dict):
                            letter = encoding.get(value, chr(value))
                        else:
                            try:
                                letter = bytes([value]).decode(encoding, errors="replace")
                            except (LookupError, UnicodeError):
                                letter = chr(value)
                        mapping.append("".join(cmap.get(char, char) for char in letter))
                    self.fonts[key] = (name, mapping)
        return self.fonts[key]
