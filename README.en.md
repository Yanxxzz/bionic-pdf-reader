# Bionic PDF Reader

[Download the latest release](https://github.com/Yanxxzz/bionic-pdf-reader/releases/latest) · [中文](README.md) · [Setup guide](docs/usage.md) · [Reader compatibility](docs/compatibility.md)

With bionic reading, the word *reading* appears as **read**ing. Turn word-prefix emphasis on or off on the original PDF page while figures, formulas and page numbers stay in place. Text stays selectable and files are processed on your computer.

If you want to read English faster or try a different way to read long papers, open a familiar paragraph. Press `Alt+B` (`Option+B` on Mac) to compare the two views, then adjust the strength to find a weight you like.

## Choose your PDF reader

| Where you read | What to use | How it works |
| --- | --- | --- |
| Chrome or Edge | Browser extension | Open a local PDF from the extension and toggle word-prefix emphasis in its reader tab. |
| Safari or Firefox | Local web reader | Choose a PDF in the system file picker and toggle on the page. Firefox also has a temporary development extension. |
| WPS PDF, Adobe Acrobat Reader, Foxit PDF Reader or PDF-XChange Editor | Switchable PDF | Generate a copy once. Use the eye or checkbox beside `仿生阅读 · Bionic Reading` in the reader’s Layers panel. |
| macOS Preview, SumatraPDF, Apple Books or a phone or tablet reader | Static PDF | Open the copy like any other PDF. Emphasis is always visible. Open the source file for the original appearance. |

In Acrobat Reader, the same selection copied byte-for-byte identical text with emphasis off and on across all 13 test languages. Safari 26.6 and 27.2 each restored the original screen pixels across 26 page cases. Native layer switching was also checked in WPS, Foxit and PDF-XChange. Preview passed a file-opening check. Mobile and other readers use the standard PDF export. [Verification by reader](docs/verification.md)

![English PDF with word-prefix emphasis in the browser reader](docs/assets/browser-preview.png)

## Open your first file

- **Chrome / Edge** — Extract the `chrome-edge` ZIP. Enable developer mode at `chrome://extensions` or `edge://extensions`, choose **Load unpacked**, and select the folder containing `manifest.json`. Open the extension from the toolbar.
- **Windows** — Extract the entire `windows-x64` ZIP and run `BionicPDF.exe`. Choose a source PDF, a different output filename and either switchable or static mode. The portable app includes its own runtime and can also start the local web reader.
- **Safari / Firefox** — Extract the `web-reader` ZIP. From the folder containing `reader.html`, run the command below with Python 3. Open `http://127.0.0.1:8765/reader.html` and choose your file.

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

The in-app guide and the offline `使用指南.html` in each ZIP explain the controls. The Firefox temporary extension must be loaded again after restarting Firefox. [Setup guide](docs/usage.md)

## Document languages and fonts

The reader supports **13 document languages** across Latin, Cyrillic and Greek scripts. They are English, French, German, Spanish, Portuguese, Italian, Dutch, Polish, Turkish, Vietnamese, Russian, Ukrainian and Greek. The browser offers an English reference rule and a half-word rule. The desktop converter uses the half-word rule with whole grapheme clusters and preserves the original ligature glyphs. [Language support](docs/languages.md)

Start with a PDF whose text you can select. Image-only scans need OCR first. Vertical text, certain embedded fonts and text inside nested Form XObjects can retain their original appearance. [PDF and font compatibility](docs/compatibility.md)

## Command line and development

From a source checkout with Python 3.11 or later, install the converter and make a switchable or static copy.

```sh
python -m pip install .
bionic-pdf source.pdf switchable.pdf --mode switchable --language en
bionic-pdf source.pdf mobile.pdf --mode static --language en
```

The browser reader draws with PDF.js. The desktop converter uses pypdf and fontTools to add vector outlines while retaining the original text. The Python wheel contains the converter. The web reader is included in the web ZIP, source checkout and Windows bundle. [Architecture, tests and builds](docs/development.md)

## License and credits

The project code is MIT licensed. The English reference rule draws on yitong2333’s Bionic-Reading. PDF.js, bundled fonts and other dependencies retain their own licenses. [MIT license](LICENSE) · [Reference project](https://github.com/yitong2333/Bionic-Reading) · [Third-party notices](THIRD_PARTY_NOTICES.md)
