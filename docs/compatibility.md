# 阅读器适配与验证范围

适配分为浏览器内实时绘制、标准可选内容图层、普通 PDF 三种方式。原始文档先保留一份，再按阅读器选择输出方式。

Windows 便携版和 Python 安装包都内置同一份本地网页阅读器，可以从制作工具的「在浏览器中阅读」打开。[安装与续读](usage.md)

## 已实施的适配

- **Chrome、Edge**：同一套 Manifest V3 扩展，直接在自己的阅读页切换。自动测试覆盖原始／仿生、原文复制层、页面尺寸、恢复原始像素及本地资源加载。
- **Firefox**：本地网页阅读器；另提供背景脚本适配的临时开发扩展。网页引擎测试与扩展签名／正式安装是两件事，临时包不宣称已上架。
- **WPS PDF**：制作可切换副本，使用左侧图层列表的眼睛开关。本机 WPS 12.1.0.29161 已人工实测整本长文档，页面、缩放、正文和批注保持原位。
- **Adobe Acrobat / Reader** 打开可切换副本，在「图层 / Layers」中点 `仿生阅读 · Bionic Reading` 左边的方框。Windows 版 Acrobat Reader 26.3.22075.0 已逐页验证 13 种语言的正文加粗及开关前后的系统剪贴板文字。[实机记录](verification.md) · [Adobe 图层说明](https://helpx.adobe.com/acrobat/desktop/edit-documents/pdf-layers/manage-layers.html)
- **Foxit PDF Reader**：制作可切换副本，在左侧导航栏空白处右键选择 Layers，再勾选该图层。2026.2.1.39815 已实机检查 13 种语言页面、图层开关、翻页、页码及缩放保留，开关前后原生复制的全文一致；检查范围见 [验证记录](verification.md)。其他版本的菜单仍可参照 [Foxit 官方手册](https://cdn01.foxitsoftware.com/pub/foxit/manual/reader/en_us/foxit-pdf-reader-user-manual-2026.1.1.pdf)。
- **PDF-XChange Editor**：制作可切换副本，使用 Layers 面板。11.1.1.0 已在本机人工验证图层开关及页码、缩放保留。按 Ctrl+L 打开图层，点击灯泡开关。
- **Firefox 内置 PDF 阅读器**：其 PDF.js 查看器有 Layers 视图，参见 [Mozilla 查看器源码](https://github.com/mozilla/pdf.js/blob/master/web/viewer.html)。可以尝试打开可切换副本；内置查看器和本项目阅读页的测试结果不混用。
- **macOS Preview**：使用普通仿生版。Apple PDFKit 引擎已验证 13 页的文字、原始像素和普通仿生显示；Preview 完成了打开文件检查，未冒充逐页人工界面验收。
- **SumatraPDF、Apple Books、手机 PDF 应用和其他阅读器**：提供不依赖新图层开关的普通仿生 PDF。该格式在 PDFium、PDF.js、Apple PDFKit 中验证文字与画面；这些应用各自的界面尚未逐个实机测试。
- **Safari** 在本地网页阅读器里点「打开 PDF」，通过 macOS 文件窗口选文件。Safari 26.6 和 27.2 均已验证 13 种语言、带标签和无标签文件、原文选择、词首加粗，以及关闭后逐页恢复原始画面。[验证记录](verification.md)

## PDF 支持边界

支持常见嵌入单字节 Type1/CFF、TrueType 和 Identity-H / CID TrueType 字体。原始文字、目录、页码、批注与已有图层被保留。加粗部分使用复用的矢量轮廓，不重新编码正文。

桌面版在绘制原文字的位置添加笔画，沿用当时的裁剪路径，之后绘制的图像或色块仍能遮住文字。若文字对象内部改变了蒙版等绘图状态，无法在同一条件下加粗的字形保留原样。

制作工具会处理页面实际绘制的嵌套 Form XObject，包括把两个原页并排放置的讲义。原有变换、裁剪和绘制顺序随表单保留。转换完成后会列出整页没有加入词首笔画的副本页码。可识别的文字片段按页面位置合词，ActualText 可辅助识别连字。扫描页、无法识别的字体、Identity-V 竖排、部分复杂 CMap 与 CID CFF 会保留原样。

没有阅读器通用的原生插件接口。本项目的标准 PDF 输出使同一份阅读副本可在多个应用里使用；不修改或注入这些应用。

## 测试结果

可复现测试命令见 [development.md](development.md)。自动测试覆盖 13 种语言示例、空白页、Identity-H、原有图层、原始文字、关闭时原始像素和普通输出。人工检查与自动检查分别记录，文档依据不冒充实机测试。

本次版本的浏览器版本、检查内容和验证边界见 [verification.md](verification.md)。
