# Project vocabulary

- **Original PDF**: the user's input. Never overwritten or uploaded by this tool.
- **Reading copy**: a PDF retaining the original text, layout and document structure, with vector word-prefix emphasis added.
- **Switchable copy**: a reading copy whose emphasis is a standard optional-content layer, initially off.
- **Static copy**: a reading copy whose emphasis is always visible; used by readers without a layer control.
- **Glyph capture**: original glyphs with geometry and optional ActualText, collected before prefix selection.
- **Prefix plan**: the selected original glyphs for a captured page. Selection considers complete words across drawing runs.
- **Native acceptance**: opening a real disk file and operating the actual application. Engine tests and documentation alone do not count.

The supported languages are the 13 codes in `examples/languages.json`. Browser and Python runtimes share authored examples and expected cases, not a cross-language execution framework. See `docs/architecture.md` for responsibilities.
