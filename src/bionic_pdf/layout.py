"""Map word prefixes in a visual line or column back to the original glyphs."""
from collections import defaultdict
import re

from .words import segment_flags


def _same_line(first, other):
    height = other['h']
    return (abs(first['y'] - other['y']) <= max(first['h'], height) * 0.32
            and abs(first['h'] - height) < max(1, height * 0.15))


def _split_columns(line):
    columns = []
    edge = float('-inf')
    for item in sorted(line, key=lambda r: r['x']):
        if not columns or item['x'] - edge > 2 * item['h']:
            columns.append([])
        columns[-1].append(item)
        edge = max(edge, item['x'] + item['w'])
    return columns


def _atoms_by_font(records):
    # ActualText can give one logical spelling to several physical glyphs.
    clusters, scopes = [], {}
    for index, record in enumerate(records):
        scope = record.get('actual')
        if scope is None:
            clusters.append([index])
        elif scope['id'] in scopes:
            scopes[scope['id']].append(index)
        else:
            indices = scopes[scope['id']] = [index]
            clusters.append(indices)

    fonts = defaultdict(list)
    for indices in clusters:
        members = [records[i] for i in indices]
        base = max(members, key=lambda r: r['w'])
        scope = base.get('actual')
        text = scope['text'] if scope else base['text']
        if scope and (re.search(r'[\r\n\u0085\u2028\u2029]', text)
                      or not all(_same_line(base, r) for r in members)
                      or len(_split_columns(members)) > 1):
            # Keep each position occupied. A paragraph has no single glyph position.
            for record in members:
                fonts[id(record['font'])].append({**record, 'text': '\0', 'indices': ()})
            continue

        left = min(r['x'] for r in members)
        right = max(r['x'] + r['w'] for r in members)
        eligible = all(r['eligible'] for r in members) and not re.search(r'\s', text.strip())
        fonts[id(base['font'])].append({
            'text': text, 'indices': indices if eligible else (),
            'x': left, 'w': right - left, 'y': base['y'], 'h': base['h'],
        })
    return fonts.values()


def _visual_segments(records):
    for atoms in _atoms_by_font(records):
        lines = []
        for atom in sorted(atoms, key=lambda r: (r['y'], r['x'])):
            for line in reversed(lines[-3:]):
                if _same_line(line[0], atom):
                    line.append(atom)
                    break
            else:
                lines.append([atom])
        for line in lines:
            yield from _split_columns(line)


def select_glyphs(records):
    selected = set()
    for segment in _visual_segments(records):
        text = ''
        spans = []
        edge = float('-inf')
        for atom in segment:
            if text and atom['x'] - edge > atom['h'] * 0.18 and not text[-1].isspace():
                text += ' '
            start = len(text)
            text += atom['text']
            spans.append((start, len(text), atom['indices']))
            edge = max(edge, atom['x'] + atom['w'])

        flags = segment_flags(text)
        for start, end, indices in spans:
            if indices and flags.find(b'\x01', start, end) >= 0:
                selected.update(indices)
    return selected
