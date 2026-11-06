"""Create a WPS-switchable reading copy with one optional vector stroke layer.

Original PDF text remains the only text. Embedded glyph outlines are reused as
vector Form XObjects; no duplicate text or rasterized pages are introduced.
"""
from __future__ import annotations

import argparse
import copy
import io
import math
import re
import time
import sys
from pathlib import Path


from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen
from fontTools import agl
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject as A, DictionaryObject as D, NameObject as N,
    NumberObject as I, FloatObject as F, TextStringObject as T, BooleanObject as B,
    DecodedStreamObject, ContentStream)
from .selection import Converter, State, raw_string


def num(value):
    return f'{float(value):.7f}'.rstrip('0').rstrip('.') or '0'


def matrix_multiply(left, right):
    a,b,c,d,e,f = left
    g,h,i,j,k,l = right
    return (a*g+c*h, b*g+d*h, a*i+c*j, b*i+d*j, a*k+c*l+e, b*k+d*l+f)


def translated(matrix, x, y):
    return matrix_multiply(matrix, (1,0,0,1,x,y))


class PathPen(BasePen):
    def __init__(self, glyph_set):
        super().__init__(glyph_set)
        self.commands = []
    def _moveTo(self, point): self.commands.append(' '.join(map(num, point)) + ' m')
    def _lineTo(self, point): self.commands.append(' '.join(map(num, point)) + ' l')
    def _curveToOne(self, a, b, d): self.commands.append(' '.join(map(num, (*a,*b,*d))) + ' c')
    def _closePath(self): self.commands.append('h')
    def _endPath(self): pass


class GlyphLibrary:
    def __init__(self, writer, weight):
        self.writer, self.weight = writer, weight
        self.fonts, self.forms = {}, {}
        self.skipped = set()
    def font(self, font):
        key = font.indirect_reference.idnum if getattr(font, 'indirect_reference', None) else id(font)
        if key in self.fonts: return self.fonts[key]
        info = None
        cid = font.get('/Subtype') == '/Type0'
        descendant = font['/DescendantFonts'][0].get_object() if cid else font
        descriptor = descendant.get('/FontDescriptor')
        descriptor = descriptor.get_object() if descriptor else {}
        try:
            if '/FontFile3' in descriptor and descriptor['/FontFile3'].get('/Subtype') == '/Type1C':
                cff = CFFFontSet()
                cff.decompile(io.BytesIO(descriptor['/FontFile3'].get_data()), None)
                top = cff[cff.fontNames[0]]
                info = {'glyphs': top.CharStrings, 'matrix': tuple(top.FontMatrix), 'bbox': tuple(top.FontBBox), 'owner': cff}
            elif '/FontFile2' in descriptor:
                tt = TTFont(io.BytesIO(descriptor['/FontFile2'].get_data()))
                upem = tt['head'].unitsPerEm
                info = {'glyphs': tt.getGlyphSet(), 'matrix': (1/upem,0,0,1/upem,0,0),
                    'bbox': (tt['head'].xMin,tt['head'].yMin,tt['head'].xMax,tt['head'].yMax), 'owner': tt,
                    'cmap': tt.getBestCmap() or {},
                    'byte_cmap': next((t.cmap for t in tt['cmap'].tables if t.platformID==1 and t.platEncID==0),{})}
                if cid:
                    cidmap = descendant.get('/CIDToGIDMap')
                    info['cidmap'] = cidmap.get_object().get_data() if cidmap is not None and hasattr(cidmap.get_object(),'get_data') else None
                    info['glyph_order'] = tt.getGlyphOrder()
            if info:
                encoding = font.get('/Encoding')
                differences, index = {}, 0
                if isinstance(encoding, D):
                    for item in encoding.get('/Differences', []):
                        if isinstance(item, (int, I)): index = int(item)
                        else: differences[index] = str(item)[1:]; index += 1
                info['differences'] = differences
                info['key'] = key
        except (KeyError, ValueError, AssertionError):
            info = None
        self.fonts[key] = info
        return info
    def glyph(self, font, byte, unicode_text):
        info = self.font(font)
        if not info: self.skipped.add(str(font.get('/BaseFont'))); return None
        name = info['differences'].get(byte)
        if not name and 'glyph_order' not in info:
            name = info.get('byte_cmap',{}).get(byte)
        if 'glyph_order' in info:
            cidmap = info['cidmap']
            gid = int.from_bytes(cidmap[byte*2:byte*2+2],'big') if cidmap is not None else byte
            name = info['glyph_order'][gid] if gid < len(info['glyph_order']) else None
        if not name:
            if len(unicode_text) == 1:
                name = info.get('cmap', {}).get(ord(unicode_text)) or agl.UV2AGL.get(ord(unicode_text))
            elif unicode_text in ('fi', 'fl', 'ff', 'ffi', 'ffl'):
                name = unicode_text
        if not name or name not in info['glyphs']: return None
        key = (info['key'], name)
        if key not in self.forms:
            pen = PathPen(info['glyphs'])
            info['glyphs'][name].draw(pen)
            if not pen.commands: return None
            # Width is in the glyph's units, so all text sizes share this form.
            em_scale = max(abs(info['matrix'][0]), abs(info['matrix'][3]))
            line_width = self.weight / em_scale
            content = ('q ' + num(line_width) + ' w 1 j 1 J\n' + '\n'.join(pen.commands) + '\nS Q\n').encode('ascii')
            form = DecodedStreamObject()
            form.set_data(content)
            x0,y0,x1,y1 = info['bbox']
            form.update({N('/Type'): N('/XObject'), N('/Subtype'): N('/Form'),
                N('/BBox'): A(F(x) for x in (x0-line_width,y0-line_width,x1+line_width,y1+line_width)),
                N('/Resources'): D()})
            self.forms[key] = (N('/BRGlyph' + str(len(self.forms))), self.writer._add_object(form.flate_encode()))
        name, reference = self.forms[key]
        return name, reference, info['matrix']


class OverlayBuilder:
    def __init__(self, writer, layer, weight=0.026, locale='auto'):
        self.writer, self.layer = writer, layer
        self.selector = Converter(weight, locale)
        self.glyphs = GlyphLibrary(writer, weight)
        self.count = 0
        self.widths = {}
    def width(self,font,code):
        key = font.indirect_reference.idnum if getattr(font,'indirect_reference',None) else id(font)
        if key not in self.widths:
            if font.get('/Subtype') == '/Type0':
                child = font['/DescendantFonts'][0].get_object()
                values, table, i = child.get('/W',[]), {}, 0
                while i < len(values):
                    start = int(values[i]); value = values[i+1]; i += 2
                    if isinstance(value,A): table.update({start+j:float(w) for j,w in enumerate(value)})
                    else:
                        end,width = int(value),float(values[i]); i += 1
                        table.update({c:width for c in range(start,end+1)})
                default = float(child.get('/DW',1000))
            else:
                first = int(font.get('/FirstChar',0))
                table = {first+i:float(w) for i,w in enumerate(font.get('/Widths',[]))}
                default = 0
            self.widths[key] = table,default
        table,default = self.widths[key]
        return table.get(code,default)
    def build_page(self, page):
        page_content = page.get_contents()
        if page_content is None:
            return 0
        resources = page.get('/Resources', D())
        original = page_content.get_data()
        content = ContentStream(page_content, self.writer)
        state, ctm, line_matrix = State(), (1,0,0,1,0,0), (1,0,0,1,0,0)
        tc, tw, tz, rise, leading = 0.0, 0.0, 1.0, 0.0, 0.0
        stack, commands, used = [], [], {}
        marked = []
        position_known = True
        page_count = 0
        for args, op in content.operations:
            if op in (b'BDC',b'BMC'):
                if op == b'BDC' and str(args[0]) == '/OC' and isinstance(args[1],N): marked.append(str(args[1]))
                else: marked.append(None)
            elif op == b'EMC' and marked: marked.pop()
            if op == b'q': stack.append((copy.copy(state), ctm, tc, tw, tz, rise, leading))
            elif op == b'Q' and stack:
                matrix = state.matrix
                state, ctm, tc, tw, tz, rise, leading = stack.pop()
                state.matrix = matrix
            elif op == b'cm': ctm = matrix_multiply(ctm, tuple(map(float,args)))
            elif op == b'BT': state.matrix = line_matrix = (1,0,0,1,0,0); position_known = True
            elif op == b'Tf': state.font, state.font_size = str(args[0]), float(args[1])
            elif op == b'Tm': state.matrix = line_matrix = tuple(map(float,args)); position_known = True
            elif op in (b'Td', b'TD', b'T*'):
                if op == b'T*': x,y = 0,-leading
                else:
                    x,y = map(float,args)
                    if op == b'TD': leading = -y
                line_matrix = translated(line_matrix,x,y); state.matrix = line_matrix; position_known = True
            elif op == b'Tc': tc = float(args[0])
            elif op == b'Tw': tw = float(args[0])
            elif op == b'Tz': tz = float(args[0])/100
            elif op == b'Ts': rise = float(args[0])
            elif op == b'TL': leading = float(args[0])
            elif op == b'Tr': state.render_mode = int(args[0])
            elif op in (b'g',b'rg',b'k'):
                state.fill_cs = {b'g':'/DeviceGray',b'rg':'/DeviceRGB',b'k':'/DeviceCMYK'}[op]
                state.fill_values = tuple(args)
            elif op == b'cs': state.fill_cs = str(args[0]); state.fill_values = (I(0),)
            elif op in (b'sc',b'scn'): state.fill_values = tuple(args)
            elif op == b'gs':
                gs = resources.get('/ExtGState',{}).get(args[0])
                if gs:
                    gs = gs.get_object()
                    state.fill_alpha = float(gs.get('/ca',state.fill_alpha))
                    state.stroke_alpha = float(gs.get('/CA',state.stroke_alpha))
            if op in (b"'", b'"'):
                if op == b'"': tw,tc = float(args[0]),float(args[1])
                line_matrix = translated(line_matrix,0,-leading); state.matrix = line_matrix; position_known = True
            if op not in (b'Tj', b'TJ', b"'", b'"'): continue
            values = args[0] if op == b'TJ' else A([args[-1]])
            font = resources.get('/Font',{}).get(state.font)
            if font is None: position_known = False; continue
            font = font.get_object()
            cid = font.get('/Subtype') == '/Type0' and str(font.get('/Encoding')) == '/Identity-H'
            if not (cid or font.get('/Subtype') in ('/Type1','/TrueType')):
                self.glyphs.skipped.add(str(font.get('/BaseFont','unknown')))
                position_known = False; continue
            mapping = self.selector.font_map(resources,state.font)
            cmap = mapping[1] if mapping else [chr(i) for i in range(256)]
            selection = self.selector.emphasize(values,state,resources) if position_known and state.fill_alpha == 1 else None
            groups = []
            if selection:
                mode = 0
                for operands, operator in selection:
                    if operator == b'Tr': mode = int(operands[0])
                    elif operator == b'TJ': groups.append((mode == 2,operands[0]))
            else: groups = [(False,values)]
            unit = 2 if cid else 1
            for selected, items in groups:
                for item in items:
                    if not isinstance(item, (T,bytes)):
                        state.matrix = translated(state.matrix,-float(item)*state.font_size*tz/1000,0)
                        continue
                    raw = raw_string(item)
                    for offset in range(0,len(raw),unit):
                        byte = int.from_bytes(raw[offset:offset+unit],'big')
                        if selected:
                            glyph = self.glyphs.glyph(font,byte,cmap.get(byte,'') if isinstance(cmap,dict) else cmap[byte])
                            if glyph:
                                key,reference,fm = glyph
                                used[key] = reference
                                transform = matrix_multiply(ctm,matrix_multiply(translated(state.matrix,0,rise),
                                    matrix_multiply((state.font_size*tz,0,0,state.font_size,0,0),fm)))
                                oc = [tag for tag in marked if tag]
                                draw = ('q ' + ' '.join(map(num,transform)) + ' cm ' + state.fill_cs + ' CS ' +
                                    ' '.join(map(str,state.fill_values)) + ' SCN ' + str(key) + ' Do Q')
                                commands.append(' '.join('/OC '+tag+' BDC' for tag in oc)+' '+draw+' EMC'*len(oc))
                                page_count += 1
                        width = self.width(font,byte)
                        advance = (width*state.font_size/1000 + tc + (tw if byte == 32 else 0))*tz
                        state.matrix = translated(state.matrix,advance,0)
        if commands:
            if self.layer is not None:
                properties = resources.get('/Properties')
                if not properties: properties = D(); resources[N('/Properties')] = properties
                properties[N('/BRBionic')] = self.layer
            xobjects = resources.get('/XObject')
            if not xobjects: xobjects = D(); resources[N('/XObject')] = xobjects
            xobjects.update(used)
            stream = DecodedStreamObject()
            start, end = (b'/OC /BRBionic BDC\n', b'\nEMC\n') if self.layer is not None else (b'', b'\n')
            stream.set_data(b'q\n' + original + b'\nQ\n' + start + '\n'.join(commands).encode('ascii') + end)
            page.replace_contents(stream.flate_encode())
        self.count += page_count
        return page_count



def make_pdf(source, target, pages=None, weight=0.026, mode='switchable', locale='auto'):
    started = time.monotonic()
    if mode not in ('switchable','static'): raise ValueError('mode must be switchable or static')
    if Path(source).resolve() == Path(target).resolve(): raise ValueError('请为阅读副本选择不同文件名，不能覆盖原 PDF。')
    reader = PdfReader(source)
    if reader.is_encrypted and not reader.decrypt(''): raise ValueError('请先打开并另存为未加密的 PDF。')
    writer = PdfWriter(clone_from=reader) if pages is None else PdfWriter()
    writer.pdf_header = b'%PDF-1.6'
    if pages is not None:
        for number in pages: writer.add_page(reader.pages[number-1])
    existing = writer._root_object.get('/OCProperties')
    if existing and any(str(x.get_object().get('/Name','')) == '仿生阅读 · Bionic Reading' for x in existing.get('/OCGs',[])):
        raise ValueError('这份 PDF 已包含仿生开关，请直接在 WPS 中切换，或选择原始 PDF。')
    layer = writer._add_object(D({N('/Type'):N('/OCG'), N('/Name'):T('仿生阅读 · Bionic Reading')})) if mode == 'switchable' else None
    if existing and layer is not None:
        existing.setdefault(N('/OCGs'),A()).append(layer)
        config = existing.setdefault(N('/D'),D())
        config.setdefault(N('/OFF'),A()).append(layer)
        config.setdefault(N('/Order'),A()).append(layer)
    elif layer is not None:
        writer._root_object[N('/OCProperties')] = D({N('/OCGs'):A([layer]),
            N('/D'):D({N('/Name'):T('Reading mode'),N('/BaseState'):N('/ON'),N('/OFF'):A([layer]),N('/Order'):A([layer])})})
    if layer is not None: writer._root_object[N('/PageMode')] = N('/UseOC')
    builder = OverlayBuilder(writer,layer,weight,locale)
    for i,page in enumerate(writer.pages):
        count = builder.build_page(page)
        if (i+1)%50 == 0 or i+1 == len(writer.pages):
            print(f'PROGRESS {i+1}/{len(writer.pages)} glyphs={builder.count} seconds={time.monotonic()-started:.1f}',flush=True)
    if builder.count == 0: raise ValueError('未找到可处理的文字层或可用嵌入字体；扫描版需先做 OCR。')
    writer.add_metadata({'/Title':str((reader.metadata.title if reader.metadata else None) or Path(source).stem) + ' - Switchable Reading',
        '/Subject':'Original PDF text plus optional vector word-prefix emphasis. Toggle the Bionic Reading layer in WPS.'})
    target = Path(target)
    temporary = target.with_name(target.stem+'.partial.pdf')
    try:
        writer.write(temporary)
        temporary.replace(target)
    finally:
        if temporary.exists(): temporary.unlink()
    print(f'DONE {target}',flush=True)
    return {'pages':len(writer.pages),'glyphs':builder.count,'glyph_forms':len(builder.glyphs.forms),
        'skipped_fonts':sorted(builder.glyphs.skipped),'mode':mode,'locale':locale,'seconds':time.monotonic()-started}
