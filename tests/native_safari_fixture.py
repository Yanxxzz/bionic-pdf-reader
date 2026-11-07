"""Run a normal Safari window against original sample PDFs on a disposable Mac."""
import functools
import hashlib
import json
import socketserver
import subprocess
import threading
import time
import unicodedata
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import AppKit
import ApplicationServices as AX
import Quartz as Q
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'test-results'
OUT.mkdir(exist_ok=True)
events = []
report = {'cases': [], 'dialogs': []}

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/reader.html':
            body = (ROOT/'extension/reader.html').read_text().replace('</body>', '<script type="module" src="/observer.mjs"></script></body>').encode()
            mime = 'text/html; charset=utf-8'
        elif self.path == '/observer.mjs':
            body, mime = (ROOT/'tests/native_safari_observe.mjs').read_bytes(), 'text/javascript'
        elif self.path == '/control.html':
            body, mime = (ROOT/'tests/native_safari_control.html').read_bytes(), 'text/html'
        else:
            return super().do_GET()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != '/proof':
            return self.send_error(404)
        event = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        events.append(event)
        print('event', {k:v for k,v in event.items() if k not in ('selection','text')}, flush=True)
        self.send_response(204)
        self.end_headers()

class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address

def until(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.15)
    raise TimeoutError('Expected a native Safari event or system panel')

def event(kind, start=0, **expected):
    def find():
        for e in events[start:]:
            if e['kind'] == 'error':
                raise RuntimeError(e['message'])
            if e['kind'] == kind and all(e.get(k) == v for k,v in expected.items()):
                return e
    return until(find)

def front():
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return str(app.bundleIdentifier() or app.localizedName())

def click(x, y):
    assert front() == 'com.apple.Safari', front()
    for kind in (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp):
        e = Q.CGEventCreateMouseEvent(None, kind, (x, y), Q.kCGMouseButtonLeft)
        Q.CGEventSetIntegerValueField(e, Q.kCGMouseEventClickState, 1)
        Q.CGEventPost(Q.kCGHIDEventTap, e)
        time.sleep(.06)

def key(code, flags=0):
    assert front() in ('com.apple.Safari','com.apple.appkit.xpc.openAndSavePanelService'), front()
    for down in (True, False):
        e = Q.CGEventCreateKeyboardEvent(None, code, down)
        Q.CGEventSetFlags(e, flags)
        Q.CGEventPost(Q.kCGHIDEventTap, e)
        time.sleep(.06)

def onscreen():
    flags = Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements
    windows = Q.CGWindowListCopyWindowInfo(flags, Q.kCGNullWindowID) or []
    return [(str(w.get('kCGWindowOwnerName','')),str(w.get('kCGWindowName','')),int(w.get('kCGWindowLayer',0))) for w in windows]

def attr(element, name):
    err, value = AX.AXUIElementCopyAttributeValue(element, name, None)
    return value if err == 0 else None

def open_panel():
    apps = AppKit.NSWorkspace.sharedWorkspace().runningApplications()
    for app in apps:
        bundle = str(app.bundleIdentifier() or '')
        if bundle != 'com.apple.Safari' and 'openandsavepanel' not in bundle.lower():
            continue
        axapp = AX.AXUIElementCreateApplication(app.processIdentifier())
        queue = [(w,0) for w in (attr(axapp,'AXWindows') or [])]
        while queue:
            el, depth = queue.pop(0)
            role, subrole = attr(el,'AXRole'), attr(el,'AXSubrole')
            title = str(attr(el,'AXTitle') or '')
            if role == 'AXSheet' or subrole == 'AXDialog' or ('openandsavepanel' in bundle.lower() and role == 'AXWindow'):
                controls = [el]
                labels = []
                for _ in range(6):
                    labels.extend(str(attr(child,'AXTitle') or '') for child in controls if attr(child,'AXRole') == 'AXButton')
                    controls = [child for parent in controls for child in (attr(parent,'AXChildren') or [])]
                if 'Cancel' in labels and any(s in labels for s in ('Open','Choose','Select','Upload')):
                    return {'source':'AX','bundle':bundle,'role':str(role),'title':title,'buttons':labels}
            if depth < 4 and role != 'AXWebArea':
                queue.extend((c,depth+1) for c in (attr(el,'AXChildren') or []))
    for owner,title,layer in onscreen():
        if ('Open and Save Panel' in owner or owner=='Safari') and title in ('Open','Choose File','Choose Files','Select File'):
            return {'source':'WindowServer','owner':owner,'title':title}
    return None

def normalize(value):
    return ''.join(unicodedata.normalize('NFC',value).split())

def screen(name):
    subprocess.run(['screencapture','-x',str(OUT/(name+'.png'))],timeout=6,check=False)

def sample_screen(case, mode, sample):
    rect = sample['onscreen']
    assert min(rect[2:]) > 35, rect
    time.sleep(.35)
    path=OUT/f'{case}-{mode}.png'
    subprocess.run(['screencapture','-x','-R'+','.join(map(str,rect)),str(path)],check=True)
    return Image.open(path).convert('RGB')

def choose_path(path):
    key(5, Q.kCGEventFlagMaskCommand | Q.kCGEventFlagMaskShift)
    time.sleep(.6)
    pb = AppKit.NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(str(path),AppKit.NSPasteboardTypeString)
    key(9, Q.kCGEventFlagMaskCommand)
    time.sleep(.4)
    key(36)
    time.sleep(.65)
    key(36)

def run():
    url = f'http://127.0.0.1:{server.server_port}/reader.html'
    subprocess.run(['open','-a','Safari',url.replace('reader.html','control.html')],check=True)
    control=event('control')
    until(lambda:front() == 'com.apple.Safari')
    time.sleep(.4)
    x,y=control['patch']
    path=OUT/'control-color.png'
    subprocess.run(['screencapture','-x',f'-R{x},{y},10,10',str(path)],check=True)
    color=Image.open(path).convert('RGB').getpixel((4,4))
    report['unaidedControl']={'screenColor':color, 'visible':color[0]>150 and color[1]<90 and color[2]<125}
    click(*control['button'])
    try:
        panel=until(open_panel,25)
        plain=(ROOT/'.tmp/examples/shaped-tagged.pdf').resolve()
        choose_path(plain)
        proof=event('control-file',trusted=True,sha=hashlib.sha256(plain.read_bytes()).hexdigest())
        report['unaidedControl'].update(panel=panel,selected=proof)
    except TimeoutError:
        report['unaidedControl']['pickerTimedOut']=True
        screen('control-chooser-timeout')
    print('independent native HTML control',report['unaidedControl'],flush=True)
    subprocess.run(['open','-a','Safari',url],check=True)
    initial = event('ready')
    until(lambda:front() == 'com.apple.Safari')
    report.update({'ua':initial['ua'],'macOS':subprocess.check_output(['sw_vers','-productVersion'],text=True).strip(),
                   'postAccess':bool(Q.CGPreflightPostEventAccess()),'accessibility':bool(AX.AXIsProcessTrusted()),
                   'screenCapture':bool(Q.CGPreflightScreenCaptureAccess())})
    print('environment',report,flush=True)
    cases = json.loads((ROOT/'examples/shaping-cases.json').read_text())
    for variant in ('tagged','plain'):
        path = (ROOT/f'.tmp/examples/shaped-{variant}.pdf').resolve()
        assert path.is_file(), path
        start = len(events)
        click(initial['x'],initial['y'])
        physical = event('click',start,target='open-file',trusted=True)
        panel = until(open_panel,25)
        screen(variant+'-chooser')
        choose_path(path)
        file = event('file',start,name=path.name,trusted=True,sha=hashlib.sha256(path.read_bytes()).hexdigest())
        report['dialogs'].append({'variant':variant,'panel':panel,'file':file,'physicalClick':physical})
        for page,sample in enumerate(cases,1):
            if page > 1:
                start = len(events)
                key(124)
            original = event('render',start,page=page,mode='original',file=path.name)
            assert original['ink'] and original['count'] == 0
            case=f"{variant}-{sample['code']}"
            original_screen=sample_screen(case,'original',original)
            for field in ('text','selection'):
                assert normalize(sample['text']) in normalize(original[field]),(page,field,original)
            start = len(events)
            key(11,Q.kCGEventFlagMaskAlternate)
            bold = event('render',start,page=page,mode='bionic')
            assert bold['ink'] and bold['count']>0 and bold['pixels']!=original['pixels']
            assert bold['text']==original['text'] and bold['selection']==original['selection']
            bold_screen=sample_screen(case,'bionic',bold)
            start = len(events)
            key(11,Q.kCGEventFlagMaskAlternate)
            restored = event('render',start,page=page,mode='original')
            assert restored['pixels']==original['pixels']
            restored_screen=sample_screen(case,'restored',restored)
            screen_result={'inkPixels':sum(original_screen.convert('L').histogram()[:190]),
                'emphasisVisible': ImageChops.difference(original_screen,bold_screen).getbbox() is not None,
                'restored': ImageChops.difference(original_screen,restored_screen).getbbox() is None}
            report['cases'].append({'language':sample['code'],'variant':variant,'restored':True,'screen':screen_result})
            assert screen_result['inkPixels']>100 and screen_result['emphasisVisible'] and screen_result['restored'],(case,screen_result)
    report['passed'] = True

server = LocalServer(('127.0.0.1',0),functools.partial(Handler,directory=str(ROOT/'extension')))
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    run()
finally:
    report['front'] = front()
    report['windows'] = onscreen()
    report['events'] = events
    (OUT/'native-safari.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('final windows',report['front'],report['windows'],flush=True)
    screen('last-window')
    server.shutdown()
