"""Run the actual macOS Safari browser through Apple's supplied driver."""
from pathlib import Path
import base64
import functools
import json
import threading
import unicodedata
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
class Handler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(ROOT/'extension')))
threading.Thread(target=server.serve_forever,daemon=True).start()
driver=webdriver.Safari();driver.set_window_size(1440,1040);wait=WebDriverWait(driver,60)
report=[]
step='starting'
def activate_control(control):
    driver.execute_script("const e=document.getElementById(arguments[0]),r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);if(!r.width||!r.height||e.disabled||!(hit===e||e.contains(hit)))throw new Error('Control is covered: '+arguments[0]);e.click();",control)
samples=json.loads((ROOT/'examples/shaping-cases.json').read_text(encoding='utf-8'))
try:
    driver.get(f'http://127.0.0.1:{server.server_port}/reader.html')
    driver.execute_script("window.__readerErrors=[];addEventListener('error',e=>__readerErrors.push(e.message));addEventListener('unhandledrejection',e=>__readerErrors.push(String(e.reason)));const originalError=console.error.bind(console);console.error=(...args)=>{__readerErrors.push(args.map(String).join(' '));originalError(...args);};")
    wait.until(lambda d:d.execute_script("return document.documentElement.dataset.readerReady==='true'"))
    # Isolate native-driver file access from the reader. SafariDriver builds
    # can select a path without granting WebContent permission to read it.
    probe_path=ROOT/'.tmp/examples/native-probe.pdf'
    probe_path.write_bytes((ROOT/'.tmp/examples/shaped-tagged.pdf').read_bytes())
    driver.execute_script("const i=document.createElement('input');i.type='file';i.id='native-file-probe';i.hidden=true;i.accept='application/pdf,.pdf';document.body.append(i);")
    driver.find_element(By.ID,'native-file-probe').send_keys(str(probe_path))
    native=driver.execute_async_script("""
      const done=arguments[arguments.length-1],file=document.querySelector('#native-file-probe').files[0];
      (async()=>{
        const result={};
        try{result.arrayBuffer={ok:true,bytes:(await file.arrayBuffer()).byteLength};}
        catch(e){result.arrayBuffer={ok:false,error:e.name+': '+e.message};}
        result.fileReader=await new Promise(resolve=>{const r=new FileReader();r.onload=()=>resolve({ok:true,bytes:r.result.byteLength});r.onerror=()=>resolve({ok:false,error:r.error.name+': '+r.error.message});r.readAsArrayBuffer(file);});
        document.querySelector('#native-file-probe').remove();done(result);
      })().catch(e=>done({error:String(e)}));
    """)
    transport='native-file-input' if native.get('arrayBuffer',{}).get('ok') else 'memory-file-input'
    environment={'browserVersion':driver.capabilities.get('browserVersion'),'nativeFileProbe':native,'transport':transport,'controls':'DOM activation with visible hit-target checks; native OS clicks not covered'}
    (OUT/'safari-environment.json').write_text(json.dumps(environment,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Safari file access probe:',json.dumps(environment),flush=True)
    for variant in ('tagged','plain'):
        step=f'opening {variant}'
        driver.execute_script("for(const key of Object.keys(localStorage))if(key.startsWith('bionic-page-'))localStorage.removeItem(key);")
        previous=driver.execute_script("return document.querySelector('#page-frame').getAttribute('data-render-revision')")
        source=ROOT/f'.tmp/examples/shaped-{variant}.pdf'
        if transport=='native-file-input':driver.find_element(By.ID,'file-input').send_keys(str(source))
        else:
            data=base64.b64encode(source.read_bytes()).decode()
            driver.execute_script("const bytes=Uint8Array.from(atob(arguments[0]),c=>c.charCodeAt(0)),dt=new DataTransfer();dt.items.add(new File([bytes],arguments[1],{type:'application/pdf'}));const input=document.querySelector('#file-input');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));",data,source.name)
        wait.until(lambda d:d.execute_script("return document.querySelector('#page-frame').getAttribute('data-render-revision')")!=previous)
        for i,sample in enumerate(samples,1):
            step=f'{variant} / {sample["code"]} / original'
            if i>1:
                driver.execute_script("const e=document.querySelector('#page-number');e.value=arguments[0];e.dispatchEvent(new Event('change',{bubbles:true}));",str(i))
            wait.until(lambda d:d.execute_script("const f=document.querySelector('#page-frame');return f.dataset.renderedPage===arguments[0]&&f.dataset.mode==='original'",str(i)))
            previous=driver.execute_script("return document.querySelector('#page-frame').dataset.renderRevision")
            driver.execute_script("const e=document.querySelector('#language');e.value=arguments[0];e.dispatchEvent(new Event('change',{bubbles:true}));",sample['code'])
            wait.until(lambda d:d.execute_script("return document.querySelector('#page-frame').dataset.renderRevision")!=previous)
            text=driver.execute_script("return document.querySelector('#text-layer').textContent")
            normalize=lambda s:''.join(unicodedata.normalize('NFC',s).split())
            assert normalize(sample['text']) in normalize(text),(sample['code'],'logical text',text)
            assert '\x00' not in text
            selected=driver.execute_script("const r=document.createRange();r.selectNodeContents(document.querySelector('#text-layer'));const s=getSelection();s.removeAllRanges();s.addRange(r);const value=s.toString();s.removeAllRanges();return value;")
            spaced=lambda s:' '.join(unicodedata.normalize('NFC',s).split())
            assert spaced(sample['text']) in spaced(selected),(sample['code'],'copy/selection',selected)
            assert driver.execute_script('return window.scrollY')==0,'Selecting PDF text must not scroll the application toolbar out of view'
            original=driver.execute_script("return document.querySelector('#pdf-canvas').toDataURL()")
            step=f'{variant} / {sample["code"]} / enabling bionic'
            activate_control('bionic-mode')
            wait.until(lambda d:d.execute_script("return document.querySelector('#page-frame').dataset.mode==='bionic'"))
            assert driver.execute_script("return document.querySelector('#text-layer').textContent")==text
            assert driver.execute_script("return document.querySelector('#pdf-canvas').toDataURL()")!=original
            if variant=='tagged':driver.save_screenshot(str(OUT/f'safari-shaped-{sample["code"]}.png'))
            activate_control('original-mode')
            wait.until(lambda d:d.execute_script("return document.querySelector('#page-frame').dataset.mode==='original'"))
            assert driver.execute_script("return document.querySelector('#pdf-canvas').toDataURL()")==original
            report.append({'browser':'Safari','version':driver.capabilities.get('browserVersion'),'language':sample['code'],'variant':variant,'text':True,'selection':True,'originalPixelsRestored':True,'transport':transport})
            print('Safari',variant,sample['code'],'passed',flush=True)
    print('Actual Safari: shaped text, selection and toggle checks passed')
except Exception:
    debug=driver.execute_script("return {errors:window.__readerErrors,ready:document.documentElement.dataset.readerReady,frame:{...document.querySelector('#page-frame').dataset},status:document.querySelector('#reading-status').textContent,message:document.querySelector('#message').textContent,pressed:document.querySelector('#bionic-mode').getAttribute('aria-pressed'),active:document.activeElement?.tagName+'#'+document.activeElement?.id,scroll:{x:scrollX,y:scrollY,height:document.documentElement.scrollHeight,viewport:innerHeight},toolbar:document.querySelector('#bionic-mode').getBoundingClientRect().toJSON(),ua:navigator.userAgent}")
    debug['step']=step;debug['capabilities']=driver.capabilities
    (OUT/'safari-failure.json').write_text(json.dumps(debug,ensure_ascii=False,indent=2),encoding='utf-8')
    driver.save_screenshot(str(OUT/'safari-failure.png'))
    print(json.dumps(debug,ensure_ascii=False,indent=2),flush=True)
    raise
finally:
    (OUT/'safari-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    driver.quit();server.shutdown()
