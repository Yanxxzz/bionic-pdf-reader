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
OUT = ROOT/'test-results'/os.environ.get('ACROBAT_ATTEMPT','primary')
OUT.mkdir(parents=True,exist_ok=True)
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

def keys(sequence):
    keyboard.send_keys(sequence,vk_packet=False)

def read(img):
    items,_ = engine(np.asarray(img))
    return [(str(text),int(box[0][0]),int(box[0][1]),int(box[2][0]),int(box[2][1])) for box,text,score in (items or [])]

def observed_page():
    deadline=time.monotonic()+50
    while time.monotonic()<deadline:
        foreground=gui.GetForegroundWindow()
        title=norm_title(foreground)
        if foreground!=hwnd and title in ('Adobe Acrobat','Welcome to Adobe Acrobat Reader'):
            print('Closing startup dialog',repr(title),flush=True)
            keys('{ESC}');time.sleep(.7)
            if gui.GetForegroundWindow()==foreground:
                keys('%{F4}');time.sleep(.7)
            continue
        img=screen(); items=read(img)
        labels=' '.join(canonical(t) for t,*_ in items)
        tip=next((row for row in items if canonical(row[0]).strip('.!') in ('ok','gotit','skipthetour','skiptour')),None)
        if tip:
            mouse.click(coords=((tip[1]+tip[3])//2,(tip[2]+tip[4])//2))
        elif 'welcometoacrobatreader' in labels and 'continue' in labels:
            button=next(row for row in items if row[0].strip().lower()=='continue')
            mouse.click(coords=((button[1]+button[3])//2,(button[2]+button[4])//2))
        elif 'defaultpdfapplication' in labels:
            button=next(row for row in items if row[0].strip().lower()=='no')
            mouse.click(coords=((button[1]+button[3])//2,(button[2]+button[4])//2))
        elif '7-dayfreetrial' in labels or 'trypremiumfeatures' in labels:
            assert img.size==(1024,768)
            mouse.click(coords=(909,80))  # Close the first-launch offer.
        elif 'pintoadobe' in labels or 'pintheadobe' in labels or 'yourtaskbar' in labels:
            button=next(row for row in items if 'nothanks' in re.sub('[^a-z]','',row[0].lower()))
            mouse.click(coords=((button[1]+button[3])//2,(button[2]+button[4])//2))
        elif np.asarray(img.crop((70,165,490,490)).convert('L')).mean()<85:
            # Acrobat dims its whole document while a startup web dialog is loading.
            # Wait for its actual contents or the native modal window above.
            time.sleep(.8)
            continue
        else:
            return img,items
        time.sleep(.5)
    raise RuntimeError('First-launch prompts still cover the native window')

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

def read_native_copy():
    cb.OpenClipboard()
    try:
        cb.EmptyClipboard();cb.SetClipboardText('waiting for native Acrobat copy',win32con.CF_UNICODETEXT)
    finally: cb.CloseClipboard()
    keys('^c')
    def fresh():
        value=clipboard_text()
        return value if value and value!='waiting for native Acrobat copy' else None
    return until(fresh,6)

def copy_selection(header):
    _,x0,y0,x1,y1=header
    start=(x0+8,(y0+y1)//2)
    end=(min(x0+345,490),start[1]+225)
    keys('{ESC}');mouse.click(coords=start);time.sleep(.35)
    mouse.press(coords=start)
    for step in range(1,9):
        mouse.move(coords=tuple(a+(b-a)*step//8 for a,b in zip(start,end)))
        time.sleep(.04)
    mouse.release(coords=end)
    copied=read_native_copy()
    keys('{ESC}');mouse.click(coords=(end[0],end[1]+8));mouse.move(coords=(730,485));time.sleep(.15)
    return copied

titles=re.compile(r'SHAPED\s+SAMPLE\s*/\s*([A-Z]{2})')

def page_header(items):
    return next((row for row in items if 'original' in canonical(row[0]) and ('shaped' in canonical(row[0]) or 'sample' in canonical(row[0]))),None)

def capture_page(index,sample,mode):
    for attempt in range(3):
        shot,items=observed_page()
        shot.save(OUT/(mode+'-'+sample['code']+'.png'))
        hdr=page_header(items)
        if not hdr:
            if attempt<2: time.sleep(.6);continue
            raise RuntimeError(f'Could not see page heading {index}: {items}')
        cursor=(hdr[1]+15,hdr[4]+18)
        try:
            text=copy_selection(hdr)
            if titles.findall(text)!=[sample['code'].upper()]:
                raise RuntimeError(f'Native selection on {mode}/{sample["code"]} contained {titles.findall(text)}')
        except RuntimeError:
            if attempt==2: raise
            screen().save(OUT/'copy-interrupted.png')
            continue
        (OUT/(mode+'-'+sample['code']+'.txt')).write_bytes(text.encode('utf-8'))
        assert len(text)>80 and 'Bionic PDF Reader' in text, (mode,sample['code'],repr(text))
        if mode=='on':
            old=(OUT/('off-'+sample['code']+'.txt')).read_bytes()
            assert old==text.encode('utf-8'), 'Clipboard text differs'
            # Limit the comparison to the PDF paragraphs, away from Acrobat's toolbar and cursor.
            from PIL import Image
            before=np.asarray(Image.open(OUT/('off-'+sample['code']+'.png')).convert('L'),dtype=np.int16)
            after=np.asarray(shot.convert('L'),dtype=np.int16)
            x,y=cursor
            rect=np.s_[y+6:y+135,max(0,x-16):min(x+385,498)]
            gain=int((before[rect]-after[rect]).sum())
            changed=int((np.abs(before[rect]-after[rect])>6).sum())
            assert gain>300 and changed>20,(sample['code'],gain,changed)
            report['pages'][sample['code']]={'nativeClipboardEqual':True,'changedPixels':changed,'extraInk':gain,
                'authoredPhrase':canonical(sample['text']) in canonical(text),'clipboardBytes':len(old)}
        print(mode,index,sample['code'],'passed',flush=True)
        return

def original_clipboard():
    original=source.with_name('shaped-tagged.pdf')
    subprocess.Popen([str(reader),'/n','/A','page=1&view=Fit',str(original)])
    def original_window():
        return next((h for h,t in adobe_windows() if 'multilingual' in t.lower() and 'switchable' not in t.lower()),None)
    target=until(original_window,35)
    window=Desktop(backend='win32').window(handle=target)
    window.maximize();window.set_focus();time.sleep(1)
    expected=[s['code'].upper() for s in samples]
    for attempt in range(4):
        keys('{ESC}');mouse.click(coords=(495,495));keys('^a');time.sleep(.4)
        if attempt: keys('^a');time.sleep(.3)
        value=read_native_copy()
        if titles.findall(value)==expected: break
        print('Original selection contained',titles.findall(value),flush=True)
    else:
        raise RuntimeError('Could not copy all 13 original pages through Acrobat')
    (OUT/'original-clipboard.txt').write_bytes(value.encode())
    blocks=re.split(r'(?=ORIGINAL SHAPED SAMPLE\s*/)',value)
    for sample,block in zip(samples,[b for b in blocks if titles.search(b)],strict=True):
        code=sample['code']
        if code not in report['pages']:
            continue
        actual=(OUT/f'off-{code}.txt').read_bytes().decode()
        same=block.rstrip('\r\n')==actual.rstrip('\r\n')
        report['pages'][code]['sourceClipboardEqual']=same
        if not same: errors.append((code,'original',repr(block[:290]),repr(actual[:290])))

try:
    assert reader.is_file(),reader
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception: pass
    engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    process=subprocess.Popen([str(reader),'/n','/A','page=1&view=Fit&pagemode=layers',str(source)])
    hwnd=until(main_doc,80)
    app=Desktop(backend='win32').window(handle=hwnd)
    app.maximize();app.set_focus();time.sleep(1)
    for attempt in range(12):
        first,items=observed_page()
        first.save(OUT/f'layer-setup-{attempt}.png')
        print('layer setup',attempt,'foreground',norm_title(gui.GetForegroundWindow()),
              'enabled',gui.IsWindowEnabled(hwnd),'point',norm_title(gui.GetAncestor(gui.WindowFromPoint((1000,269)),2)),
              'panel',[(t,x,y) for t,x,y,*_ in items if y<200 and (90<y or 'read' in t.lower())],flush=True)
        assert first.size==(1024,768)
        if not gui.IsWindowEnabled(hwnd):
            time.sleep(.7)
            continue
        app.set_focus();time.sleep(.3)
        left_open=any(x<45 and 90<y<125 and canonical(t) in ('alltools','read') for t,x,y,*_ in items)
        if left_open:
            mouse.move(coords=(261,108));time.sleep(.3);mouse.click(coords=(261,108));time.sleep(.8)
            continue
        if any('bionicreading' in canonical(t) for t,*_ in items):
            eye=layer_button(first,items)
            break
        mouse.click(coords=(1000,269));time.sleep(1)
    else:
        raise RuntimeError('Native Layers panel did not open')
    # Fit the complete page (not only its width) after the panel is open.
    mouse.click(coords=(490,505));keys('{ESC}');keys('^0');mouse.move(coords=(730,485));time.sleep(.8)
    first,items=observed_page();first.save(OUT/'acrobat-layers.png')
    docpoint=point_in_document(items)
    assert docpoint,items
    eye=layer_button(first,items)
    report['window']=norm_title(hwnd)
    report['layerEye']=eye
    errors=[]
    for index,sample in enumerate(samples,1):
        observed_page()
        if index>1:
            mouse.click(coords=(1000,557));time.sleep(.6) # Next page in the visible native navigation rail.
        mouse.move(coords=(730,485))
        for mode in ('off','on'):
            try: capture_page(index,sample,mode)
            except Exception as exc:
                errors.append((sample['code'],mode,str(exc)))
                print('Page diagnosis',errors[-1],flush=True)
            mouse.click(coords=eye);mouse.move(coords=(730,485));time.sleep(.45)
    report['errors']=errors
    original_clipboard()
    assert not errors,errors
    assert len(report['pages'])==13
    report['passed']=True
finally:
    report['windows']=adobe_windows()
    (OUT/'acrobat-native.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    screen().save(OUT/'acrobat-final.png')
    print('result',report,flush=True)
