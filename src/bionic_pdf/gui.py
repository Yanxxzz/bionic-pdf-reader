"""Local desktop launcher for making and reading PDF copies."""
import os
from concurrent.futures import CancelledError
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
INK, MUTED, SURFACE, EDGE = '#23372F', '#526158', '#FFFCF5', '#9FA89A'
LINE, SELECTED = '#D5D6C9', '#E8EEE3'
MODES = ('可切换版', '普通仿生版')


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
    style.configure('Title.TLabel', foreground=PINE, background=SURFACE, font=(serif, 21, 'bold'))
    style.configure('Cover.TLabel', foreground=MUTED, background=SURFACE)
    style.configure('HelpTitle.TLabel', foreground=PINE, font=(serif, 19, 'bold'))
    style.configure('Section.TLabel', foreground=PINE, font=(sans, 11, 'bold'))
    style.configure('TButton', padding=('8p', '4p'), relief='flat', background=SURFACE, foreground=PINE,
                    borderwidth=1, bordercolor=EDGE, lightcolor=SURFACE, darkcolor=SURFACE, focuscolor=AMBER)
    style.map('TButton', background=[('active', '#EDF0E7')], bordercolor=[('focus', AMBER)],
              foreground=[('disabled', MUTED)])
    style.configure('Quiet.TButton', background=PAPER, bordercolor=PAPER, lightcolor=PAPER,
                    darkcolor=PAPER, padding=('4p', '4p'), borderwidth=0)
    style.configure('Primary.TButton', background=PINE, foreground=SURFACE, bordercolor=PINE,
                    darkcolor=PINE, lightcolor=PINE, focuscolor='#FFD491')
    style.map('Primary.TButton', background=[('disabled', '#E2E5DA'), ('pressed', '#102D24'), ('active', '#285442')],
              foreground=[('disabled', MUTED)], bordercolor=[('disabled', '#C7CCBF'), ('focus', AMBER)])
    # Keep Tk's native radio role and keyboard behaviour across the full option.
    style.layout('Mode.TRadiobutton', [('Button.border', {
        'sticky': 'nswe', 'children': style.layout('TRadiobutton'),
    })])
    style.configure('Mode.TRadiobutton', padding=('8p', '6p'), font=(sans, 10, 'bold'), anchor='w',
                    indicatorsize='8p', focuscolor=AMBER, background=SURFACE, bordercolor=EDGE,
                    lightcolor=SURFACE, darkcolor=SURFACE)
    for option in ('background', 'lightcolor', 'darkcolor'):
        style.map('Mode.TRadiobutton', **{option: [('selected', SELECTED), ('active', '#F0F2E9')]})
    style.map('Mode.TRadiobutton', bordercolor=[('focus', AMBER), ('selected', '#779381')])
    for name in ('TEntry', 'TCombobox'):
        style.configure(name, padding=('5p', '4p'), fieldbackground=SURFACE, background=SURFACE, foreground=INK,
                        bordercolor=EDGE, lightcolor=SURFACE, darkcolor=SURFACE, arrowcolor=PINE,
                        selectbackground=PINE, selectforeground=SURFACE)
        style.map(name, bordercolor=[('focus', AMBER)], fieldbackground=[('disabled', '#E6E7DF'), ('readonly', SURFACE)],
                  foreground=[('disabled', MUTED), ('readonly', INK)])
    style.configure('TCheckbutton', background=PAPER, focuscolor=AMBER, indicatorforeground=PINE)
    style.map('TCheckbutton', background=[('active', PAPER)], indicatorbackground=[('selected', SURFACE)])
    style.configure('Horizontal.TProgressbar', thickness='4p', background=PINE, troughcolor='#DFE3D8', bordercolor=LINE,
                    lightcolor=PINE, darkcolor=PINE)
    root.option_add('*TCombobox*Listbox.font', (sans, 10))
    root.option_add('*TCombobox*Listbox.selectBackground', PINE)
    root.option_add('*TCombobox*Listbox.selectForeground', SURFACE)
    return sans, serif


def cover_image(root, path):
    width = root.winfo_pixels('132p')
    try:
        from PIL import Image, ImageOps, ImageTk
    except ImportError:
        original = tk.PhotoImage(master=root, file=path)
        return original.subsample(max(1, round(original.width() / width)))
    with Image.open(path) as image:
        cover = ImageOps.fit(image.convert('RGB'), (width, round(width * .57)), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(cover, master=root)


class Maker:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.busy = False
        self.cancel_requested = threading.Event()
        self.close_when_finished = False
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

        frame = ttk.Frame(root, padding=('16p', '12p'))
        frame.pack(fill='both', expand=True)
        hero = tk.Frame(frame, background=SURFACE, highlightbackground=LINE, highlightthickness=1)
        hero.pack(fill='x', pady=(0, '10p'))
        heading = tk.Frame(hero, background=SURFACE, padx='12p', pady='8p')
        heading.pack(side='left', fill='y')
        ttk.Label(heading, text='制作阅读副本', style='Title.TLabel').pack(anchor='w')
        ttk.Label(heading, text='按你常用的阅读器选择副本类型。', style='Cover.TLabel').pack(anchor='w', pady=('2p', 0))
        try:
            assets = reader_directory() / 'assets'
            root.iconphoto(True, tk.PhotoImage(master=root, file=assets / 'icon-48.png'))
            self.cover = cover_image(root, assets / 'reading-room.png')
            tk.Label(hero, image=self.cover, background=SURFACE, borderwidth=0, highlightthickness=0).pack(side='right')
        except (OSError, tk.TclError):
            pass  # A source-only installation can still export PDFs.

        files = ttk.Frame(frame)
        files.pack(fill='x')
        files.columnconfigure(1, weight=1)
        self.source_entry, self.source_button = self.path_row(files, 0, '原始 PDF', self.source, '选择文件…', self.pick_source)
        self.target_entry, _ = self.path_row(files, 1, '保存到', self.target, '保存位置…', self.pick_target)

        ttk.Label(frame, text='副本类型', style='Section.TLabel').pack(anchor='w', pady=('10p', '4p'))
        modes = ttk.Frame(frame)
        modes.pack(fill='x')
        self.mode_hint = tk.StringVar(root)
        self.mode_buttons = []
        for column, (value, readers) in enumerate(zip(MODES, ('WPS / Acrobat / Foxit', '手机 / Mac 预览'))):
            modes.columnconfigure(column, weight=1, uniform='mode')
            radio = ttk.Radiobutton(modes, text=f'{value}  ·  {readers}', style='Mode.TRadiobutton',
                                    variable=self.mode, value=value)
            radio.grid(row=0, column=column, sticky='ew', padx=(0, '5p') if column == 0 else ('5p', 0))
            self.mode_buttons.append(radio)
            for key in ('Left', 'Right', 'Up', 'Down'):
                radio.bind(f'<{key}>', self.move_mode)
        self.inputs.extend(self.mode_buttons)
        ttk.Label(frame, textvariable=self.mode_hint, style='Hint.TLabel').pack(anchor='w', pady=('3p', 0))

        options = ttk.Frame(frame)
        options.pack(fill='x', pady=('5p', 0))
        options.columnconfigure(0, weight=1)
        self.options_button = ttk.Button(options, text='▸  页码、语言与扫描件', style='Quiet.TButton',
                                         command=self.toggle_options)
        self.options_button.grid(row=0, column=0, sticky='w')
        self.options = ttk.Frame(options, padding=('4p', '3p'))
        self.options.grid(row=1, column=0, sticky='ew')
        self.options.columnconfigure((0, 1), weight=1, uniform='settings')
        ttk.Label(self.options, text='导出页码').grid(row=0, column=0, sticky='w')
        ttk.Label(self.options, text='文档语言').grid(row=0, column=1, sticky='w')
        pages = ttk.Entry(self.options, textvariable=self.pages)
        pages.grid(row=1, column=0, sticky='ew', padx=(0, 14), pady=3)
        language = ttk.Combobox(self.options, textvariable=self.locale, values=list(self.language_options), state='readonly')
        language.grid(row=1, column=1, sticky='ew', pady=3)
        ttk.Label(self.options, text='留空导出整本。例如 1-3,7。', style='Hint.TLabel').grid(row=2, column=0, sticky='w')
        ocr = ttk.Checkbutton(self.options, text='扫描页本地 OCR', variable=self.ocr)
        ocr.grid(row=3, column=0, sticky='w', pady=(4, 0))
        ttk.Label(self.options, text='识别图片里的正文，需 Tesseract 5 和语言包。', style='Hint.TLabel').grid(row=3, column=1, sticky='w')
        self.inputs.extend((pages, language, ocr))
        self.options.grid_remove()
        tk.Frame(frame, background=LINE, height=1).pack(fill='x', pady=('5p', '7p'))

        controls = ttk.Frame(frame)
        controls.pack(fill='x')
        self.generate = ttk.Button(controls, text='生成阅读副本', style='Primary.TButton', command=self.start)
        self.generate.pack(side='left')
        self.open_button = ttk.Button(controls, text='打开阅读副本', style='Primary.TButton', command=self.open_result)
        ttk.Button(controls, text='在浏览器中阅读', style='Quiet.TButton', command=self.open_reader).pack(side='left', padx='5p')
        ttk.Button(controls, text='使用指南', style='Quiet.TButton', command=self.show_help).pack(side='right')
        self.feedback = ttk.Frame(frame)
        self.feedback.pack(fill='x', pady=('6p', 0))
        self.progress = ttk.Progressbar(self.feedback, maximum=100, length=220)
        self.status_line = ttk.Label(self.feedback, textvariable=self.status, wraplength='455p', style='Hint.TLabel')
        self.status_line.pack(anchor='w', fill='x')
        self.page_list = ttk.Entry(self.feedback, textvariable=self.page_details, state='readonly')
        for value in (self.source, self.target, self.mode, self.pages, self.locale, self.ocr):
            value.trace_add('write', self.clear_result)
        self.clear_result()

        root.bind('<Control-o>', lambda event: self.pick_source())
        root.bind('<Control-Return>', lambda event: self.start())
        root.bind('<F1>', lambda event: self.show_help())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.fit_window()
        self.source_button.focus_set()
        root.after(120, self.poll)

    def path_row(self, parent, row, label, variable, action, command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12))
        entry = ttk.Entry(parent, textvariable=variable, width=28)
        entry.grid(row=row, column=1, sticky='ew', pady='2p')
        button = ttk.Button(parent, text=action, command=command)
        button.grid(row=row, column=2, padx=('7p', 0), pady='3p')
        self.inputs.extend((entry, button))
        return entry, button

    def move_mode(self, event):
        step = -1 if event.keysym in ('Left', 'Up') else 1
        index = self.mode_buttons.index(event.widget)
        button = self.mode_buttons[(index + step) % len(self.mode_buttons)]
        if button.instate(['!disabled']):
            button.focus_set()
            button.invoke()
        return 'break'

    def toggle_options(self):
        if self.options.winfo_manager():
            self.options.grid_remove()
            self.options_button.configure(text='▸  页码、语言与扫描件')
        else:
            self.options.grid()
            self.options_button.configure(text='▾  页码、语言与扫描件')
        self.fit_window()

    def fit_window(self):
        self.root.update_idletasks()
        self.root.minsize(max(self.root.winfo_pixels('510p'), self.root.winfo_reqwidth()), self.root.winfo_reqheight())

    def update_actions(self):
        source = self.source.get().strip()
        self.source_button.configure(style='TButton' if source else 'Primary.TButton')
        if not self.busy:
            self.generate.state(['!disabled' if source and self.target.get().strip() else 'disabled'])
        for radio in self.mode_buttons:
            radio.configure(takefocus=radio.cget('value') == self.mode.get())
        ready_to_open = not self.busy and self.result is not None and self.result.is_file()
        self.generate.configure(style='TButton' if ready_to_open else 'Primary.TButton')
        if ready_to_open:
            self.open_button.pack(side='left', after=self.generate, padx=(8, 0))
        else:
            self.open_button.pack_forget()

    def clear_result(self, *_):
        self.result = None
        self.page_list.pack_forget()
        self.progress.pack_forget()
        self.progress['value'] = 0
        switchable = self.mode.get() == MODES[0]
        self.mode_hint.set('打开副本后，在「图层」面板开启或关闭仿生阅读。' if switchable
                           else '打开副本即显示加粗词首，可用原始 PDF 对照。')
        if not self.source.get().strip():
            self.status.set('先点「选择文件」打开原始 PDF。')
        elif not self.target.get().strip():
            self.status.set('点「保存位置」为副本选择文件名。')
        else:
            pages = self.pages.get().strip()
            if len(pages) > 45:
                pages = pages[:45] + '…'
            scope = f'导出页码 {pages}' if pages else '导出整本'
            summary = [scope, self.mode.get()]
            if self.language_options[self.locale.get()] != 'auto':
                summary.append(self.locale.get())
            if self.ocr.get():
                summary.append('本地 OCR')
            self.status.set(' · '.join(summary))
        self.update_actions()

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
        if not busy:
            self.progress.stop()
            self.progress.configure(mode='determinate')
        for widget in self.inputs:
            widget.state(['disabled' if busy else '!disabled'])
        self.generate.configure(text='取消导出' if busy else '生成阅读副本',
                                command=self.request_cancel if busy else self.start)
        self.generate.state(['!disabled'])
        self.update_actions()

    def request_cancel(self):
        self.cancel_requested.set()
        self.generate.state(['disabled'])
        self.status.set('正在取消，当前处理步骤结束后停止。')

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
        self.cancel_requested.clear()
        self.set_busy(True)
        self.progress.pack(fill='x', before=self.status_line, pady=(1, 6))
        self.fit_window()
        self.progress['value'] = 0
        self.status.set('正在准备字体和页面…')
        if sys.platform == 'win32':
            import ctypes
            enabled = ctypes.c_int()
            # SPI_GETCLIENTAREAANIMATION respects the Windows animation preference.
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0) and enabled.value:
                self.progress.configure(mode='indeterminate')
                self.progress.start(65)
        self.page_list.pack_forget()

        def work(allow_signature_loss):
            try:
                report = make_pdf(source, target, **options, allow_signature_loss=allow_signature_loss,
                                  cancelled=self.cancel_requested.is_set,
                                  progress=lambda current, total: self.events.put(('progress', (current, total))))
                self.events.put(('done', (report, target)))
            except CancelledError:
                self.events.put(('cancelled', None))
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
                if kind == 'signature' and self.cancel_requested.is_set():
                    kind = 'cancelled'
                if self.close_when_finished and kind in ('cancelled', 'done', 'error'):
                    self.root.destroy()
                    return
                if kind == 'progress':
                    current, total = payload
                    if str(self.progress.cget('mode')) == 'indeterminate':
                        self.progress.stop()
                        self.progress.configure(mode='determinate')
                    self.progress['value'] = 100 * current / total
                    if not self.cancel_requested.is_set():
                        self.status.set('正在保存阅读副本…' if current == total else f'已处理 {current} / {total} 页…')
                elif kind == 'cancelled':
                    self.set_busy(False)
                    self.progress['value'] = 0
                    self.progress.pack_forget()
                    self.status.set('已取消。原文件和已有副本已保留，可调整页码后重新生成。')
                elif kind == 'signature':
                    if messagebox.askyesno('导出会使数字签名失效',
                            SignatureLossError.message + '\n\n仍要生成仅供阅读的副本吗？选择“否”后可在浏览器中阅读原件。',
                            default=messagebox.NO, parent=self.root):
                        payload(True)
                    else:
                        self.set_busy(False)
                        self.progress.pack_forget()
                        self.status.set('已取消导出。可点击「在浏览器中阅读」打开已签名的原件。')
                elif kind == 'done':
                    report, self.result = payload
                    self.set_busy(False)
                    self.progress['value'] = 100
                    summary = page_summary(report['unemphasized_pages'])
                    if len(summary) > 80:
                        self.page_details.set(summary)
                        self.page_list.pack(fill='x')
                        summary = f'其中 {len(report["unemphasized_pages"])} 页未加粗，可在下方选中并复制页码。'
                    next_step = ('打开副本，在「图层」面板开启仿生阅读。' if report['mode'] == 'switchable'
                                 else '打开阅读副本即可看到加粗词首。')
                    self.status.set(f'完成，共 {report["pages"]} 页。' + summary + ' ' + next_step)
                    self.fit_window()
                elif kind == 'error':
                    self.set_busy(False)
                    self.progress.pack_forget()
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
            if self.close_when_finished or not messagebox.askyesno(
                    '取消导出并关闭？', '当前处理步骤结束后关闭。要取消这次导出吗？',
                    default=messagebox.NO, parent=self.root):
                return
            if self.busy:  # Tk can deliver the completion event while the confirmation is open.
                self.close_when_finished = True
                self.request_cancel()
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
        previous_focus = self.root.focus_get()
        window = self.help_window = tk.Toplevel(self.root)
        window.title('使用指南与配置说明')
        window.transient(self.root)
        width = min(window.winfo_pixels('495p'), window.winfo_screenwidth() - window.winfo_pixels('20p'))
        height = min(window.winfo_pixels('378p'), window.winfo_screenheight() - window.winfo_pixels('48p'))
        window.geometry(f'{width}x{height}')
        window.minsize(min(width, window.winfo_pixels('315p')), min(height, window.winfo_pixels('240p')))
        frame = ttk.Frame(window, padding=('14p', '10p'))
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, text='使用指南', style='HelpTitle.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 8))
        body = ttk.Frame(frame)
        body.grid(row=1, column=0, sticky='nsew')
        text = tk.Text(body, wrap='char', background=SURFACE, foreground=INK, font=(self.sans, 10),
                       padx='10p', pady='6p', spacing2='1p', spacing3='4p', borderwidth=0, highlightthickness=1,
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
        def close_guide(event=None):
            window.destroy()
            if previous_focus and previous_focus.winfo_exists():
                previous_focus.focus_set()

        close = ttk.Button(frame, text='关闭指南', command=close_guide)
        close.grid(row=2, column=0, sticky='e', pady=(10, 0))

        def focus_close(event):
            close.focus_set()
            return 'break'

        text.bind('<Tab>', focus_close)
        text.bind('<Shift-Tab>', focus_close)
        window.bind('<Escape>', close_guide)
        window.protocol('WM_DELETE_WINDOW', close_guide)
        text.focus_set()


HELP_SECTIONS = (
    ('先试读两页', '点「在浏览器中阅读」进入阅读页，在首页选「试读两页示例」。点顶部「仿生」和「原始」阅读同一行，再点页底的英文引用进入第二页，用「返回原处」回到起点。'),
    ('制作阅读副本', '用「选择文件」打开原始 PDF，为副本选择另一个保存位置。按阅读器选择副本类型，点击「生成阅读副本」。要指定页码、语言或使用 OCR，先展开「页码、语言与扫描件」。导出页码留空可制作整本，输入 1-3,7,5-4 可按指定顺序导出。\n'
     '选错页码可点「取消导出」，当前处理步骤结束后停止，已有文件会保留。完成后查看未加粗的副本页码，再点「打开阅读副本」。双页讲义左右两半合计一页。已有数字签名时，导出前会询问。选择「否」可在浏览器中阅读原件，选择「是」会生成签名失效的阅读副本。'),
    ('English quick start', 'Select 选择文件 to choose a PDF. Use 可切换版 for a copy with a Layers switch, or 普通仿生版 for always-visible emphasis. Choose 生成阅读副本 to export, 取消导出 to cancel, or 在浏览器中阅读 to read locally in your browser.'),
    ('在原阅读器中切换', '选择「可切换版」，生成后在阅读器的图层面板开启「仿生阅读 · Bionic Reading」。图层默认关闭。\n'
     '• WPS 点左侧图层图标，再点眼睛。\n• Acrobat 打开「视图 → 显示/隐藏 → 侧面板 → 图层」。\n• Foxit 在左侧导航栏空白处右键选择「图层」。\n• PDF-XChange 按 Ctrl+L 打开图层，再点灯泡。\n• Firefox 159 打开「管理页面 → 视图 → 图层」。\n'
     'Preview、SumatraPDF、Apple Books 和手机阅读器适合使用「普通仿生版」。打开即可看到加粗词首。'),
    ('在浏览器中读原件', '点「在浏览器中阅读」打开已选的 PDF，也可以进入阅读页后再选文件。用「原始 / 仿生」或 Alt+B 切换，在阅读设置中调整语言、规则和强度。窄窗口可先展开「阅读设置与目录」。阅读期间请保持制作工具开启。'),
    ('文档语言与扫描件', '支持英语、法语、德语、西班牙语、葡萄牙语、意大利语、荷兰语、波兰语、土耳其语、越南语、俄语、乌克兰语和希腊语。自动和英语模式对纯英文字母词采用参考规则，其他词及其余语言按完整字素加粗前半词。自动模式保留原 PDF 的语言标记。\n'
     '扫描页只有图像时，安装本机 Tesseract 5 和对应语言包，展开「页码、语言与扫描件」，选好文档语言并勾选「扫描页本地 OCR」。导出后可搜索一句正文。可切换版关闭图层后显示原图，已识别的文字仍可复制。\n'
     '文字未加粗时，可检查是否为竖排、特殊编码、未嵌入字体或原有粗体。原件也显示乱码时，可换一款阅读器对照同一页。'),
    ('键盘操作', 'Ctrl+O 选择原始 PDF，Ctrl+Enter 生成阅读副本，F1 打开指南，Esc 关闭指南。用 Tab 切换控件，方向键选择副本类型，空格激活按钮或复选框。'),
)


def create_window():
    if sys.platform == 'win32':
        import ctypes
        # Set this before Tk creates a window so Windows does not stretch its pixels.
        ctypes.windll.user32.SetProcessDPIAware()
    return tk.Tk()


def main():
    window = create_window()
    Maker(window)
    window.mainloop()


if __name__ == '__main__':
    main()
