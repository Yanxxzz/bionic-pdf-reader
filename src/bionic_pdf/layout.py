"""Select prefixes across positioned glyph runs, retaining ActualText clusters."""
from collections import defaultdict
import regex
from .words import text_flags

def select_glyphs(records):
    atoms=[];scopes={}
    for i,record in enumerate(records):
        scope=record.get('actual')
        if scope is not None:
            key=scope['id']
            if key not in scopes:
                scopes[key]={'text':scope['text'],'records':[]};atoms.append(scopes[key])
            scopes[key]['records'].append((i,record))
        else:atoms.append({'text':record['text'],'records':[(i,record)]})
    groups=defaultdict(list)
    for atom in atoms:
        members=atom['records'];base=max(members,key=lambda pair:pair[1]['w'])[1]
        atom.update(x=min(r['x'] for _,r in members),right=max(r['x']+r['w'] for _,r in members),y=base['y'],h=base['h'])
        # One ActualText scope is an indivisible shaped unit. Paragraph-sized
        # replacement spans cannot reliably map a prefix to their glyphs.
        atom['eligible']=all(r['eligible'] for _,r in members) and '\x00' not in atom['text'] and not regex.search(r'\s',atom['text'].strip())
        groups[base['font']].append(atom)
    selected=set()
    for atoms in groups.values():
        lines=[]
        for atom in sorted(atoms,key=lambda a:(a['y'],a['x'])):
            line=next((line for line in reversed(lines[-3:]) if abs(line[0]['y']-atom['y'])<=max(line[0]['h'],atom['h'])*0.32 and abs(line[0]['h']-atom['h'])<max(1,atom['h']*.15)),None)
            if line is None:lines.append([atom])
            else:line.append(atom)
        for line in lines:
            text='';spans=[];right=None
            for atom in sorted(line,key=lambda a:a['x']):
                if right is not None and atom['x']-right>atom['h']*.18 and text and not text[-1].isspace():text+=' '
                start=len(text);text+=atom['text'];spans.append((start,len(text),atom));right=max(right or atom['right'],atom['right'])
            if '\x00' in text or regex.search(r'[=+<>∑∫√±×÷≤≥∞]|https?://|www\.|@|_',text):continue
            if regex.fullmatch(r'[A-Za-z]{1,4}',text):continue
            flags=text_flags(text)
            for start,end,atom in spans:
                if atom['eligible'] and any(flags[start:end]):selected.update(i for i,_ in atom['records'])
    return selected
