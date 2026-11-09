"""Local desktop launcher for making and reading PDF copies."""
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

from .converter import make_pdf, page_summary
from .document import SignatureLossError
from .local_reader import reader_directory, start_reader
from .words import LANGUAGES


PINE, PAPER, AMBER = '#183D32', '#F6F3EB', '#A25D21'
INK, MUTED, SURFACE, EDGE = '#23372F', '#526158', '#FFFCF5', '#778376'
MODES = ('可切换版 · WPS / Acrobat / Foxit', '普通仿生版 · 其他 PDF 阅读器')


def configure_style(root):
    families = set(font.families(root))
    sans = next((f for f in ('Microsoft YaHei UI', 'PingFang SC', 'Noto Sans CJK SC') if f in families),
                font.nametofont('TkDefaultFont').actual('family'))
    serif = next((f for f in ('Noto Serif SC', '宋体', 'SimSun', 'Songti SC', 'Noto Serif CJK SC')
                  if f in families), 'Georgia')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=PAPER, foreground=INK, font=(sans, 10))
    style.configure('TLabel', background=PAPER)
    style.configure('Hint.TLabel', foreground=MUTED, font=(sans, 9))
    style.configure('Title.TLabel', background=PINE, foreground=PAPER, font=(serif, 23, 'bold'))
    style.configure('Subtitle.TLabel', background=PINE, foreground='#E1E8DE', font=(sans, 10))
    style.configure('HelpTitle.TLabel', foreground=PINE, font=(serif, 19, 'bold'))
    style.configure('TSeparator', background='#C7CBBB')
    style.configure('TButton', padding=(11, 6), background=SURFACE, foreground=PINE, bordercolor=EDGE,
                    lightcolor=SURFACE, darkcolor=SURFACE, focuscolor=AMBER)
    style.map('TButton', background=[('active', '#E8ECE1')], bordercolor=[('focus', AMBER)],
              foreground=[('disabled', MUTED)])
    style.configure('Primary.TButton', background=PINE, foreground=SURFACE, bordercolor=PINE,
                    darkcolor=PINE, lightcolor=PINE, focuscolor='#FFD491')
    style.map('Primary.TButton', background=[('disabled', '#DCE1D5'), ('pressed', '#102D24'), ('active', '#285442')],
              foreground=[('disabled', MUTED)], bordercolor=[('!disabled', 'focus', AMBER)])
    for name in ('TEntry', 'TCombobox'):
        style.configure(name, padding=5, fieldbackground=SURFACE, background=SURFACE, foreground=INK,
                        bordercolor=EDGE, lightcolor=SURFACE, darkcolor=SURFACE, arrowcolor=PINE,
                        selectbackground=PINE, selectforeground=SURFACE)
        style.map(name, bordercolor=[('focus', AMBER)], fieldbackground=[('disabled', '#E6E7DF'), ('readonly', SURFACE)],
                  foreground=[('disabled', MUTED), ('readonly', INK)])
    style.configure('TCheckbutton', background=PAPER, focuscolor=AMBER, indicatorforeground=PINE)
    style.map('TCheckbutton', background=[('active', PAPER)], indicatorbackground=[('selected', SURFACE)])
    style.configure('Horizontal.TProgressbar', background=PINE, troughcolor='#DFE3D8', bordercolor='#A3AA9E',
                    lightcolor=PINE, darkcolor=PINE)
    root.option_add('*TCombobox*Listbox.font', (sans, 10))
    root.option_add('*TCombobox*Listbox.selectBackground', PINE)
    root.option_add('*TCombobox*Listbox.selectForeground', SURFACE)
    return sans, serif


class Maker:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.busy = False
        self.result = None
        self.inputs = []
        self.mode = tk.StringVar(root, MODES[0])
        auto = '自动分词 · auto'
        self.language_options = {auto: 'auto', **{f'{name} · {code}': code for code, name in LANGUAGES.items()}}
        self.locale = tk.StringVar(root, auto)
        self.pages, self.ocr = tk.StringVar(root), tk.BooleanVar(root)
        self.source, self.target = tk.StringVar(root), tk.StringVar(root)
        self.status, self.page_details = tk.StringVar(root, '请选择原始 PDF。'), tk.StringVar(root)
        self.help_window = None
        root.title('Bionic PDF Reader · 仿生阅读制作工具')
        root.configure(background=PAPER)
        self.sans, self.serif = configure_style(root)

        frame = ttk.Frame(root, padding=(22, 18))
        frame.pack(fill='both', expand=True)
        hero = tk.Frame(frame, background=PINE)
        hero.pack(fill='x', pady=(0, 16))
        heading = tk.Frame(hero, background=PINE, padx=18, pady=12)
        heading.pack(side='left', fill='y')
        ttk.Label(heading, text='制作阅读副本', style='Title.TLabel').pack(anchor='w')
        ttk.Label(heading, text='在原页加粗词首，保留正文与页码。', style='Subtitle.TLabel').pack(anchor='w', pady=(4, 0))
        try:
            assets = reader_directory() / 'assets'
            root.iconphoto(True, tk.PhotoImage(master=root, file=assets / 'icon-48.png'))
            self.cover = tk.PhotoImage(master=root, file=assets / 'reading-room.png').subsample(6)
            tk.Label(hero, image=self.cover, borderwidth=0, highlightthickness=0).pack(side='right')
        except (OSError, tk.TclError):
            pass  # Export remains available in a source-only installation.

        files = ttk.Frame(frame)
        files.pack(fill='x')
        files.columnconfigure(1, weight=1)
        self.source_entry = self.path_row(files, 0, '原始 PDF', self.source, '选择文件…', self.pick_source)
        self.target_entry = self.path_row(files, 1, '阅读副本', self.target, '保存位置…', self.pick_target)
        ttk.Separator(frame).pack(fill='x', pady=12)

        options = ttk.Frame(frame)
        options.pack(fill='x')
        options.columnconfigure(0, weight=3)
        options.columnconfigure(1, weight=2)
        for column, (label, variable, values, width) in enumerate((
                ('阅读方式', self.mode, MODES, 25), ('文档语言', self.locale, list(self.language_options), 14))):
            inset = (0, 16) if column == 0 else 0
            ttk.Label(options, text=label).grid(row=0, column=column, sticky='w')
            combo = ttk.Combobox(options, textvariable=variable, values=values, state='readonly', width=width)
            combo.grid(row=1, column=column, sticky='ew', padx=inset, pady=(3, 9))
            self.inputs.append(combo)
        ttk.Label(options, text='导出页码').grid(row=2, column=0, sticky='w')
        pages = ttk.Entry(options, textvariable=self.pages)
        pages.grid(row=3, column=0, sticky='ew', padx=(0, 16), pady=(3, 2))
        ocr = ttk.Checkbutton(options, text='扫描页本地 OCR', variable=self.ocr)
        ocr.grid(row=3, column=1, sticky='w')
        self.inputs.extend((pages, ocr))
        ttk.Label(options, text='留空导出整本，也可输入 1-3,7,5-4。', style='Hint.TLabel').grid(row=4, column=0, sticky='w')

        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=(16, 13))
        self.generate = ttk.Button(controls, text='生成阅读副本', style='Primary.TButton', command=self.start)
        self.generate.pack(side='left')
        self.open_button = ttk.Button(controls, text='打开阅读副本', command=self.open_result, state='disabled')
        self.open_button.pack(side='left', padx=(8, 0))
        ttk.Button(controls, text='在浏览器中阅读', command=self.open_reader).pack(side='left', padx=8)
        ttk.Button(controls, text='使用指南', command=self.show_help).pack(side='right')
        track = ttk.Frame(frame, height='9p')
        track.pack(fill='x')
        self.progress = ttk.Progressbar(track, maximum=100)
        self.progress.place(relwidth=1, relheight=1)
        self.status_line = ttk.Label(frame, textvariable=self.status, wraplength=505)
        self.status_line.pack(anchor='w', fill='x', pady=(7, 4))
        self.page_list = ttk.Entry(frame, textvariable=self.page_details, state='readonly')
        self.source.trace_add('write', self.clear_result)
        self.target.trace_add('write', self.clear_result)

        root.bind('<Control-o>', lambda event: self.pick_source())
        root.bind('<Control-Return>', lambda event: self.start())
        root.bind('<F1>', lambda event: self.show_help())
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.update_idletasks()
        # Reserve enough height for a copyable page report when an export skips many pages.
        height = root.winfo_reqheight() + self.page_list.winfo_reqheight() + 12
        root.minsize(max(560, root.winfo_reqwidth()), height)
        root.geometry(f'{max(710, root.winfo_reqwidth())}x{height}')
        root.after(120, self.poll)

    def path_row(self, parent, row, label, variable, action, command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=4)
        entry = ttk.Entry(parent, textvariable=variable, width=28)
        entry.grid(row=row, column=1, sticky='ew')
        button = ttk.Button(parent, text=action, command=command)
        button.grid(row=row, column=2, padx=(10, 0), pady=4)
        self.inputs.extend((entry, button))
        return entry

    def clear_result(self, *_):
        self.result = None
        self.open_button.state(['disabled'])
        self.page_list.pack_forget()
        self.progress['value'] = 0
        self.status.set('可生成副本，或在浏览器中阅读原件。' if self.source.get().strip() else '请选择原始 PDF。')

    def pick_source(self):
        if self.busy:
            return
        name = filedialog.askopenfilename(parent=self.root, title='选择原始 PDF', filetypes=[('PDF 文档', '*.pdf')])
        if name:
            self.source.set(name)
            self.pages.set('')
            path = Path(name)
            self.target.set(str(path.with_name(path.stem + '_仿生阅读.pdf')))
            self.source_entry.xview_moveto(1)
            self.target_entry.xview_moveto(1)

    def pick_target(self):
        if self.busy:
            return
        name = filedialog.asksaveasfilename(parent=self.root, title='保存阅读副本', defaultextension='.pdf',
            filetypes=[('PDF 文档', '*.pdf')], initialfile=Path(self.target.get()).name or '仿生阅读.pdf')
        if name:
            self.target.set(name)
            self.target_entry.xview_moveto(1)

    def set_busy(self, busy):
        self.busy = busy
        for widget in (*self.inputs, self.generate):
            widget.state(['disabled' if busy else '!disabled'])

    def start(self):
        if self.busy:
            return
        source, target = Path(self.source.get()), Path(self.target.get())
        if not source.is_file() or source.suffix.lower() != '.pdf':
            messagebox.showinfo('请选择 PDF', '请先选择原始 PDF。', parent=self.root)
            return
        if not self.target.get().strip():
            messagebox.showinfo('请选择保存位置', '请为阅读副本选择保存位置。', parent=self.root)
            return
        if source.resolve() == target.resolve():
            messagebox.showinfo('请保留原文件', '请给阅读副本选择不同文件名。', parent=self.root)
            return
        if target.exists() and not messagebox.askyesno('替换阅读副本', '目标文件已存在，是否替换这份阅读副本？', parent=self.root):
            return
        options = dict(pages=self.pages.get().strip() or None, mode='static' if self.mode.get() == MODES[1] else 'switchable',
                       locale=self.language_options[self.locale.get()], ocr=self.ocr.get())
        self.set_busy(True)
        self.open_button.state(['disabled'])
        self.progress['value'] = 0
        self.status.set('正在准备字体和页面…')
        self.page_list.pack_forget()

        def work(allow_signature_loss):
            try:
                report = make_pdf(source, target, **options, allow_signature_loss=allow_signature_loss,
                                  progress=lambda current, total: self.events.put(('progress', (current, total))))
                self.events.put(('done', (report, target)))
            except SignatureLossError:
                self.events.put(('signature', launch))
            except Exception as error:
                self.events.put(('error', str(error)))

        def launch(allow_signature_loss=False):
            threading.Thread(target=work, args=(allow_signature_loss,), daemon=True).start()
        launch()

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'progress':
                    current, total = payload
                    self.progress['value'] = 100 * current / total
                    self.status.set(f'已处理 {current} / {total} 页…')
                elif kind == 'signature':
                    if messagebox.askyesno('导出会使数字签名失效',
                            SignatureLossError.message + '\n\n仍要生成仅供阅读的副本吗？选择“否”后可在浏览器中阅读原件。',
                            default=messagebox.NO, parent=self.root):
                        payload(True)
                    else:
                        self.set_busy(False)
                        self.status.set('已取消导出。可点击「在浏览器中阅读」打开已签名的原件。')
                elif kind == 'done':
                    report, self.result = payload
                    self.set_busy(False)
                    self.open_button.state(['!disabled'])
                    self.progress['value'] = 100
                    summary = page_summary(report['unemphasized_pages'])
                    if len(summary) > 80:
                        self.page_details.set(summary)
                        self.page_list.pack(fill='x')
                        summary = f'其中 {len(report["unemphasized_pages"])} 页未加粗，可在下方选中并复制页码。'
                    self.status.set(f'完成，共 {report["pages"]} 页。' + summary)
                elif kind == 'error':
                    self.set_busy(False)
                    self.status.set('未生成副本，原始文件保留。')
                    messagebox.showerror('无法生成阅读副本', payload, parent=self.root)
        except queue.Empty:
            pass
        self.root.after(120, self.poll)

    def open_result(self):
        if self.result is None or not self.result.is_file():
            return
        if sys.platform == 'win32':
            os.startfile(str(self.result))
        else:
            import subprocess
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(self.result)])

    def close(self):
        if self.busy:
            messagebox.showinfo('正在生成', '请等当前副本生成结束后再关闭。', parent=self.root)
            return
        self.root.destroy()

    def open_reader(self):
        import webbrowser
        try:
            if not webbrowser.open_new_tab(start_reader(self.source.get())):
                raise OSError('无法启动默认浏览器。')
        except OSError as error:
            messagebox.showerror('无法打开阅读器', str(error), parent=self.root)

    def show_help(self):
        if self.help_window is not None and self.help_window.winfo_exists():
            self.help_window.lift()
            self.help_window.focus_set()
            return
        window = self.help_window = tk.Toplevel(self.root)
        window.title('使用指南与配置说明')
        window.transient(self.root)
        window.geometry('665x505')
        window.minsize(420, 320)
        frame = ttk.Frame(window, padding=(20, 14))
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, text='使用指南', style='HelpTitle.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 8))
        body = ttk.Frame(frame)
        body.grid(row=1, column=0, sticky='nsew')
        text = tk.Text(body, wrap='char', background=SURFACE, foreground=INK, font=(self.sans, 10),
                       padx=15, pady=8, spacing2=2, spacing3=6, borderwidth=0, highlightthickness=1,
                       highlightbackground=EDGE, highlightcolor=AMBER, selectbackground=PINE, selectforeground=SURFACE)
        scroll = ttk.Scrollbar(body, command=text.yview)
        scroll.pack(side='right', fill='y')
        text.configure(yscrollcommand=scroll.set)
        text.pack(fill='both', expand=True)
        text.tag_configure('heading', foreground=PINE, font=(self.serif, 14, 'bold'), spacing1=7, spacing3=4)
        for heading, content in HELP_SECTIONS:
            text.insert('end', heading + '\n', 'heading')
            text.insert('end', content + '\n')
        text.configure(state='disabled')
        close = ttk.Button(frame, text='关闭指南', command=window.destroy)
        close.grid(row=2, column=0, sticky='e', pady=(10, 0))

        def focus_close(event):
            close.focus_set()
            return 'break'

        text.bind('<Tab>', focus_close)
        text.bind('<Shift-Tab>', focus_close)
        window.bind('<Escape>', lambda event: window.destroy())
        text.focus_set()


HELP_SECTIONS = (
    ('制作阅读副本', '用「选择文件」打开原始 PDF，为副本选择另一个保存位置。选择阅读方式与文档语言，点击「生成阅读副本」。页码留空可导出整本，输入 1-3,7,5-4 可按指定顺序导出。\n'
     '完成后查看未加粗的副本页码，再点「打开阅读副本」。双页讲义左右两半合计一页。已有数字签名时，导出前会询问。选择「否」可在浏览器中阅读原件，选择「是」会生成签名失效的阅读副本。'),
    ('在原阅读器中切换', '选择「可切换版」，生成后在阅读器的图层面板开启「仿生阅读 · Bionic Reading」。图层默认关闭。\n'
     '• WPS 点左侧图层图标，再点眼睛。\n• Acrobat 打开「视图 → 显示/隐藏 → 侧面板 → 图层」。\n• Foxit 在左侧导航栏空白处右键选择「图层」。\n• PDF-XChange 按 Ctrl+L 打开图层，再点灯泡。\n• Firefox 159 打开「管理页面 → 视图 → 图层」。\n'
     'Preview、SumatraPDF、Apple Books 和手机阅读器适合使用「普通仿生版」。打开即可看到加粗词首。'),
    ('在浏览器中读原件', '点「在浏览器中阅读」打开已选的 PDF，也可以进入阅读页后再选文件。用「原始 / 仿生」或 Alt+B 切换，在阅读设置中调整语言、规则和强度。窄窗口可先展开「阅读设置与目录」。阅读期间请保持制作工具开启。'),
    ('文档语言与扫描件', '支持英语、法语、德语、西班牙语、葡萄牙语、意大利语、荷兰语、波兰语、土耳其语、越南语、俄语、乌克兰语和希腊语。自动和英语模式对纯英文字母词采用参考规则，其他词及其余语言按完整字素加粗前半词。自动模式保留原 PDF 的语言标记。\n'
     '扫描页只有图像时，安装本机 Tesseract 5 和对应语言包，选好文档语言并勾选「扫描页本地 OCR」。导出后可搜索一句正文。可切换版关闭图层后显示原图，已识别的文字仍可复制。\n'
     '文字未加粗时，可检查是否为竖排、特殊编码、未嵌入字体或原有粗体。原件也显示乱码时，可换一款阅读器对照同一页。'),
    ('键盘操作', 'Ctrl+O 选择原始 PDF，Ctrl+Enter 生成阅读副本，F1 打开指南，Esc 关闭指南。用 Tab 切换控件，空格激活按钮或复选框。'),
)


def main():
    window = tk.Tk()
    Maker(window)
    window.mainloop()


if __name__ == '__main__':
    main()
