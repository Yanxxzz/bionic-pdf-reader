"""Exercise an installed Reader on the CI machine's interactive desktop."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import unicodedata

import cv2
import numpy as np
from PIL import ImageGrab
import win32clipboard as cb
import win32gui as gui
import win32con
import win32process
from pywinauto import Desktop, keyboard, mouse
from rapidocr_onnxruntime import RapidOCR

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'test-results'
OUT.mkdir(exist_ok=True)
source = ROOT/'.tmp/examples/shaped-switchable.pdf'
reader = Path(os.environ['ProgramFiles'])/'Adobe/Acrobat DC/Acrobat/Acrobat.exe'
samples = json.loads((ROOT/'examples/shaping-cases.json').read_text(encoding='utf-8'))
report = {'source': source.name, 'sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'pages':{}}

def canonical(s):
    return ''.join(unicodedata.normalize('NFC',s).split()).casefold()

def norm_title(hwnd):
    return gui.GetWindowText(hwnd)

def adobe_windows():
    ids = []
    gui.EnumWindows(lambda hwnd, _: ids.append(hwnd) if gui.IsWindowVisible(hwnd) else None, None)
    return [(h,norm_title(h)) for h in ids if 'acrobat' in norm_title(h).lower() or gui.GetClassName(h)=='AcrobatSDIWindow']

def until(fn, timeout=25):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        item = fn()
        if item: return item
        time.sleep(.3)
    raise RuntimeError('Timed out waiting for '+getattr(fn,'__name__','Acrobat'))

def main_doc():
    return next((h for h,t in adobe_windows() if 'switchable' in t.lower() or 'multilingual' in t.lower()),None)

def screen():
    return ImageGrab.grab().convert('RGB')

def read(img):
    items,_ = engine(np.asarray(img))
    return [(str(text),int(box[0][0]),int(box[0][1]),int(box[2][0]),int(box[2][1])) for box,text,score in (items or [])]

def observed_page():
    img=screen(); items=read(img)
    if any('defaultpdfapplication' in canonical(t) for t,*_ in items):
        no = next(row for row in items if row[0].strip().lower() == 'no')
        mouse.click(coords=((no[1]+no[3])//2,(no[2]+no[4])//2))
        time.sleep(.6)
        img=screen(); items=read(img)
    return img,items

def point_in_document(items):
    hdr = next((x for x in items if 'shaped' in canonical(x[0]) and 'sample' in canonical(x[0])),None)
    if hdr: return (hdr[1]+15,hdr[4]+18)
    return None

def layer_button(img, items):
    for text,x0,y0,x1,y1 in items:
        if 'bionicreading' not in canonical(text): continue
        center = (y0+y1)//2
        left,top = max(0,x0-130),max(0,center-14)
        crop = np.array(img.crop((left,top,max(x0+1,left+1),center+15)).convert('L'))
        edges = cv2.Canny(crop,40,150)
        contours,_= cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            x,y,w,h = cv2.boundingRect(contour)
            if 10<=w<=25 and 9<=h<=25 and abs(w-h)<=3 and abs(top+y+h/2-center)<9:
                boxes.append((abs(top+y+h/2-center),-(x+w),left+x+w//2,top+y+h//2))
        if boxes:
            return min(boxes)[2:]
    raise RuntimeError('Could not locate the layer eye next to Bionic Reading')

def clipboard_text():
    cb.OpenClipboard()
    try:
        return cb.GetClipboardData(win32con.CF_UNICODETEXT) if cb.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT) else ''
    finally:
        cb.CloseClipboard()

def copy_selection():
    cb.OpenClipboard()
    try:
        cb.EmptyClipboard();cb.SetClipboardText('waiting for native Acrobat copy',win32con.CF_UNICODETEXT)
    finally: cb.CloseClipboard()
    keyboard.send_keys('^a');time.sleep(.25);keyboard.send_keys('^c')
    copied=until(lambda: (v if 'shaped' in v.lower() else None) if (v:=clipboard_text()) else None,7)
    keyboard.send_keys('{ESC}');time.sleep(.15)
    return copied

def page_id(items,code):
    return any('sample' in t.lower() and re.sub(r'[^a-z]', '', t.lower()).endswith(code) for t,*_ in items)

def capture_pass(mode):
    mouse.click(coords=docpoint)
    keyboard.send_keys('^{HOME}');time.sleep(.6)
    for index,sample in enumerate(samples,1):
        if index>1:
            keyboard.send_keys('{RIGHT}');time.sleep(.5)
        shot,items=observed_page()
        shot.save(OUT/(mode+'-'+sample['code']+'.png'))
        if not page_id(items,sample['code']):
            raise RuntimeError(f'Expected page {index} ({sample["code"]}), screen text: {items}')
        cursor=point_in_document(items)
        mouse.click(coords=cursor)
        text=copy_selection()
        assert canonical(sample['text']) in canonical(text), (mode,sample['code'],repr(text[:300]))
        (OUT/(mode+'-'+sample['code']+'.txt')).write_bytes(text.encode('utf-8'))
        if mode=='on':
            old=(OUT/('off-'+sample['code']+'.txt')).read_bytes()
            assert old==text.encode('utf-8'), 'Clipboard text differs'
            # Limit the comparison to the PDF paragraphs, away from Acrobat's toolbar and cursor.
            from PIL import Image
            before=np.asarray(Image.open(OUT/('off-'+sample['code']+'.png')).convert('L'),dtype=np.int16)
            after=np.asarray(shot.convert('L'),dtype=np.int16)
            x,y=cursor
            rect=np.s_[y+6:y+135,max(0,x-16):min(x+540,before.shape[1])]
            gain=int((before[rect]-after[rect]).sum())
            changed=int((np.abs(before[rect]-after[rect])>6).sum())
            assert gain>300 and changed>20,(sample['code'],gain,changed)
            report['pages'][sample['code']]={'nativeClipboardEqual':True,'changedPixels':changed,'extraInk':gain}
        print(mode,index,sample['code'],'passed',flush=True)

try:
    assert reader.is_file(),reader
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception: pass
    engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    process=subprocess.Popen([str(reader),'/n','/A','page=1&view=Fit&pagemode=layers',str(source)])
    hwnd=until(main_doc,80)
    app=Desktop(backend='win32').window(handle=hwnd)
    app.maximize();app.set_focus();time.sleep(1)
    keyboard.send_keys('^0');time.sleep(1)
    first=screen();first.save(OUT/'acrobat-start.png')
    items=read(first)
    print('initial text',items,flush=True)
    if not any('bionicreading' in canonical(t) for t,*_ in items):
        # The installed version starts in the new UI with All tools open and
        # Layers collapsed in the right navigation rail (verified on this desktop).
        assert first.size == (1024,768) and any('alltools' in canonical(t) for t,*_ in items)
        mouse.click(coords=(261,108));time.sleep(.4)
        mouse.click(coords=(1000,269));time.sleep(.8)
        keyboard.send_keys('^0');time.sleep(.5)
        first=screen();first.save(OUT/'acrobat-layers.png')
        items=read(first)
        print('layer panel',items,flush=True)
    docpoint=point_in_document(items)
    assert docpoint,items
    eye=layer_button(first,items)
    report['window']=norm_title(hwnd)
    report['layerEye']=eye
    capture_pass('off')
    mouse.click(coords=eye);time.sleep(.6)
    capture_pass('on')
    assert len(report['pages'])==13
    report['passed']=True
finally:
    report['windows']=adobe_windows()
    (OUT/'acrobat-native.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    screen().save(OUT/'acrobat-final.png')
    print('result',report,flush=True)
