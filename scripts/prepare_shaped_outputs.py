from pathlib import Path
from bionic_pdf import make_pdf
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'.tmp/examples/shaped-tagged.pdf'
make_pdf(source,ROOT/'.tmp/examples/shaped-switchable.pdf')
make_pdf(source,ROOT/'.tmp/examples/shaped-static.pdf',mode='static')
