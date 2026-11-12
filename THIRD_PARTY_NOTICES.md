# Third-party notices

Original project code: MIT, Copyright (c) 2026 Yanxxzz.

- **yitong2333/Bionic-Reading**: English reference word-length/common-word rule inspired by the MIT project, Copyright (c) 2024 一桐. Full MIT attribution is retained in `extension/THIRD_PARTY_NOTICES.txt`.
- **Mozilla PDF.js 5.6.205** uses Apache-2.0. See `extension/vendor/LICENSE_PDFJS` and the notices shipped with the fonts, CMaps, ICC and WASM resources. Changes to `pdf.mjs` and `pdf.worker.min.mjs` are labeled `Bionic PDF Reader modification`. They expose positioned glyph masks and ActualText metadata, draw display-only strokes, and expose the HTTP ETag and hashes of received bytes for reading progress. Background search captures glyph positions without waiting for screen refresh or painting ordinary text. Reapply the worker changes with `scripts/patch_pdfjs_worker.py`. Text-layer geometry CSS is adapted from PDF.js.
- **pypdf 6.21.4**: BSD-3-Clause, see `licenses/pypdf/`.
- **fontTools 4.63.0**: MIT and component notices, see `licenses/fonttools/`.
- **FreeType / freetype-py**. Embedded PostScript Type 1 outlines use the FreeType Project (www.freetype.org) under the FreeType License. The Python binding uses the BSD 3-Clause license. Both license texts accompany the Windows package.
- **regex**: Apache-2.0 and CNRI-Python notices, retained from its installed distribution when bundling.
- **Noto demo fonts**: SIL Open Font License 1.1, sources under https://github.com/google/fonts/tree/main/ofl . Renamed, subset font files and the corresponding OFL texts are in `tests/assets/fonts/`. Rebuild with `scripts/prepare_demo_fonts.py`. These fonts are used for original demonstration content and tests, not to replace user fonts.
- **PyInstaller**: used only to build the Windows application; its license includes the exception for distributing bundled applications. See the build distribution's license bundle.
- **pypdfium2, PDFium and Pillow** render scanned pages and match their ink to locally recognized letters. They are optional Python dependencies and their license texts accompany the Windows bundle. Tesseract 5 and its language data are installed separately by the user.
- **Playwright, pytest and ReportLab** are development and testing tools.

The Windows release accompanies its executable with third-party license files. The browser ZIP includes PDF.js and its resource licenses. Dependency versions are specified in `pyproject.toml` and `package-lock.json`.

Independent project, not affiliated with the Bionic Reading trademark owner or the authors/vendors of the referenced products. Product names identify compatibility only.

`extension/compat.mjs` and `extension/pdf-worker.mjs` are project-owned MIT code. They provide ReadableStream async iteration only where it is missing, including in the module worker. No browser-native implementation is replaced. This addresses the shipping Safari compatibility issue described in [PDF.js issue 21924](https://github.com/mozilla/pdf.js/issues/21924).
