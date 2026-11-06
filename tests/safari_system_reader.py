"""Real Safari acceptance through its system chooser and native keyboard."""
from pathlib import Path
import functools
import hashlib
import json
import subprocess
import threading
import time
import unicodedata
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
events=[];lock=threading.Lock()
class Handler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path=='/reader.html':
            data=(ROOT/'extension/reader.html').read_text(encoding='utf-8').replace('</body>','<script type="module" src="/acceptance-observer.mjs"></script></body>').encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(data)
        elif self.path=='/acceptance-observer.mjs':
            self.send_response(200);self.send_header('Content-Type','text/javascript');self.end_headers();self.wfile.write((ROOT/'tests/safari_system_observer.mjs').read_bytes())
        else:super().do_GET()
    def do_POST(self):
        if self.path!='/acceptance-report':self.send_error(404);return
        item=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with lock:events.append(item)
        self.send_response(204);self.end_headers()
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(ROOT/'extension')))
threading.Thread(target=server.serve_forever,daemon=True).start()
script=ROOT/'tests/safari_system_reader.applescript'
def action(name,*args):
    call=subprocess.run(['osascript',str(script),name,*map(str,args)],text=True,capture_output=True,timeout=90)
    print(name,call.stdout,call.stderr,flush=True)
    assert call.returncode==0,(name,call.stderr)
    return {'action':name,'stdout':call.stdout,'stderr':call.stderr}
def wait_for(predicate,after=0,timeout=60):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        with lock:found=next((e for e in reversed(events[after:]) if predicate(e)),None)
        if found:return found
        time.sleep(.1)
    raise AssertionError('Native Safari event not observed')
samples=json.loads((ROOT/'examples/shaping-cases.json').read_text(encoding='utf-8'))
normalize=lambda s:''.join(unicodedata.normalize('NFC',s).split())
report={'transport':'normal Safari, native Command+O, macOS system file dialog','cases':[],'dialogs':[]}
permission_log=(OUT/'macos-test-permissions.log').open('w',encoding='utf-8')
permission_helper=subprocess.Popen([str(ROOT/'.tmp/native-test-permissions')],stdout=permission_log,stderr=permission_log)
try:
    report['launch']=action('launch',f'http://127.0.0.1:{server.server_port}/reader.html')
    report['browser']=wait_for(lambda e:e['type']=='ready')
    report['macOS']=subprocess.check_output(['sw_vers','-productVersion'],text=True).strip()
    folder=Path.home()/'Downloads/BionicPDFAcceptance';folder.mkdir(parents=True,exist_ok=True)
    for variant in ('tagged','plain'):
        source=folder/f'native-{variant}.pdf';source.write_bytes((ROOT/f'.tmp/examples/shaped-{variant}.pdf').read_bytes())
        after=len(events)
        chooser=subprocess.Popen(['osascript',str(ROOT/'tests/safari_choose_file.applescript'),str(source),str(OUT/f'safari-system-dialog-{variant}.png')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        action('open')
        stdout,stderr=chooser.communicate(timeout=90)
        report['dialogs'].append({'returncode':chooser.returncode,'stdout':stdout,'stderr':stderr})
        print('system dialog',stdout,stderr,flush=True)
        assert chooser.returncode==0,report['dialogs'][-1]
        assert wait_for(lambda e:e['type']=='key' and e['code']=='KeyO' and e['meta'],after)['trusted'] is True
        selected=wait_for(lambda e:e['type']=='file' and e['name']==source.name,after)
        assert selected['trusted'] is True and selected['sha256']==hashlib.sha256(source.read_bytes()).hexdigest(),selected
        report['dialogs'][-1]['selected']=selected
        original=wait_for(lambda e:e['type']=='render' and e['name']==source.name and e['page']==1 and e['mode']=='original',after)
        for i,sample in enumerate(samples,1):
            if i>1:
                after=len(events);action('next');original=wait_for(lambda e:e['type']=='render' and e['page']==i and e['mode']=='original',after)
            assert normalize(sample['text']) in normalize(original['text']),(sample['code'],original)
            assert '\x00' not in original['text']
            after=len(events);action('toggle')
            active=wait_for(lambda e:e['type']=='render' and e['page']==i and e['mode']=='bionic',after)
            assert active['text']==original['text'] and active['pixels']!=original['pixels'] and active['boldGlyphs']>0
            assert any(e.get('type')=='key' and e.get('code')=='KeyB' and e.get('trusted') and e.get('alt') for e in events[after:])
            after=len(events);action('toggle');restored=wait_for(lambda e:e['type']=='render' and e['page']==i and e['mode']=='original',after)
            assert restored['pixels']==original['pixels'] and restored['scrollY']==0
            report['cases'].append({'variant':variant,'language':sample['code'],'page':i,'trustedFile':True,'originalPixelsRestored':True,'nativeKeyboardToggle':True})
            print(variant,sample['code'],'passed',flush=True)
        action('copy');time.sleep(.3)
        copied=subprocess.check_output(['pbpaste'],text=True)
        assert normalize(samples[-1]['text']) in normalize(copied),'Native clipboard lost Greek text'
        report['cases'][-1]['nativeClipboard']=True
    report['passed']=True
finally:
    (OUT/'safari-system-reader.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'safari-system-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
    subprocess.run(['screencapture','-x',str(OUT/'safari-system-final.png')],timeout=15)
    action('quit')
    server.shutdown()
    if permission_helper.poll() is None:permission_helper.terminate()
    permission_log.close()
