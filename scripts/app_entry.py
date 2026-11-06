"""PyInstaller entry point, with a noninteractive conversion smoke-test path."""
import sys
import io

if sys.stdout is None:sys.stdout=io.StringIO()
if sys.stderr is None:sys.stderr=io.StringIO()

if '--cli' in sys.argv:
    from bionic_pdf.cli import main
    raise SystemExit(main(sys.argv[2:]))
else:
    from bionic_pdf.gui import main
    main()
