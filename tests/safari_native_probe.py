"""Diagnose real Safari file selection using disk files, without synthetic Files."""
from pathlib import Path
import functools
import hashlib
import json
import subprocess
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
source=ROOT/'.tmp/examples/shaped-tagged.pdf'
data=source.read_bytes();expected=hashlib.sha256(data).hexdigest()
places={'workspace':ROOT/'.tmp/examples/native-source.pdf','downloads':Path.home()/'Downloads/BionicPDFAcceptance/native-source.pdf','temporary':Path(tempfile.mkdtemp(prefix='bionic-native-'))/'native-source.pdf'}
for path in places.values():path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
class Handler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(ROOT/'extension')))
threading.Thread(target=server.serve_forever,daemon=True).start()
driver=webdriver.Safari();driver.set_window_size(1440,1040);driver.set_script_timeout(30)
report={'browser':driver.capabilities,'expectedSha256':expected,'files':[]}
try:
    driver.get(f'http://127.0.0.1:{server.server_port}/reader.html')
    WebDriverWait(driver,60).until(lambda d:d.execute_script("return document.documentElement.dataset.readerReady==='true'"))
    activation=subprocess.run(['osascript','-e','tell application "Safari" to activate'],capture_output=True,text=True,timeout=15)
    ax=subprocess.run(['osascript','-e','tell application "System Events" to get UI elements enabled'],capture_output=True,text=True,timeout=15)
    report['activation']={'returncode':activation.returncode,'stderr':activation.stderr}
    report['accessibility']={'returncode':ax.returncode,'stdout':ax.stdout,'stderr':ax.stderr}
    driver.execute_script("const b=document.createElement('button');b.id='native-click-probe';b.textContent='Native input check';b.style='position:fixed;bottom:0;right:0;z-index:1000';b.onclick=e=>{window.__nativeClicked={trusted:e.isTrusted,time:Date.now()};};document.body.append(b);")
    driver.find_element(By.ID,'native-click-probe').click()
    report['nativeClick']=driver.execute_script('return window.__nativeClicked||null')
    driver.execute_script("document.querySelector('#native-click-probe').remove();")
    for label,path in places.items():
        for hidden in (False,True):
            driver.execute_script("document.querySelector('#disk-probe')?.remove();const i=document.createElement('input');i.type='file';i.id='disk-probe';i.accept='application/pdf,.pdf';i.hidden=arguments[0];i.style='position:fixed;bottom:0;left:0;z-index:1000';document.body.append(i);",hidden)
            driver.find_element(By.ID,'disk-probe').send_keys(str(path))
            result=driver.execute_async_script("""
                const done=arguments[arguments.length-1],file=document.querySelector('#disk-probe').files[0];
                (async()=>{const r={name:file?.name,size:file?.size,type:file?.type};
                try{const bytes=await file.arrayBuffer();r.arrayBuffer={ok:true,bytes:bytes.byteLength,sha256:[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('')};}
                catch(e){r.arrayBuffer={ok:false,error:e.name+': '+e.message};}
                r.fileReader=await new Promise(resolve=>{const f=new FileReader();f.onload=()=>resolve({ok:true,bytes:f.result.byteLength});f.onerror=()=>resolve({ok:false,error:f.error.name+': '+f.error.message});f.readAsArrayBuffer(file);});done(r);})().catch(e=>done({error:String(e)}));
            """)
            result.update(location=label,hidden=hidden);report['files'].append(result)
            print(json.dumps(result),flush=True)
    driver.save_screenshot(str(OUT/'safari-native-probe.png'))
finally:
    (OUT/'safari-native-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    driver.quit();server.shutdown()
