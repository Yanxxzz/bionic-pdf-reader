import argparse
import io
import json
import sys
from pathlib import Path
from pypdf.errors import PyPdfError
from . import __version__, make_pdf
from .document import PageSelectionError, SignatureLossError
from .converter import DEFAULT_WEIGHT, InvalidWeightError, page_summary
from .words import LANGUAGES

def main(argv=None):
    # Desktop automation reads the progress, translated summary and JSON from a pipe.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and not stream.isatty() and stream.encoding.lower() != 'utf-8':
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Create a local bionic reading PDF without replacing its original text.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--mode', choices=['switchable','static'], default='switchable', help='Layer switch, or always-visible emphasis for other readers')
    parser.add_argument('--language', choices=['auto',*LANGUAGES], default='auto',
                        help='Auto and en use reference prefixes for plain English letters. Other languages use half words. Auto keeps the source language tag.')
    parser.add_argument('--weight', type=float, default=DEFAULT_WEIGHT)
    parser.add_argument('--pages', metavar='RANGES',
                        help='Physical pages in output order, e.g. 1-3,7,5-4. Defaults to the whole document.')
    parser.add_argument('--ocr', action='store_true',
                        help='Recognize scanned pages with local Tesseract and emphasize words on the original image.')
    parser.add_argument('--allow-signature-loss', action='store_true',
                        help='Export a reading copy even though its original digital signature will be invalid.')
    args = parser.parse_args(argv)
    def progress(current,total):
        if current % 50 == 0 or current == total:
            print(f'PROGRESS {current}/{total}',flush=True)
    try:
        result = make_pdf(args.source, args.target, pages=args.pages, weight=args.weight, mode=args.mode, locale=args.language,
                          progress=progress, allow_signature_loss=args.allow_signature_loss, ocr=args.ocr)
    except (InvalidWeightError, PageSelectionError) as error:
        parser.error(str(error))
    except SignatureLossError as error:
        parser.exit(1, f'{error}\n可在浏览器中直接阅读原件。若接受签名失效，请添加 --allow-signature-loss 后重试。\n')
    except (OSError, ValueError, PyPdfError) as error:
        parser.exit(1, f'无法生成阅读副本：{error}\n')
    print(f'DONE {args.target}',flush=True)
    print(page_summary(result['unemphasized_pages']))
    print(json.dumps(result, ensure_ascii=False))
    return 0
