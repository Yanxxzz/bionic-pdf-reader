# 开发、验证与发布

## 结构

浏览器用 PDF.js 在原页上切换显示。桌面工具用 pypdf 写入阅读副本，fontTools 和 FreeType 提供嵌入字体的字形轮廓。

- 浏览器的 `reader.mjs` 负责打开文档、导航和阅读设置。`page-view.mjs` 在一个页面视图内安排绘制、取消过时的请求、复用词首结果并保留可选择的文字层。`layout.mjs` 根据字形位置计算词首，处理复制用的文字。
- `tab-source.mjs` 识别来源 PDF 和链接里的书签。刷新时比对来源地址的摘要，阅读位置和文档标识保存在当前标签页的 `sessionStorage` 中。书内引用和来源书签共用目标页与坐标的解析。`navigation.mjs` 换算落点、解析进度并筛选网页与 DOI 链接。
- `search.mjs` 中的 `BookSearch` 按需索引文档，管理当前命中、前后查找和取消，并把跨行或大小写转换后的命中映射回原文。`find-bar.mjs` 处理输入和状态显示。`page-view.mjs` 使用原文范围绘制高亮，可对齐的水平文字复用 PDF 实际绘制的字形坐标。
- 桌面端的 `document.py` 识别数字签名、解析页码范围并重建导航。`pdf_text.py` 读取文字和绘图指令，`layout.py` 选出需要强调的字形。`embedded_font.py` 解析嵌入字体的轮廓，`converter.py` 将轮廓写入阅读副本。命令行和图形界面共用 `make_pdf()`。
- `scan.py` 在开启 OCR 时按需使用 PDFium、Pillow 和本机 Tesseract。识别后的词与文字页共用 `words.py` 里的选词规则。已有文本的页面优先使用原字体。
- 带标签文档的选页映射集中在 `tagged.py`，负责阅读顺序、标记内容与批注的父级索引。整本导出直接克隆原结构。
- 修改阅读规则时，浏览器和桌面端分别改 `words.mjs` 和 `words.py`。两端的排版测试共用 `tests/layout-cases.json`，可以在同一个例子里指定字形位置和预期加粗范围。
- `tests/`：字素／语言规则、PDF 文本与像素、CID 字体和已有图层、真实浏览器与扩展测试。
- `scripts/`：原创示例、开放字体子集、Windows 程序和发布包构建。
- `docs/`：安装、兼容性、语言与开发说明。

## 本地验证

```sh
python -m pip install -e ".[dev]"
npm ci
npx playwright install chromium firefox
python scripts/make_examples.py
npm run fixtures:shaped
python scripts/prepare_shaped_outputs.py
python -m pytest
npm test
npm run test:browser
npm run test:extension
npm run test:shaped
```

浏览器测试默认使用隔离的 Chromium 和 Firefox。已安装的 Chrome / Edge 可设置 `BROWSERS=chrome,edge,firefox`；扩展可设置 `EXTENSION_CHANNEL=chrome`。扩展测试仅对临时配置使用调试接口，不修改日常浏览器。

测试例句为原创，字体可再分发；生成的 PDF 与测试截图放在忽略的 `.tmp/`、`test-results/` 中。README 预览只能使用原创样例截图。

## 构建

```sh
python -m build
python scripts/build_packages.py
# Windows:
python -m pip install -e ".[windows]"
python scripts/build_windows.py
python scripts/build_packages.py
```

输出在 `dist/`，含 Chrome/Edge ZIP、Firefox 临时开发 ZIP、网页 ZIP、Python 包及 SHA256 校验清单。Windows 可执行文件为独立便携版，不要求安装 Python。它不是带系统安装向导的 MSI，也没有商店签名。

在装有 `.[windows]` 的构建环境中运行 `python scripts/audit_release.py dist`，核对 6 个下载包的 SHA256、内置指南、许可证和归档内容。打包前会比对 EXE 的桌面源码摘要和内置阅读器文件。审计时会从最终 Windows ZIP 取出 EXE，用已打包的 wheel 和浏览器 ZIP 再核对一次。同一版本号的旧构建也会被检出。

## 维护与发布

1. 同步 `pyproject.toml`、Python `__version__`、扩展清单、阅读页版本标识、`package.json` 和 `package-lock.json` 的版本。
2. 阅读器、文档语言或下载方式有变化时，先在 `docs/compatibility.md` 和 `docs/verification.md` 更新适配方式与实测范围，再同步中英文 README 的选用表和 GitHub About 的简介、主题。README 的下载入口指向 `releases/latest`，版本细节记在 CHANGELOG。
3. 运行测试，构建，检查源码与包中不包含私人 PDF、机器路径或凭据。
4. 推送发布分支，等待 CI 的 Python、浏览器、macOS 阅读引擎和 Windows 打包测试通过。
5. 创建 `v版本` tag 和草稿 Release，上传包、许可和 SHA256 清单。
6. 完成最终验收后发布 Release；不改变仓库可见性。

GitHub 工作流只在测试代码或原创样例上运行。通过 `workflow_dispatch` 可重新测试；不会自动上传用户文档，也不自动改变仓库可见性。

## Firefox 签名

Firefox 自分发签名使用项目固定的扩展 ID `bionic-pdf-reader@yanxxzz`。先运行 `python scripts/build_packages.py`，将生成的 Firefox ZIP 解压到 `firefox-build`。用 Mozilla 的 `web-ext` 校验这个目录，确保实际发送的包已包含完整的本地阅读器。

```sh
npx web-ext@10.8.0 lint --source-dir firefox-build
```

具有该扩展发布权限的维护者在本机设置 `WEB_EXT_API_KEY` 和 `WEB_EXT_API_SECRET`，检查扩展版本号后运行签名命令。凭据由 Mozilla Add-on Developer Hub 签发。下列命令会向 Mozilla 提交扩展文件，审核签名后将 XPI 下载到 `signed-firefox`。上传签名的 XPI 到 Release 前，在正式版 Firefox 的 `about:addons` 中选择「从文件安装附加组件」，重启并验证阅读器仍然可用。[Mozilla 签名与分发说明](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/) · [web-ext sign 参数](https://extensionworkshop.com/documentation/develop/web-ext-command-reference/#web-ext-sign)

```sh
npx web-ext@10.8.0 sign --channel unlisted --source-dir firefox-build --artifacts-dir signed-firefox
```

0.5.0 的 Firefox 构建通过了上述本地校验，报告 0 个错误和 7 个警告。其中 2 个涉及老版本 Firefox 对数据收集声明的支持，另外 5 个指向随包分发的 PDF.js 中的动态代码或模块导入。可按发布提交追溯 PDF.js 版本、许可证和工作线程补丁。[第三方组件说明](../THIRD_PARTY_NOTICES.md)

## 已知边界

桌面端复用 pypdf 的字体解码和内容流解析器，在原始字节中定位文字对象的起点（`BT`）。升级 pypdf 时需验证内联图像、注释和字符串里的同名字符，以及开关前后的像素和复制文字。PDF.js 的补丁也需在升级后重验 CSP、原始像素、字距、复制层与公式。复杂脚本、专业排版与阅读效果需要额外人工和用户验证。

## 实测记录

测试覆盖范围和本次版本的实测记录见 [verification.md](verification.md)。浏览器生成的带标签 / 不带标签 PDF 需要先运行 `npm run fixtures:shaped`；否则 Python 的两个对应集成测试会明确跳过。CI 的浏览器任务会生成并实际运行它们，不把跳过作为通过证据。

macOS 任务使用 Apple 提供的 Safari / safaridriver 与 PDFKit；不是用 Linux WebKit 冒充 Safari。原始文字、图层关闭像素和普通仿生输出分别比较。Preview 进程启动仅证明能打开文件，不等同于人工界面验收。

常规 Safari 测试用独立输入框探测文件读取。驱动无法读取磁盘文件时，渲染测试使用相同字节的内存 File，输入方式写入 `safari-environment.json` 和每页报告。系统文件选择另在普通 Safari 窗口验收，通过 macOS 选取磁盘文件，核对文件摘要，并比较模式开关前后的页面像素。原生界面的版本和记录见 [验证记录](verification.md)。
