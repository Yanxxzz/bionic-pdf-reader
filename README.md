# Bionic PDF Reader · 仿生 PDF 阅读

[English](README.en.md) · [下载](https://github.com/Yanxxzz/bionic-pdf-reader/releases/latest) · [使用说明](docs/usage.md) · [阅读器兼容性](docs/compatibility.md) · [多语言](docs/languages.md)

**保留 PDF 原页、原文与图表，随时切换词首加粗。文件在本机处理。**

想寻找「加快英语阅读速度」或「更容易的英语阅读」的工具？这个项目让你尝试仿生阅读（Bionic Reading）：强调词语前部，保留后部字重。你可以根据自己的体验选择是否开启。


![浏览器阅读预览](docs/assets/browser-preview.png)

## 选择一种用法

- **Chrome / Edge 扩展**：打开本地 PDF，在同一页切换「原始／仿生」，支持强度、规则、语言、目录、缩放和复制。快捷键 `Alt+B`。
- **Windows 制作工具**：下载 Windows 压缩包，解压后双击 `BionicPDF.exe`，无需安装 Python。选择 PDF，生成「可切换版」或「普通仿生版」。
- **WPS / Acrobat / Foxit / PDF-XChange**：打开制作好的可切换副本，在阅读器的「图层」列表开关 `仿生阅读 · Bionic Reading`。
- **Firefox / Safari 及其他浏览器**：Windows 工具里的「在浏览器中阅读」可打开本地阅读页；源码用户也可启动本地网页版本。
- **Preview / SumatraPDF / 手机阅读器等**：选择「普通仿生版」，打开即可看到加粗，不依赖图层开关。

可切换副本需要制作一次，以后可在原页开关。它使用标准 PDF 图层；不是接管所有阅读器内部绘制的通用加载项。各阅读器的实测与文档依据分别列在[兼容性说明](docs/compatibility.md)中。

## 快速开始

### 浏览器扩展

1. 在 [Releases](https://github.com/Yanxxzz/bionic-pdf-reader/releases) 下载 `bionic-pdf-chrome-edge-*.zip` 并完整解压。
2. Chrome 打开 `chrome://extensions`；Edge 打开 `edge://extensions`。
3. 开启开发者模式，选择「加载已解压的扩展程序」，选择含 `manifest.json` 的文件夹。
4. 点击扩展图标，选择本地 PDF，再切换阅读模式。

扩展通过自己的阅读页使用；当前不接管网页 PDF 或浏览器内置 PDF 工具栏。Firefox 的临时加载包另见[安装说明](docs/usage.md)，它尚未取得 Mozilla 签名。

### Windows 程序

1. 下载 `bionic-pdf-windows-x64-*.zip`，完整解压后双击 `BionicPDF.exe`。
2. 选择原始 PDF 和阅读副本的保存位置。
3. 选择「可切换版」或「普通仿生版」，按需要选择文档语言。
4. 生成后打开副本；或点击「在浏览器中阅读」直接使用本地阅读页。使用网页期间保持程序开启。

原始文件保持不变。扫描图片需要先做 OCR；字体与文字编码会影响可强调的范围。软件内「使用指南」和下载包内 `使用指南.html` 提供阅读器选择、安装和配置步骤。

## 多语言

正式支持 **13 种语言**：英语、法语、德语、西班牙语、葡萄牙语、意大利语、荷兰语、波兰语、土耳其语、越南语、俄语、乌克兰语和希腊语。语言选择在浏览器、Windows 工具和命令行中保持一致。

组合重音保持完整；连字与分成多个绘制片段的单词会一起分析。中文、日文、韩文及其他文字不在本版支持范围，相关文字保留原样。详见[语言支持与限制](docs/languages.md)。

## 开发与测试

需要 Python 3.11+ 和 Node.js 22+。Windows GUI 需要 Python 自带的 tkinter；命令行可独立使用。

```sh
python -m venv .venv
# 激活虚拟环境后：
python -m pip install -e ".[dev]"
npm ci
npx playwright install chromium firefox
python scripts/make_examples.py
npm run fixtures:shaped
python -m pytest
npm test
npm run test:browser
npm run test:extension
npm run test:shaped
```

命令行生成阅读副本：

```sh
bionic-pdf input.pdf switchable.pdf --mode switchable --language auto
bionic-pdf input.pdf readable.pdf --mode static --language fr
bionic-pdf-gui
```

源码版网页阅读器：

```sh
python -m http.server 8765 --bind 127.0.0.1 --directory extension
# 浏览器打开 http://127.0.0.1:8765/reader.html
```

构建、测试证据与发布流程见 [开发说明](docs/development.md)。

## 实现与许可

浏览器基于带少量字形绘制修改的 PDF.js，直接强调原字形。PDF 制作器复用嵌入字体的矢量轮廓，正文仍只有一份；不会用另一份文字覆盖页面。支持常见单字节 Type1/CFF、TrueType，以及带有效 Unicode 映射的 Identity-H / CID TrueType。扫描页、竖排、部分特殊字体、嵌套表单里的文本目前保留原样。

项目自有代码采用 [MIT](LICENSE)。词首参考规则致谢 [yitong2333/Bionic-Reading](https://github.com/yitong2333/Bionic-Reading)；PDF.js、pypdf、fontTools 和示例字体分别保留原许可，见 [第三方说明](THIRD_PARTY_NOTICES.md)。本项目与 Bionic Reading 商标持有人、WPS、Adobe、Foxit、Mozilla 无隶属关系。

仓库与发布包只包含工具和原创示例，不附带教材、用户 PDF 或阅读记录。处理程序不上传 PDF；阅读器本身的云同步设置由该阅读器管理。
