# 0.4.0 验证记录

测试日期：2026-11-06。所有可公开测试均使用原创短句和 OFL 字体，没有教材或用户文档进入仓库、发布包或 CI。

## 已通过的本地测试

- Python：31 项通过，包含 13 种语言、分解重音、分片单词、连字、Identity-H、已有图层、空白页、原文与像素对比。
- JavaScript：17 项通过，包含与 Python 共享的词首用例、ActualText 连字、多栏复制顺序，以及 Safari 文字流的读取、取消和错误处理。
- Chrome 156.0.8078.80、Edge 156.0.4314.58、Firefox 153.0：每个浏览器验证 13 页基础样例，以及 13 种语言 × 带标签 / 不带标签两种打印 PDF；检查可选择文字、复制顺序、模式切换和原始像素恢复，没有外部文件请求。
- Chrome 独立扩展：实际加载 Manifest V3 包，检查 CSP、模块 worker、文件选择与模式切换。
- WPS 12.1.0.29161：之前已人工检查长文档图层开关、页码、缩放、正文和批注原位保留。
- PDF-XChange Editor 11.1.1.0：已在原生程序人工检查图层面板、默认关闭和开关、页面及缩放保留。13 种语言的完整页面回归在自动化引擎中进行，没有冒充每页原生界面人工验收。

## 发布前的跨平台检查

GitHub Actions 运行 Windows / Ubuntu 上 Python 3.11、3.13 的测试与构建、Chromium / Firefox 浏览器、Windows 独立程序转换，以及 macOS 的 Apple PDFKit、Safari。发布只使用通过验收的构建产物；具体运行链接在发布说明中记录。

本次 [完整验收运行](https://github.com/Yanxxzz/bionic-pdf-reader/actions/runs/42217027961) 的 7 个任务全部通过。Windows 包验证了 13 种语言转换、独立 GUI、完整语言列表、使用指南和内置网页资源；6 个发布包另做 SHA256、许可证、指南及归档内容检查。

Apple PDFKit 实际检查 13 页的原始文字、图层关闭时原始像素、普通仿生输出的加粗。Preview 也完成了打开文件及进程启动检查，这不等于逐页人工界面验收。

真实 macOS Safari 26.6.2 完成 13 种语言 × 带标签 / 不带标签两种 PDF，共 26 个案例，检查原始文字、词首加粗、选择复制和关闭恢复。控件通过 DOM 激活，并检查控件在屏幕上的实际命中位置；没有用 Playwright WebKit 冒充 Safari。

Safari 的系统文件选择和原生鼠标点击不列为通过项：SafariDriver 在不含阅读器代码的独立文件输入框上，使用 arrayBuffer 和 FileReader 均报 NotReadableError。本次渲染验收因此使用包含相同 PDF 字节的内存 File，环境记录和每个案例都注明输入方式。这验证真实 Safari 的阅读引擎与 DOM 控件，不替代系统文件对话框或原生点击验收。源码保留探针和结果记录，不隐藏此限制。

尚未将 Acrobat、Foxit、SumatraPDF 或手机应用列为本次逐应用实机验收；它们通过标准图层或普通 PDF 方式适配，见 [compatibility.md](compatibility.md)。

这些测试验证显示和文字保留，不是阅读速度或理解率实验。字体和编码边界见 [languages.md](languages.md)。
