"""PyInstaller entry point, with a noninteractive conversion smoke-test path."""
import sys
import io

if sys.stdout is None:sys.stdout=io.StringIO()
if sys.stderr is None:sys.stderr=io.StringIO()

if '--smoke-gui' in sys.argv:
    import tkinter as tk
    from bionic_pdf.gui import Maker
    root=tk.Tk();root.withdraw();app=Maker(root)
    assert len(app.language_options)==14
    app.show_help()
    guides=[w for w in root.winfo_children() if isinstance(w,tk.Toplevel)]
    assert len(guides)==1
    guides[0].withdraw();root.update_idletasks()
    assert root.winfo_reqheight()<=650
    guides[0].destroy();root.destroy()
elif '--cli' in sys.argv:
    from bionic_pdf.cli import main
    raise SystemExit(main(sys.argv[2:]))
else:
    from bionic_pdf.gui import main
    main()
