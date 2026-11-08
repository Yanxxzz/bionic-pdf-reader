"""Verify a static PDF with the macOS Books library or the iPhone simulator's Safari."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import subprocess
import threading
import time

from PIL import Image, ImageChops
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from bionic_pdf import make_pdf


TITLE = "Native reader compatibility sample"


def make_sample(folder):
    for name in ("original", "static", "off"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    source = folder / "original" / "sample.pdf"
    font = Path(__file__).resolve().parents[1] / "tests/assets/fonts/Latin.ttf"
    pdfmetrics.registerFont(TTFont("SampleLatin", str(font)))
    pdf = Canvas(str(source), pagesize=(320, 420), invariant=1)
    pdf.setTitle(TITLE)
    # Two markers delimit the text in a screenshot independently of the device's zoom and toolbar.
    pdf.setFillColorRGB(.05, .72, .3)
    for y in (220, 285):
        pdf.rect(25, y, 270, 3, fill=1, stroke=0)
    pdf.setFillColorRGB(.12, .12, .12)
    pdf.setFont("SampleLatin", 21)
    pdf.drawString(48, 246, "Reading together")
    pdf.save()
    for name, mode in (("static", "static"), ("off", "switchable")):
        result = make_pdf(source, folder / name / "sample.pdf", mode=mode)
        assert result["glyphs"] > 0


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def books(folder):
    import Quartz
    import Vision
    from Foundation import NSURL

    sample = folder / "static/sample.pdf"
    subprocess.run(["open", "-b", "com.apple.iBooksX"], check=True)
    # On first launch Books shows an introductory sheet. Locate its named button on screen.
    screen = folder / "books-screen.png"
    for _ in range(12):
        time.sleep(1)
        subprocess.run(["screencapture", "-x", str(screen)], check=True)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(screen)), {})
        ok, error = handler.performRequests_error_([request], None)
        assert ok, error
        labels = {line.topCandidates_(1)[0].string(): line.boundingBox() for line in request.results()}
        if "Get Started" in labels and any("Apple Books" in label for label in labels):
            rect = labels["Get Started"]
            size = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()).size
            point = ((rect.origin.x + rect.size.width/2)*size.width,
                     (1 - rect.origin.y - rect.size.height/2)*size.height)
            for event in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
                Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                                   Quartz.CGEventCreateMouseEvent(None, event, point, Quartz.kCGMouseButtonLeft))
            time.sleep(1)
            break
    subprocess.run(["open", "-b", "com.apple.iBooksX", str(sample)], check=True)
    library = Path.home() / "Library/Containers/com.apple.iBooksX/Data/Documents/BKLibrary"
    deadline = time.monotonic() + 75
    diagnostics = {}
    while time.monotonic() < deadline:
        for db in library.glob("*.sqlite"):
            with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ZBKLIBRARYASSET'").fetchone():
                    continue
                rows = list(conn.execute("SELECT ZTITLE, ZPATH FROM ZBKLIBRARYASSET WHERE ZTITLE LIKE ? OR ZPATH LIKE ?",
                                         (TITLE + "%", "%/sample.pdf")))
                diagnostics[db.name] = rows
                for title, path in rows:
                    if path and Path(path).is_file() and Path(path).read_bytes() == sample.read_bytes():
                        version = command("defaults", "read", "/System/Applications/Books.app/Contents/Info",
                                          "CFBundleShortVersionString")
                        return {"app": "macOS Books", "version": version, "title": title,
                                "cataloguedPdfBytesMatch": True}
        time.sleep(1)
    (folder / "books-database.json").write_text(json.dumps(diagnostics, indent=2))
    subprocess.run(["screencapture", "-x", str(screen)], check=False)
    raise AssertionError("Books did not catalogue the exported PDF with its original bytes")


def text_crop(image):
    """Find the colored bars in the Safari screenshot, then return the enclosed text area."""
    red, green, blue = image.convert("RGB").split()
    mask = ImageChops.multiply(green.point(lambda x: 255 if x > 140 else 0),
                               red.point(lambda x: 255 if x < 85 else 0))
    mask = ImageChops.multiply(mask, blue.point(lambda x: 255 if x < 140 else 0))
    box = mask.getbbox()
    if not box or box[2] - box[0] < image.width / 3:
        return None
    x = (box[0] + box[2]) // 2
    rows = [y for y in range(box[1], box[3]) if mask.getpixel((x, y))]
    gaps = [(upper, lower) for upper, lower in zip(rows, rows[1:]) if lower - upper > 15]
    if len(gaps) != 1:
        return None
    upper, lower = gaps[0]
    crop = image.crop((box[0] + 2, upper + 3, box[2] - 2, lower - 2)).convert("L")
    if sum(crop.histogram()[:110]) < 100:
        return None
    return crop


def iphone(folder):
    devices = json.loads(command("xcrun", "simctl", "list", "devices", "available", "-j"))["devices"]
    choices = [(tuple(map(int, runtime.split(".iOS-")[1].split("-"))), device)
               for runtime, items in devices.items() if ".iOS-" in runtime
               for device in items if device["name"].startswith("iPhone")]
    version, device = max(choices, key=lambda row: row[0])
    udid = device["udid"]

    def sim(*args, check=True):
        subprocess.run(["xcrun", "simctl", *args], check=check)

    sim("bootstatus", udid, "-b")
    sim("ui", udid, "appearance", "light")
    sim("launch", udid, "com.apple.mobilesafari")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=folder))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    shots = {}
    try:
        for mode in ("original", "static", "off"):
            url = f"http://127.0.0.1:{server.server_port}/{mode}/sample.pdf"
            sim("openurl", udid, url)
            path = folder / f"iphone-{mode}.png"
            deadline = time.monotonic() + 120
            retry = time.monotonic() + 45
            previous = None
            while time.monotonic() < deadline:
                time.sleep(2)
                sim("io", udid, "screenshot", str(path))
                with Image.open(path) as shot:
                    crop = text_crop(shot)
                if crop is not None and previous is not None and crop.size == previous.size:
                    if crop.tobytes() == previous.tobytes():
                        shots[mode] = crop
                        break
                previous = crop
                if crop is None and time.monotonic() > retry:
                    sim("openurl", udid, url)
                    retry = deadline
            assert mode in shots, f"Safari did not display stable PDF text in {mode}"
    finally:
        server.shutdown()
        server.server_close()
    original, static, off = (shots[name] for name in ("original", "static", "off"))
    assert original.size == static.size == off.size
    assert original.tobytes() == off.tobytes()
    dark_pixels = [sum(img.histogram()[:110]) for img in (original, static)]
    assert dark_pixels[1] > dark_pixels[0]
    return {"app": "Safari PDF viewer", "simulator": device["name"], "iOS": version,
            "originalAndOffMatch": True, "originalAndStaticInkPixels": dark_pixels}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("reader", choices=("books", "iphone"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    folder = args.output.resolve()
    make_sample(folder)
    result = (books if args.reader == "books" else iphone)(folder)
    (folder / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(result)
