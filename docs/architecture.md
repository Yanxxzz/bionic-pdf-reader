# Architecture

There are two delivery paths: live browser rendering and a PDF reading-copy converter. They have different drawing interfaces, so each has one implementation. Reader-specific plugins or injected code are unnecessary: desktop readers use standard PDF optional-content layers or the static copy.

## Browser

`reader.mjs` owns the document lifecycle, render cancellation, page navigation and controls. It adapts PDF.js to the reader. Keeping these related operations together avoids a collection of modules that only forward calls.

`layout.mjs` owns glyph capture, geometric word reconstruction, prefix planning and ActualText repair. `words.mjs` owns language boundaries and word-prefix rules. There is one glyph planner. A capture/render mismatch is reported as an error instead of silently selecting glyphs with another algorithm.

`compat.mjs` and `pdf-worker.mjs` adapt older Safari stream iteration and the packaged module worker. PDF.js changes stay localized to its drawing hook; see `scripts/patch_pdfjs_actualtext.py`.

## PDF conversion

The public interface is `make_pdf(source, target, ..., progress=None)`.

- `converter.py` owns PDF reading/writing, original drawing-state tracking, reusable vector glyph forms and the optional layer.
- `pdf_text.py` decodes original character codes and holds the drawing state needed by the converter. It does not select or rewrite word prefixes.
- `layout.py` selects original glyphs from page geometry; `words.py` supplies language and prefix rules.
- `cli.py` formats terminal messages. `gui.py` sends `(current, total)` progress updates to its existing UI queue. The converter never redirects or parses console output.
- `local_reader.py` serves packaged browser files on loopback for the Windows launcher.

Original text is not rewritten or duplicated. Emphasis reuses embedded glyph outlines as vector forms. Unsupported content remains unchanged. This accounts for the necessary font and PDF-state code without adding reader-specific branches.

## Regression surfaces

Tests exercise `make_pdf`, `GlyphCapture` / `planGlyphs`, real browser pages and packaged applications. Shared language and layout cases check behavior across runtimes. PDF tests compare original text and default-off pixels, and preserve existing layers and document structure. Native acceptance separately records application version, input method and observed operations.

The 0.4.1 cleanup deletes the unused text-rewriting engine and the browser's second glyph-selection algorithm. No compatibility wrapper remains for these internal implementations. The public converter interface and reader controls are retained.
