# 阅读器适配与验证范围

适配分为浏览器内实时绘制、标准可选内容图层、普通 PDF 三种方式。原始文档先保留一份，再按阅读器选择输出方式。

## 已实施的适配

- **Chrome、Edge**：同一套 Manifest V3 扩展，直接在自己的阅读页切换。自动测试覆盖原始／仿生、原文复制层、页面尺寸、恢复原始像素及本地资源加载。
- **Firefox**：本地网页阅读器；另提供背景脚本适配的临时开发扩展。网页引擎测试与扩展签名／正式安装是两件事，临时包不宣称已上架。
- **WPS PDF**：制作可切换副本，使用左侧图层列表的眼睛开关。本机 WPS 12.1.0.29161 已人工实测整本长文档，页面、缩放、正文和批注保持原位。
- **Adobe Acrobat / Reader**：制作可切换副本，使用 Layers 面板。依据 [Adobe 官方图层说明](https://helpx.adobe.com/acrobat/desktop/edit-documents/pdf-layers/manage-layers.html) 适配；当前未将它列为本机人工实测结果。
- **Foxit PDF Reader**：制作可切换副本，在左侧导航栏空白处右键选择 Layers，再勾选该图层。2026.2.1.39815 已实机检查 13 种语言页面、图层开关、翻页、页码及缩放保留，开关前后原生复制的全文一致；检查范围见 [验证记录](verification.md)。其他版本的菜单仍可参照 [Foxit 官方手册](https://cdn01.foxitsoftware.com/pub/foxit/manual/reader/en_us/foxit-pdf-reader-user-manual-2026.1.1.pdf)。
- **PDF-XChange Editor**：制作可切换副本，使用 Layers 面板。11.1.1.0 已在本机人工验证图层开关及页码、缩放保留。按 Ctrl+L 打开图层，点击灯泡开关。
- **Firefox 内置 PDF 阅读器**：其 PDF.js 查看器有 Layers 视图，参见 [Mozilla 查看器源码](https://github.com/mozilla/pdf.js/blob/master/web/viewer.html)。可以尝试打开可切换副本；内置查看器和本项目阅读页的测试结果不混用。
- **macOS Preview**：使用普通仿生版。Apple PDFKit 引擎已验证 13 页的文字、原始像素和普通仿生显示；Preview 完成了打开文件检查，未冒充逐页人工界面验收。
- **SumatraPDF、Apple Books、手机 PDF 应用和其他阅读器**：提供不依赖新图层开关的普通仿生 PDF。该格式在 PDFium、PDF.js、Apple PDFKit 中验证文字与画面；这些应用各自的界面尚未逐个实机测试。
- **Safari**：真实 macOS Safari 已完成本地网页阅读引擎的 13 种语言、文字选择、模式切换和关闭恢复测试，并补齐文字流兼容。验收使用内存 File 和 DOM 控件激活；SafariDriver 的系统文件选择在独立探针中也读取失败，系统文件对话框和原生点击尚不列为通过项。完整边界见 [验证记录](verification.md)。

## PDF 支持边界

支持常见嵌入单字节 Type1/CFF、TrueType 和 Identity-H / CID TrueType 字体。原始文字、目录、页码、批注与已有图层被保留。加粗部分使用复用的矢量轮廓，不重新编码正文。

扫描页、无法识别的字体、Identity-V / 竖排、部分复杂 CMap 与 CID CFF、嵌套 Form XObject 中的文本尚不做强调。会按页面位置合并单词的独立绘制片段，并在有 ActualText 时辅助识别连字。无法可靠映射的内容保留原样。复杂裁剪、透明度和专业排版需使用自己的文档抽查。

没有阅读器通用的原生插件接口。本项目的标准 PDF 输出使同一份阅读副本可在多个应用里使用；不修改或注入这些应用。

## 测试结果

可复现测试命令见 [development.md](development.md)。自动测试覆盖 13 种语言示例、空白页、Identity-H、原有图层、原始文字、关闭时原始像素和普通输出。人工检查与自动检查分别记录，文档依据不冒充实机测试。

本次版本的浏览器版本、检查内容和验证边界见 [verification.md](verification.md)。
