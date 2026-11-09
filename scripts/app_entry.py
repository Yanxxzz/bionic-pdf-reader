"""PyInstaller entry point, with a noninteractive conversion smoke-test path."""
import sys
import io

if sys.stdout is None:sys.stdout=io.StringIO()
if sys.stderr is None:sys.stderr=io.StringIO()

def smoke_gui():
    import tkinter as tk
    from bionic_pdf.gui import Maker
    root=tk.Tk();root.withdraw();app=Maker(root)
    assert len(app.language_options)==14
    assert app.cover.width() > 0 and app.cover.height() > 0
    app.show_help()
    guides=[w for w in root.winfo_children() if isinstance(w,tk.Toplevel)]
    assert len(guides)==1
    guides[0].withdraw();root.update_idletasks()
    assert root.winfo_reqheight()<=650
    guides[0].destroy();root.destroy()
    from bionic_pdf.local_reader import start_reader
    from urllib.request import urlopen
    url=start_reader()
    for asset in ('reader.html','pdf-worker.mjs','compat.mjs','assets/reading-room.png'):
        with urlopen(url.replace('reader.html',asset),timeout=10) as response:
            assert response.status==200 and response.read()
            if asset.endswith('.mjs'):assert 'javascript' in response.headers['Content-Type']
            if asset.endswith('.png'):assert response.headers.get_content_type() == 'image/png'

if '--smoke-gui' in sys.argv:
    try:smoke_gui()
    except Exception:
        import os
        import traceback
        from pathlib import Path
        (Path(os.environ.get('TMP','.tmp'))/'gui-smoke-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise SystemExit(1)
elif '--cli' in sys.argv:
    from bionic_pdf.cli import main
    raise SystemExit(main(sys.argv[2:]))
else:
    from bionic_pdf.gui import main
    main()
