import argparse
import json
from pathlib import Path
from . import __version__, make_pdf
from .words import LANGUAGES

def main(argv=None):
    parser = argparse.ArgumentParser(description='Create a local bionic reading PDF without replacing its original text.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--mode', choices=['switchable','static'], default='switchable', help='Layer switch, or always-visible emphasis for other readers')
    parser.add_argument('--language', choices=['auto',*LANGUAGES], default='auto', help='Document language; auto segments words without detecting language')
    parser.add_argument('--weight', type=float, default=0.026)
    args = parser.parse_args(argv)
    if not 0.005 <= args.weight <= 0.08: parser.error('--weight must be between 0.005 and 0.08')
    try:
        result = make_pdf(args.source, args.target, weight=args.weight, mode=args.mode, locale=args.language)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, ensure_ascii=False))
    return 0
