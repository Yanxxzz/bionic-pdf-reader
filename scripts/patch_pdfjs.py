"""Rebuild or verify the two customized PDF.js files from the official npm archive."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory

SCRIPTS = Path(__file__).resolve().parent
VENDOR = SCRIPTS.parent / 'extension' / 'vendor'
ARCHIVE_SHA256 = 'e196561c11faacf04e224e177b5d792619136cec5bd2274d8c743e577239ebc7'


def patch_worker(source):
    # The upstream worker is minified onto one line. Match the individual hooks
    # so that a reviewer can see exactly which operators are being changed.
    changes = (
        ('e=[e[0].name,e[1]instanceof Dict?e[1].get("MCID"):null];break;',
         'e=[e[0].name,e[1]instanceof Dict?e[1].get("MCID"):null,e[1]instanceof Dict&&'
         'typeof e[1].get("ActualText")==="string"?stringToPDFString(e[1].get("ActualText")):null];break;'),
        ('type:"beginMarkedContentProps",id:Number.isInteger(e)?',
         'type:"beginMarkedContentProps",actualText:j[1]instanceof Dict&&typeof j[1].get("ActualText")'
         '==="string"?stringToPDFString(j[1].get("ActualText")):null,id:Number.isInteger(e)?'),
        ('h.on("GetData",function(e){return n.requestLoadedStream().then(e=>e.bytes)});',
         'h.on("GetData",function(e){return n.requestLoadedStream().then(e=>e.bytes)});'
         'h.on("BionicResumeProof",()=>bionicStreamProof(n.pdfDocument.stream));'),
    )
    for old, new in changes:
        if source.count(old) != 1:
            raise ValueError('PDF.js worker changed; review the corresponding operator.')
        source = source.replace(old, new)
    return ('/* Bionic PDF Reader modification: verify received byte ranges on a reader-tab reload. */\n'
            'import {streamByteProof as bionicStreamProof} from "../reading-progress.mjs";\n'
            '/* Bionic PDF Reader modification: forward decoded ActualText as an additional marked-content operator argument. */\n'
            + source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, help='pdfjs-dist-5.6.205.tgz')
    parser.add_argument('--write', action='store_true', help='replace the vendored files after rebuilding')
    args = parser.parse_args()
    if hashlib.sha256(args.archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        parser.error('Expected the unmodified pdfjs-dist 5.6.205 npm archive.')
    with tarfile.open(args.archive) as archive, TemporaryDirectory() as directory:
        display = Path(directory) / 'pdf.mjs'
        display.write_bytes(archive.extractfile('package/build/pdf.mjs').read())
        subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply', '--no-index', '--whitespace=nowarn',
                        str(SCRIPTS / 'pdfjs-display.patch')],
                       cwd=directory, check=True)
        worker = archive.extractfile('package/build/pdf.worker.min.mjs').read().decode('utf-8')
        rebuilt = {display.name: display.read_bytes(), 'pdf.worker.min.mjs': patch_worker(worker).encode('utf-8')}
    for name, data in rebuilt.items():
        target = VENDOR / name
        if args.write:
            target.write_bytes(data)
        elif data != target.read_bytes():
            parser.exit(1, f'{name} differs from the reproducible build.\n')
    print('PDF.js display and worker match the pinned build.')


if __name__ == '__main__':
    main()
