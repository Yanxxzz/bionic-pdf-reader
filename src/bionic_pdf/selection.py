"""Emphasize word prefixes without reflowing or replacing any PDF glyphs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from .words import text_flags, word_spans

from pypdf import PdfReader, PdfWriter
from pypdf._cmap import get_encoding
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    ContentStream,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

WORDS = re.compile(r"[A-Za-z]+")
STYLED_FONT = re.compile(r"bold|italic|oblique|black|heavy|demi|symbol|dingbat", re.I)
MATH = re.compile(r"[=+<>\u2211\u222b\u221a\u00b1\u00d7\u00f7\u2264\u2265\u221e]")
LINK = re.compile(r"https?://|www\.|@|_|\b[A-Za-z]+\.(?:com|org|net|edu)\b", re.I)


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
    stroke_cs: str = "/DeviceGray"
    stroke_values: tuple = (NumberObject(0),)
    line_width: float = 1.0
    render_mode: int = 0
    fill_alpha: float = 1.0
    stroke_alpha: float = 1.0

    @property
    def size(self):
        return abs(self.font_size) * math.hypot(float(self.matrix[2]), float(self.matrix[3]))


class Converter:
    def __init__(self, weight=0.026, locale='auto'):
        self.weight = weight
        self.locale = locale
        self.fonts = {}
        self.stats = Counter()
        self.font_stats = Counter()

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
                    mapping = {ord(k):v for k,v in cmap.items() if isinstance(k,str) and len(k)==1}
                    self.fonts[key] = (name,mapping) if mapping else None
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

    def emphasize(self, values, state, resources):
        if state.render_mode != 0 or not (6.8 <= state.size <= 24):
            return None
        # Keep rotated chart labels intact, including their extraction order.
        if abs(float(state.matrix[1])) > 0.00001 or abs(float(state.matrix[2])) > 0.00001:
            return None
        if state.fill_cs == "/Pattern" or abs(state.fill_alpha - state.stroke_alpha) > 0.0001:
            return None
        info = self.font_map(resources, state.font)
        if info is None:
            return None
        font_name, mapping = info
        font = resources['/Font'][state.font].get_object()
        unit = 2 if font.get('/Subtype') == '/Type0' else 1
        strings = [raw_string(value) for value in values if isinstance(value, (TextStringObject, ByteStringObject))]
        def letter(code): return mapping.get(code,'') if isinstance(mapping,dict) else mapping[code]
        text = "".join(letter(int.from_bytes(data[i:i+unit],'big')) for data in strings for i in range(0,len(data),unit))
        if not text or MATH.search(text) or LINK.search(text):
            return None
        matches = list(word_spans(text, self.locale))
        # A short isolated run is usually a mathematical function or symbol.
        if len(matches) == 1 and re.fullmatch(r'[A-Za-z]{1,4}', matches[0][1]) and not re.search(r"\s", text):
            return None
        flags = text_flags(text, locale=self.locale)
        word_count = sum(bool(flags[start]) for start, word in matches)
        if not any(flags):
            return None

        # Split only string bytes; preserve all original TJ kerning adjustments.
        groups = []
        current = []
        bold = False
        offset = 0
        for value in values:
            if not isinstance(value, (TextStringObject, ByteStringObject)):
                current.append(value)
                continue
            data = raw_string(value)
            pending = bytearray()
            for i in range(0,len(data),unit):
                raw = data[i:i+unit]
                char = letter(int.from_bytes(raw,'big'))
                requested = bool(flags[offset]) if offset < len(flags) and char else False
                offset += len(char)
                if requested != bold:
                    if pending:
                        current.append(ByteStringObject(bytes(pending)))
                        pending.clear()
                    if current:
                        groups.append((bold, ArrayObject(current)))
                    current = []
                    bold = requested
                pending.extend(raw)
            if pending:
                current.append(ByteStringObject(bytes(pending)))
        if current:
            groups.append((bold, ArrayObject(current)))

        # Do not use q/Q around text fragments: PDFium restores the text
        # position on Q, collapsing every word prefix onto its following text.
        # Explicitly restore only the stroke attributes that we change.
        width = FloatObject(round(state.size * self.weight, 5))
        output = [
            ([NameObject(state.fill_cs)], b"CS"),
            (list(state.fill_values), b"SCN"),
            ([width], b"w"),
        ]
        current_mode = state.render_mode
        for is_bold, group in groups:
            desired_mode = 2 if is_bold else state.render_mode
            if desired_mode != current_mode:
                output.append(([NumberObject(desired_mode)], b"Tr"))
                current_mode = desired_mode
            output.append(([group], b"TJ"))
        output.extend([
            ([NumberObject(state.render_mode)], b"Tr"),
            ([FloatObject(state.line_width)], b"w"),
            ([NameObject(state.stroke_cs)], b"CS"),
            (list(state.stroke_values), b"SCN"),
        ])
        self.stats["emphasized_words"] += word_count
        self.stats["changed_text_operations"] += 1
        self.font_stats[font_name] += word_count
        return output
