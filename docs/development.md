# 开发、验证与发布

## 结构

- `extension/`：浏览器阅读器、分词规则、带修改标记的 PDF.js 与许可。
- `src/bionic_pdf/`：命令行、GUI、Unicode 词界、字体轮廓和 PDF 制作器。
- `tests/`：字素／语言规则、PDF 文本与像素、CID 字体和已有图层、真实浏览器与扩展测试。
- `scripts/`：原创示例、开放字体子集、Windows 程序和发布包构建。
- `docs/`：安装、兼容性、语言与开发说明。

## 本地验证

```sh
python -m pip install -e ".[dev]"
npm ci
npx playwright install chromium firefox
python scripts/make_examples.py
python -m pytest
npm test
npm run test:browser
npm run test:extension
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

## 维护与发布

1. 同步 `pyproject.toml`、Python `__version__`、扩展 `manifest.json` 和 `package.json` 的版本。
2. 更新 CHANGELOG、兼容性与语言范围。新的阅读器应分别记录文档依据和实测结果。
3. 运行测试，构建，检查源码与包中不包含私人 PDF、机器路径或凭据。
4. 推送到私有仓库，等待 CI 的测试、浏览器和 Windows 构建通过。
5. 创建 `v版本` tag 和草稿 Release，上传包、许可和 SHA256 清单。
6. 完成最终验收后公开仓库并发布 Release。

GitHub 工作流只在测试代码或原创样例上运行。通过 `workflow_dispatch` 可重新测试；不会自动上传用户文档，也不自动改变仓库可见性。

## 已知边界

PDF 处理依赖固定版本的 pypdf 私有字体编码接口，升级时需要跑完整回归。PDF.js 的补丁也需在升级后重验 CSP、原始像素、字距、复制层与公式。复杂脚本、专业排版与阅读效果需要额外人工和用户验证。
