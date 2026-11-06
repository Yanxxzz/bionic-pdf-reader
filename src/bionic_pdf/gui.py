"""Local graphical launcher for the WPS reading-copy generator."""
import os
import sys
import threading
import queue
import contextlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from .converter import make_pdf

class ProgressWriter:
    def __init__(self, events): self.events, self.buffer = events, ''
    def write(self, text):
        self.buffer += text
        while '\n' in self.buffer:
            line,self.buffer = self.buffer.split('\n',1)
            if line: self.events.put(('progress',line))
        return len(text)
    def flush(self): pass

class Maker:
    def __init__(self, root):
        self.root, self.events, self.busy = root, queue.Queue(), False
        self.result = None
        self.mode = tk.StringVar(value='可切换版 · WPS / Acrobat / Foxit')
        self.locale = tk.StringVar(value='auto')
        self.source, self.target, self.status = tk.StringVar(),tk.StringVar(),tk.StringVar(value='选择原始 PDF，按阅读器选择可切换版或普通仿生版。')
        root.title('Bionic PDF · 仿生阅读制作工具')
        root.geometry('760x550'); root.minsize(700,530)
        root.configure(bg='#f3f6ef')
        style = ttk.Style(); style.theme_use('clam')
        style.configure('TFrame',background='#f3f6ef')
        style.configure('TLabel',background='#f3f6ef',foreground='#29453b',font=('Microsoft YaHei UI',10))
        style.configure('TButton',font=('Microsoft YaHei UI',10),padding=8)
        frame = ttk.Frame(root,padding=28); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='让 PDF 阅读多一个选择',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        ttk.Label(frame,text='保留正文和页码，打开副本后可随时开关词首加粗。').pack(anchor='w',pady=(9,22))
        self.path_row(frame,'原始 PDF',self.source,self.pick_source)
        self.path_row(frame,'阅读副本',self.target,self.pick_target)
        options = ttk.Frame(frame); options.pack(fill='x',pady=(16,0))
        ttk.Label(options,text='阅读方式',width=9).pack(side='left')
        ttk.Combobox(options,textvariable=self.mode,state='readonly',width=34,values=['可切换版 · WPS / Acrobat / Foxit','普通仿生版 · 其他 PDF 阅读器']).pack(side='left')
        language = ttk.Frame(frame); language.pack(fill='x',pady=(12,0))
        ttk.Label(language,text='文档语言',width=9).pack(side='left')
        ttk.Combobox(language,textvariable=self.locale,state='readonly',width=12,values=['auto','en','fr','de','es','pt','it','ru','el','zh','ja','ko','ar','he','hi']).pack(side='left')
        ttk.Label(language,text='auto 自动；中日韩及复杂文字为试验支持。').pack(side='left',padx=12)
        self.progress = ttk.Progressbar(frame,maximum=100); self.progress.pack(fill='x',pady=(18,10))
        ttk.Label(frame,textvariable=self.status,wraplength=650).pack(anchor='w')
        controls = ttk.Frame(frame);controls.pack(fill='x',pady=(22,0))
        self.generate = ttk.Button(controls,text='生成阅读副本',command=self.start);self.generate.pack(side='left')
        self.open_button = ttk.Button(controls,text='打开阅读副本',command=self.open_result,state='disabled');self.open_button.pack(side='left',padx=12)
        ttk.Button(controls,text='在浏览器中阅读',command=self.open_reader).pack(side='left')
        ttk.Label(frame,text='可切换版：在阅读器“图层”列表开关。普通版：打开即显示词首加粗。',font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(18,0))
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(120,self.poll)
    def path_row(self,parent,label,variable,command):
        row = ttk.Frame(parent);row.pack(fill='x',pady=5)
        ttk.Label(row,text=label,width=9).pack(side='left')
        ttk.Entry(row,textvariable=variable).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='选择…',command=command).pack(side='left',padx=(8,0))
    def pick_source(self):
        if self.busy:return
        name = filedialog.askopenfilename(title='选择原始 PDF',filetypes=[('PDF 文档','*.pdf')])
        if name:
            self.source.set(name)
            path=Path(name);self.target.set(str(path.with_name(path.stem+'_仿生阅读.pdf')))
    def pick_target(self):
        if self.busy:return
        name=filedialog.asksaveasfilename(title='保存阅读副本',defaultextension='.pdf',filetypes=[('PDF 文档','*.pdf')],initialfile=Path(self.target.get()).name if self.target.get() else 'WPS可切换阅读.pdf')
        if name:self.target.set(name)
    def start(self):
        if self.busy:return
        if not self.target.get().strip():messagebox.showinfo('请选择保存位置','请为阅读副本选择保存位置。');return
        source,target=Path(self.source.get()),Path(self.target.get())
        if not source.is_file() or source.suffix.lower()!='.pdf':messagebox.showinfo('请选择 PDF','请先选择原始 PDF。');return
        if source.resolve()==target.resolve():messagebox.showinfo('请保留原文件','请给阅读副本选择不同文件名。');return
        if target.exists() and not messagebox.askyesno('替换阅读副本','目标文件已存在，是否替换这份阅读副本？'):return
        mode = 'static' if self.mode.get().startswith('普通') else 'switchable'
        locale = self.locale.get()
        self.busy=True;self.generate.config(state='disabled');self.open_button.config(state='disabled');self.progress['value']=0
        self.status.set('正在准备字体和页面…')
        def work():
            try:
                with contextlib.redirect_stdout(ProgressWriter(self.events)):
                    report=make_pdf(source,target,mode=mode,locale=locale)
                self.events.put(('done',(report,target)))
            except Exception as error:self.events.put(('error',str(error)))
        threading.Thread(target=work,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,payload=self.events.get_nowait()
                if kind=='progress' and payload.startswith('PROGRESS '):
                    current,total=map(int,payload.split()[1].split('/'));self.progress['value']=100*current/total;self.status.set(f'已处理 {current} / {total} 页…')
                elif kind=='done':
                    payload,self.result=payload
                    self.busy=False;self.generate.config(state='normal');self.open_button.config(state='normal');self.progress['value']=100
                    self.status.set(f'完成，共 {payload["pages"]} 页。' + ('可在阅读器“图层”列表开关。' if payload['mode']=='switchable' else '打开即显示加粗，可用于没有图层开关的阅读器。'))
                elif kind=='error':
                    self.busy=False;self.generate.config(state='normal');self.status.set('未生成副本，原始文件保留。');messagebox.showerror('无法生成阅读副本',payload)
        except queue.Empty:pass
        self.root.after(120,self.poll)
    def open_result(self):
        target=self.result
        if target is None:return
        if not target.is_file():return
        if sys.platform == 'win32': os.startfile(str(target))
        else:
            import subprocess
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open',str(target)])
    def close(self):
        if self.busy:
            messagebox.showinfo('正在生成','请等当前副本生成结束后再关闭。');return
        self.root.destroy()
    def open_reader(self):
        import webbrowser
        from .local_reader import start_reader
        try: webbrowser.open_new_tab(start_reader())
        except OSError as error:messagebox.showerror('无法打开阅读器',str(error))

def main():
    window=tk.Tk();Maker(window);window.mainloop()

if __name__ == "__main__":
    main()
