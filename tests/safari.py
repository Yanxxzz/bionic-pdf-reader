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
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results';OUT.mkdir(exist_ok=True)
class Handler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(ROOT/'extension')))
threading.Thread(target=server.serve_forever,daemon=True).start()
driver=webdriver.Safari();driver.set_window_size(1440,1040);wait=WebDriverWait(driver,60)
report=[]
step='starting'
samples=json.loads((ROOT/'examples/shaping-cases.json').read_text(encoding='utf-8'))
try:
    driver.get(f'http://127.0.0.1:{server.server_port}/reader.html')
    driver.execute_script("window.__readerErrors=[];addEventListener('error',e=>__readerErrors.push(e.message));addEventListener('unhandledrejection',e=>__readerErrors.push(String(e.reason)));const originalError=console.error.bind(console);console.error=(...args)=>{__readerErrors.push(args.map(String).join(' '));originalError(...args);};")
    for variant in ('tagged','plain'):
        driver.execute_script("for(const key of Object.keys(localStorage))if(key.startsWith('bionic-page-'))localStorage.removeItem(key);")
        previous=driver.execute_script("return document.querySelector('#page-frame').getAttribute('data-render-revision')")
        data=base64.b64encode((ROOT/f'.tmp/examples/shaped-{variant}.pdf').read_bytes()).decode()
        driver.execute_script("const bytes=Uint8Array.from(atob(arguments[0]),c=>c.charCodeAt(0));const dt=new DataTransfer();dt.items.add(new File([bytes],arguments[1],{type:'application/pdf'}));const input=document.querySelector('#file-input');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));",data,f'shaped-{variant}.pdf')
        wait.until(lambda d:d.execute_script("return document.querySelector('#page-frame').getAttribute('data-render-revision')")!=previous)
        for i,sample in enumerate(samples,1):
            step=f'{variant} / {sample["code"]} / original'
            if i>1:
                page_input=driver.find_element(By.ID,'page-number');page_input.clear();page_input.send_keys(str(i),Keys.ENTER)
            wait.until(lambda d:d.execute_script("const f=document.querySelector('#page-frame');return f.dataset.renderedPage===arguments[0]&&f.dataset.mode==='original'",str(i)))
            previous=driver.execute_script("return document.querySelector('#page-frame').dataset.renderRevision")
            Select(driver.find_element(By.ID,'language')).select_by_value(sample['code'])
            wait.until(lambda d:d.execute_script("return document.querySelector('#page-frame').dataset.renderRevision")!=previous)
            text=driver.execute_script("return document.querySelector('#text-layer').textContent")
            normalize=lambda s:''.join(unicodedata.normalize('NFC',s).split())
            assert normalize(sample['text']) in normalize(text),(sample['code'],'logical text',text)
            assert '\x00' not in text
            selected=driver.execute_script("const r=document.createRange();r.selectNodeContents(document.querySelector('#text-layer'));const s=getSelection();s.removeAllRanges();s.addRange(r);const value=s.toString();s.removeAllRanges();return value;")
            spaced=lambda s:' '.join(unicodedata.normalize('NFC',s).split())
            assert spaced(sample['text']) in spaced(selected),(sample['code'],'copy/selection',selected)
            original=driver.execute_script("return document.querySelector('#pdf-canvas').toDataURL()")
            step=f'{variant} / {sample["code"]} / enabling bionic'
            driver.find_element(By.ID,'bionic-mode').click()
            wait.until(lambda d:d.execute_script("return document.querySelector('#page-frame').dataset.mode==='bionic'"))
            assert driver.execute_script("return document.querySelector('#text-layer').textContent")==text
            assert driver.execute_script("return document.querySelector('#pdf-canvas').toDataURL()")!=original
            if variant=='tagged':driver.save_screenshot(str(OUT/f'safari-shaped-{sample["code"]}.png'))
            driver.find_element(By.ID,'original-mode').click()
            wait.until(lambda d:d.execute_script("return document.querySelector('#page-frame').dataset.mode==='original'"))
            assert driver.execute_script("return document.querySelector('#pdf-canvas').toDataURL()")==original
            report.append({'browser':'Safari','version':driver.capabilities.get('browserVersion'),'language':sample['code'],'variant':variant,'text':True,'selection':True,'originalPixelsRestored':True})
    print('Actual Safari: shaped text, selection and toggle checks passed')
except Exception:
    debug=driver.execute_script("return {errors:window.__readerErrors,frame:{...document.querySelector('#page-frame').dataset},status:document.querySelector('#reading-status').textContent,message:document.querySelector('#message').textContent,pressed:document.querySelector('#bionic-mode').getAttribute('aria-pressed'),active:document.activeElement?.outerHTML,ua:navigator.userAgent}")
    debug['step']=step;debug['capabilities']=driver.capabilities
    (OUT/'safari-failure.json').write_text(json.dumps(debug,ensure_ascii=False,indent=2),encoding='utf-8')
    driver.save_screenshot(str(OUT/'safari-failure.png'))
    print(json.dumps(debug,ensure_ascii=False,indent=2),flush=True)
    raise
finally:
    (OUT/'safari-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    driver.quit();server.shutdown()
