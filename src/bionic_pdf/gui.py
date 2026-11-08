"""Local graphical launcher for the WPS reading-copy generator."""
import os
import sys
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from .converter import make_pdf, page_summary
from .document import SignatureLossError
from .words import LANGUAGES

class Maker:
    def __init__(self, root):
        self.root, self.events, self.busy = root, queue.Queue(), False
        self.result = None
        self.mode = tk.StringVar(value='可切换版 · WPS / Acrobat / Foxit')
        self.language_options={'自动分词 · auto':'auto',**{f'{name} · {code}':code for code,name in LANGUAGES.items()}}
        self.locale = tk.StringVar(value='自动分词 · auto')
        self.source, self.target, self.status = tk.StringVar(),tk.StringVar(),tk.StringVar(value='选择原始 PDF，按阅读器选择可切换版或普通仿生版。')
        root.title('Bionic PDF · 仿生阅读制作工具')
        root.geometry('760x650'); root.minsize(700,630)
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
        ttk.Combobox(language,textvariable=self.locale,state='readonly',width=24,values=list(self.language_options)).pack(side='left')
        ttk.Label(language,text='英语用参考规则，自动及其他语言加粗前半词。').pack(side='left',padx=12)
        self.progress = ttk.Progressbar(frame,maximum=100); self.progress.pack(fill='x',pady=(18,10))
        self.status_line = ttk.Label(frame,textvariable=self.status,wraplength=650)
        self.status_line.pack(anchor='w')
        self.page_details = tk.StringVar()
        self.page_list = ttk.Entry(frame,textvariable=self.page_details,state='readonly')
        controls = ttk.Frame(frame);controls.pack(fill='x',pady=(22,0))
        self.generate = ttk.Button(controls,text='生成阅读副本',command=self.start);self.generate.pack(side='left')
        self.open_button = ttk.Button(controls,text='打开阅读副本',command=self.open_result,state='disabled');self.open_button.pack(side='left',padx=12)
        ttk.Button(controls,text='在浏览器中阅读',command=self.open_reader).pack(side='left')
        ttk.Label(frame,text='可切换版：在阅读器“图层”列表开关。普通版：打开即显示词首加粗。',font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(18,0))
        ttk.Button(frame,text='使用指南与配置说明',command=self.show_help).pack(anchor='w',pady=(10,0))
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
        locale = self.language_options[self.locale.get()]
        self.busy=True;self.generate.config(state='disabled');self.open_button.config(state='disabled');self.progress['value']=0
        self.status.set('正在准备字体和页面…')
        self.page_list.pack_forget()
        def work(allow_signature_loss):
            try:
                report=make_pdf(source,target,mode=mode,locale=locale,
                    allow_signature_loss=allow_signature_loss,
                    progress=lambda current,total:self.events.put(('progress',(current,total))))
                self.events.put(('done',(report,target)))
            except SignatureLossError:
                self.events.put(('signature', launch))
            except Exception as error:self.events.put(('error',str(error)))
        def launch(allow_signature_loss=False):
            threading.Thread(target=work,args=(allow_signature_loss,),daemon=True).start()
        launch()
    def poll(self):
        try:
            while True:
                kind,payload=self.events.get_nowait()
                if kind=='progress':
                    current,total=payload
                    self.progress['value']=100*current/total;self.status.set(f'已处理 {current} / {total} 页…')
                elif kind=='signature':
                    if messagebox.askyesno('导出会使数字签名失效',
                            SignatureLossError.message + '\n\n仍要生成仅供阅读的副本吗？选择“否”后可在浏览器中阅读原件。',
                            default=messagebox.NO, parent=self.root):
                        payload(True)
                    else:
                        self.busy=False;self.generate.config(state='normal')
                        self.status.set('已取消导出。可点击「在浏览器中阅读」打开已签名的原件。')
                elif kind=='done':
                    payload,self.result=payload
                    self.busy=False;self.generate.config(state='normal');self.open_button.config(state='normal');self.progress['value']=100
                    summary = page_summary(payload['unemphasized_pages'])
                    if len(summary) > 80:
                        self.page_details.set(summary)
                        self.page_list.pack(fill='x', after=self.status_line)
                        summary = f'其中 {len(payload["unemphasized_pages"])} 页未加粗，可在下方选中并复制页码。'
                    self.status.set(f'完成，共 {payload["pages"]} 页。' + summary)
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
        try:
            if not webbrowser.open_new_tab(start_reader(self.source.get())):
                raise OSError('无法启动默认浏览器。')
        except OSError as error:messagebox.showerror('无法打开阅读器',str(error))
    def show_help(self):
        window=tk.Toplevel(self.root);window.title('使用指南与配置说明');window.geometry('680x520');window.minsize(580,420)
        text=tk.Text(window,wrap='word',font=('Microsoft YaHei UI',10),padx=22,pady=18)
        scrollbar=ttk.Scrollbar(window,command=text.yview);scrollbar.pack(side='right',fill='y');text.configure(yscrollcommand=scrollbar.set);text.pack(fill='both',expand=True)
        text.insert('1.0',HELP_TEXT);text.configure(state='disabled')
        ttk.Button(window,text='关闭指南',command=window.destroy).pack(pady=10)

HELP_TEXT='''选择你的阅读方式

• 点击「在浏览器中阅读」即可打开已选的原始 PDF。也可以在浏览器中选文件。点击顶部「原始 / 仿生」或按 Alt+B 切换。在侧栏调整语言、规则和强度，窄窗口中先展开「阅读设置与目录」。使用期间保持制作工具开启。

• WPS / Acrobat / Foxit / PDF-XChange：选择「可切换版」，生成后打开副本。在「图层 / Layers」面板开关「仿生阅读 · Bionic Reading」。默认关闭，开关时页码和缩放保持原位。
  WPS：左侧图层图标 → 眼睛开关。
  PDF-XChange：Ctrl+L 打开图层 → 点击灯泡。
  Acrobat：菜单 → 视图 → 显示/隐藏 → 侧面板 → 图层。
  Foxit：在左侧导航栏空白处右键 → 图层，再勾选该图层。

• Preview / SumatraPDF / 手机阅读器：选择「普通仿生版」。打开副本即可显示加粗；要看原始效果，打开原文件。

制作步骤
1. 选择原始 PDF。
2. 选择新的保存文件名。
3. 选择阅读方式与文档语言，然后生成。
4. 查看未加粗的副本页码，点击「打开阅读副本」。双页讲义的左右两半合计一页。
已有数字签名时，工具会在导出前提示。选择「否」可在浏览器中阅读原件，选择「是」生成的副本会失去原签名的效力。

语言与配置
支持英语、法语、德语、西班牙语、葡萄牙语、意大利语、荷兰语、波兰语、土耳其语、越南语、俄语、乌克兰语、希腊语。
制作副本时，选英语会对纯英文字母词应用参考规则。自动模式和其他 12 种语言按完整字素加粗前半词。手动选择会设置副本的文档语言，自动模式沿用原文件的语言标记。多语言混排可以选自动。

常见问题
• 没有加粗：扫描图片需要先做 OCR；未嵌入字体、特殊编码、竖排、原有粗斜体和部分嵌套内容会保持原样。
• 原始模式也乱码：先用其他阅读器检查源 PDF。
• 找不到图层：改用普通仿生版，或在浏览器阅读页开关。
• 浏览器版本没有导出按钮：使用本制作工具生成副本。

文件在本机处理。仿生阅读是一种排版偏好，请自行比较是否适合你。
'''

def main():
    window=tk.Tk();Maker(window);window.mainloop()

if __name__ == "__main__":
    main()
