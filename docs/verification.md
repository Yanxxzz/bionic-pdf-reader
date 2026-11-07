# 验证记录

## 0.4.1

测试日期为 2026-11-07。桌面阅读器使用工具生成的可切换副本，浏览器使用原创多语言样例。

- 删除停用的 PDF 文字改写引擎和浏览器备用字形选择算法；转换进度改为回调，GUI 不再全局重定向标准输出。
- 本地 39 项 Python、22 项 JavaScript 测试通过，覆盖嵌套绘图状态、双栏公式、跨行复制、文件名与图层资源重名，以及 13 种语言的词首。用重构前后的转换器生成三份样例副本，共 40 页，逐页文字与像素一致。另用已有图层和图形的样例检查整本与选页导出、图层开关和静态副本。
- Chrome、Edge、Firefox 验证了同页切换时的文字选区、切换语言或规则后的词首，以及带标签和无标签样例的复制顺序。Chrome 扩展也完成了加载和切换测试。各次提交的跨平台结果见[发布分支的 CI 记录](https://github.com/Yanxxzz/bionic-pdf-reader/actions/workflows/ci.yml?query=branch%3Arelease%2Fv0.4.1)。
- Windows 独立程序完成转换、图形界面和离线使用指南检查。6 个下载包均核对 SHA256、许可证和归档内容。[下载与校验清单](https://github.com/Yanxxzz/bionic-pdf-reader/releases/tag/v0.4.1)
- Foxit PDF Reader 2026.2.1.39815：原生界面检查了 13 种语言页面、默认关闭、开关与翻页状态、页码及缩放保留。原生全选复制覆盖 13 种语言，开关前后的全文一致。未把代表页面的开关检查说成每页都做了完整开关循环。
- Acrobat Reader 26.3.22075.0 在独立 Windows 测试机上打开 13 页可切换副本。每页都实际点图层开关，开启后的正文截图出现更深的笔画。用鼠标选中同一页的文字并复制到 Windows 剪贴板，开关前后的 13 对原始结果逐字节相同，包括重音、空格和换行。[Acrobat 原生验收](https://github.com/Yanxxzz/bionic-pdf-reader/actions/runs/42358778065)
- 另用 Acrobat 打开未经转换的 PDF 对照正文。原件和阅读副本的 13 页正文相同，跨选区对照时忽略 Acrobat 插入的换行。越南语压力样例包含分解重音，Acrobat 在原文件中已会复制出个别重复字符，开关图层后保留原件的复制结果。此限制涉及这份 PDF 的文字提取。[样例原文](../examples/shaping-cases.json) · [原件对照](https://github.com/Yanxxzz/bionic-pdf-reader/actions/runs/42358778065)
- 在 macOS 15.7.9 的 Safari 26.6 和 macOS 15.8.2 的 Safari 27.2 中，从普通浏览器窗口点「打开 PDF」，用系统文件窗口分别选择带标签和无标签的 PDF。两种文件读入后的 SHA256 均与磁盘文件一致。[Safari 26.6](https://github.com/Yanxxzz/bionic-pdf-reader/actions/runs/42355398492/job/128352269117) · [Safari 27.2](https://github.com/Yanxxzz/bionic-pdf-reader/actions/runs/42355398492/job/128352268727)
- 两版 Safari 各检查 13 种语言 × 两份文件。每页都比对原始、开启、关闭三个状态。开启后正文截图出现加粗，原文和选区文字保持一致。关闭后，整页画布与正文区域的系统截图都逐像素恢复。[逐页验收程序](https://github.com/Yanxxzz/bionic-pdf-reader/blob/9f44e5b0059ed57b16c3bf1a0dc8ccc38d43582c/tests/native_safari_fixture.py)
- 另有两台 macOS 26/27 测试机将普通纯色网页也截成白色，另一台 Intel 测试机的文件框检测超时。这些运行保留为环境诊断。Safari 27.2 修复后的逐页截图来自上述 macOS 15.8.2 测试机。[对照测试](https://github.com/Yanxxzz/bionic-pdf-reader/actions/runs/42354853729)

## 0.4.0

测试日期：2026-11-06。所有可公开测试均使用原创短句和 OFL 字体，没有教材或用户文档进入仓库、发布包或 CI。

### 已通过的本地测试

- Python：31 项通过，包含 13 种语言、分解重音、分片单词、连字、Identity-H、已有图层、空白页、原文与像素对比。
- JavaScript：17 项通过，包含与 Python 共享的词首用例、ActualText 连字、多栏复制顺序，以及 Safari 文字流的读取、取消和错误处理。
- Chrome 156.0.8078.80、Edge 156.0.4314.58、Firefox 153.0：每个浏览器验证 13 页基础样例，以及 13 种语言 × 带标签 / 不带标签两种打印 PDF；检查可选择文字、复制顺序、模式切换和原始像素恢复，没有外部文件请求。
- Chrome 独立扩展：实际加载 Manifest V3 包，检查 CSP、模块 worker、文件选择与模式切换。
- WPS 12.1.0.29161：之前已人工检查长文档图层开关、页码、缩放、正文和批注原位保留。
- PDF-XChange Editor 11.1.1.0：已在原生程序人工检查图层面板、默认关闭和开关、页面及缩放保留。13 种语言的完整页面回归在自动化引擎中进行，没有冒充每页原生界面人工验收。

### 发布前的跨平台检查

GitHub Actions 运行 Windows / Ubuntu 上 Python 3.11、3.13 的测试与构建、Chromium / Firefox 浏览器、Windows 独立程序转换，以及 macOS 的 Apple PDFKit、Safari。发布只使用通过验收的构建产物；具体运行链接在发布说明中记录。

本次 [完整验收运行](https://github.com/Yanxxzz/bionic-pdf-reader/actions/runs/42217027961) 的 7 个任务全部通过。Windows 包验证了 13 种语言转换、独立 GUI、完整语言列表、使用指南和内置网页资源；6 个发布包另做 SHA256、许可证、指南及归档内容检查。

Apple PDFKit 实际检查 13 页的原始文字、图层关闭时原始像素、普通仿生输出的加粗。Preview 也完成了打开文件及进程启动检查，这不等于逐页人工界面验收。

真实 macOS Safari 26.6.2 完成 13 种语言 × 带标签 / 不带标签两种 PDF，共 26 个案例，检查原始文字、词首加粗、选择复制和关闭恢复。控件通过 DOM 激活，并检查控件在屏幕上的实际命中位置；没有用 Playwright WebKit 冒充 Safari。

Safari 的系统文件选择和原生鼠标点击不列为通过项：SafariDriver 在不含阅读器代码的独立文件输入框上，使用 arrayBuffer 和 FileReader 均报 NotReadableError。本次渲染验收因此使用包含相同 PDF 字节的内存 File，环境记录和每个案例都注明输入方式。这验证真实 Safari 的阅读引擎与 DOM 控件，不替代系统文件对话框或原生点击验收。源码保留探针和结果记录，不隐藏此限制。

尚未将 Acrobat、Foxit、SumatraPDF 或手机应用列为本次逐应用实机验收；它们通过标准图层或普通 PDF 方式适配，见 [compatibility.md](compatibility.md)。

这些测试验证显示和文字保留，不是阅读速度或理解率实验。字体和编码边界见 [languages.md](languages.md)。
