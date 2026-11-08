# 阅读器适配与验证范围

适配分为浏览器内实时绘制、标准可选内容图层、普通 PDF 三种方式。原始文档先保留一份，再按阅读器选择输出方式。

Windows 便携版和 Python 安装包都内置同一份本地网页阅读器，可以从制作工具的「在浏览器中阅读」打开。[安装与续读](usage.md)

## 已实施的适配

- **Chrome、Edge**：同一套 Manifest V3 扩展，直接在自己的阅读页切换。自动测试覆盖原始／仿生、原文复制层、页面尺寸、恢复原始像素及本地资源加载。
- **Firefox** 可以把本地网页阅读器加入书签。Windows 正式版 Firefox 159.0.1 已实测退出整个浏览器、重新启动、打开书签并选回同一份文件后接续第 2 页。临时扩展包也已在该版本中验证，Firefox 重新启动后会移除它。[使用步骤](usage.md#safarifirefox-与其他浏览器) · [Mozilla 签名说明](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/)
- **WPS PDF**：制作可切换副本，使用左侧图层列表的眼睛开关。本机 WPS 12.1.0.29161 已人工实测整本长文档，页面、缩放、正文和批注保持原位。
- **Adobe Acrobat / Reader** 打开可切换副本，在「图层 / Layers」中点 `仿生阅读 · Bionic Reading` 左边的方框。Windows 版 Acrobat Reader 26.3.22075.0 已逐页验证 13 种语言的正文加粗及开关前后的系统剪贴板文字。[实机记录](verification.md) · [Adobe 图层说明](https://helpx.adobe.com/acrobat/desktop/edit-documents/pdf-layers/manage-layers.html)
- **Foxit PDF Reader**：制作可切换副本，在左侧导航栏空白处右键选择 Layers，再勾选该图层。2026.2.1.39815 已实机检查 13 种语言页面、图层开关、翻页、页码及缩放保留，开关前后原生复制的全文一致；检查范围见 [验证记录](verification.md)。其他版本的菜单仍可参照 [Foxit 官方手册](https://cdn01.foxitsoftware.com/pub/foxit/manual/reader/en_us/foxit-pdf-reader-user-manual-2026.1.1.pdf)。
- **PDF-XChange Editor**：制作可切换副本，使用 Layers 面板。11.1.1.0 已在本机人工验证图层开关及页码、缩放保留。按 Ctrl+L 打开图层，点击灯泡开关。
- **Firefox 内置 PDF 阅读器** 可直接在 PDF 原页切换。用 Firefox 159.0.1 打开可切换副本，在「管理页面 → 视图 → 图层」勾选 `仿生阅读 · Bionic Reading`。实测 13 种语言，开启后每一页的正文都更深，画面与普通仿生版相同。关闭后逐页恢复原件像素，文字选择层始终一致。[使用步骤](usage.md#safarifirefox-与其他浏览器)
- **macOS Preview**：使用普通仿生版。Apple PDFKit 引擎已验证 13 页的文字、原始像素和普通仿生显示；Preview 完成了打开文件检查，未冒充逐页人工界面验收。
- **SumatraPDF** 可直接打开普通仿生版。Windows 正式版 3.6.1 已用其原生引擎绘制 13 种语言的原文和副本。另用官方便携预览版 3.7.0.24556 逐页导出位图和文字，开层与普通版画面相同，关层恢复原件，四种文件提取的正文一致。[SumatraPDF 渲染命令](https://www.sumatrapdfreader.org/docs/Tool-convert)
- **Apple Books（Mac）** 可导入普通仿生版。在 Books 8.5 中已核对导入的书库记录及其管理的文件，PDF 字节与导出副本一致。从 Mac 书库打开时，正文由 Preview 或默认 PDF 阅读器显示。[Books 实测](https://github.com/Yanxxzz/bionic-pdf-reader/actions/runs/42479896097/job/128729353138) · [Apple 使用说明](https://support.apple.com/guide/books/ibkseed72068/mac)
- **iPhone Safari** 可直接打开普通仿生版。iOS 26.5 的 iPhone 17 Pro 模拟器上已在 Safari 原生 PDF 视图核对截图，普通版正文更深，关闭图层的副本与原件正文像素一致。[iOS 验证记录](https://github.com/Yanxxzz/bionic-pdf-reader/actions/runs/42481026772/job/128732765051)
- **Android MuPDF mini** 可直接打开普通仿生版。在 Android 11 模拟器上，MuPDF mini 1.28.5a 通过系统的文件分享功能打开三份 PDF。正文截图中的深色像素从原件的 688 个增加到普通版的 831 个，关层副本与原件正文逐像素一致。[Android 验证记录](https://github.com/Yanxxzz/bionic-pdf-reader/actions/runs/42482301369/job/128736674308)
- **其他手机 PDF 阅读器** 可选普通仿生版。该副本始终显示词首笔画，应用内的书库、批注、同步方式取决于所用阅读器。
- **Safari** 在本地网页阅读器里点「打开 PDF」，通过 macOS 文件窗口选文件。Safari 26.6 和 27.2 均已验证 13 种语言、带标签和无标签文件、原文选择、词首加粗，以及关闭后逐页恢复原始画面。[验证记录](verification.md)

## PDF 支持边界

支持常见嵌入单字节 Type1/CFF、TrueType，以及横排 Identity-H 的 CID TrueType 和常见 CFF1 字体。原始文字、目录、页码、批注与已有图层被保留。文字页的加粗部分使用复用的矢量轮廓。

桌面版在绘制原文字的位置添加笔画，沿用当时的裁剪路径，之后绘制的图像或色块仍能遮住文字。若文字对象内部改变了蒙版等绘图状态，无法在同一条件下加粗的字形保留原样。

制作工具会处理页面实际绘制的嵌套 Form XObject，包括把两个原页并排放置的讲义，以及拥有独立无障碍标签的 Form。转换完成后列出整页没有加入词首笔画的副本页码。竖排 Identity-V、部分复杂 CMap、在不同阅读引擎中指向不同字形的嵌入字体会保留原样。

纯图片扫描页可选本地 Tesseract OCR。可切换版把识别出的词首笔画放进同一组 PDF 图层，原始图像仍可查看。已有 OCR 文字层只保留一份。阅读器中的预制图层沿用导出时的语言和强度。[扫描件操作步骤](usage.md#扫描件本地-ocr)

没有阅读器通用的原生插件接口。本项目的标准 PDF 输出使同一份阅读副本可在多个应用里使用；不修改或注入这些应用。

## 测试结果

可复现测试命令见 [development.md](development.md)。自动测试覆盖 13 种语言示例、空白页、Identity-H、原有图层、原始文字、关闭时原始像素和普通输出。人工检查与自动检查分别记录，文档依据不冒充实机测试。

本次版本的浏览器版本、检查内容和验证边界见 [verification.md](verification.md)。
