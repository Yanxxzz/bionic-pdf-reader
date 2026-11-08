"""Read a sample in macOS Books, iOS Safari, or Android MuPDF mini."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
from xml.etree import ElementTree

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
    handled = set()
    for _ in range(25):
        time.sleep(1)
        subprocess.run(["screencapture", "-x", str(screen)], check=True)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(screen)), {})
        ok, error = handler.performRequests_error_([request], None)
        assert ok, error
        labels = {line.topCandidates_(1)[0].string(): line.boundingBox() for line in request.results()}
        button = None
        if "Get Started" in labels and any("Apple Books" in label for label in labels):
            button = "Get Started"
        elif "Discover New Books" in labels and "Not Now" in labels:
            button = "Not Now"
        if button and button not in handled:
            rect = labels[button]
            size = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID()).size
            point = ((rect.origin.x + rect.size.width/2)*size.width,
                     (1 - rect.origin.y - rect.size.height/2)*size.height)
            for event in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
                Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                                   Quartz.CGEventCreateMouseEvent(None, event, point, Quartz.kCGMouseButtonLeft))
            handled.add(button)
        elif handled == {"Get Started", "Not Now"} and button is None:
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
                rows = list(conn.execute("SELECT ZTITLE, ZPATH FROM ZBKLIBRARYASSET WHERE ZTITLE LIKE ? OR ZPATH IS NOT NULL",
                                         (TITLE + "%",)))
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
    """Find the two colored bars in a reader screenshot and return the enclosed text area."""
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


def compare_pages(shots):
    original, static, off = (shots[name] for name in ("original", "static", "off"))
    assert original.size == static.size == off.size
    assert original.tobytes() == off.tobytes()
    dark_pixels = [sum(img.histogram()[:110]) for img in (original, static)]
    assert dark_pixels[1] > dark_pixels[0]
    return {"originalAndOffMatch": True, "originalAndStaticInkPixels": dark_pixels}


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
    return {"app": "Safari PDF viewer", "simulator": device["name"], "iOS": version, **compare_pages(shots)}


def choose_android_pdf(folder, package, name):
    """Select a downloaded file in the system picker launched by MuPDF mini."""
    command("adb", "shell", "am", "force-stop", package)
    command("adb", "shell", "am", "start", "-W", "-n", package + "/.LibraryActivity")
    visited = set()
    for _ in range(12):
        command("adb", "shell", "uiautomator", "dump", "/sdcard/bionic-ui.xml")
        xml = command("adb", "shell", "cat", "/sdcard/bionic-ui.xml")
        nodes = ElementTree.fromstring(xml).findall(".//node")
        if any(node.get("package") == package for node in nodes):
            activity = command("adb", "shell", "dumpsys", "activity", "activities")
            if any("ResumedActivity" in line and "DocumentActivity" in line for line in activity.splitlines()):
                return
        labels = {node.get("content-desc"): node.get("bounds") for node in nodes if node.get("content-desc")}
        labels.update({node.get("text"): node.get("bounds") for node in nodes if node.get("text")})
        for target in (name, name.removesuffix(".pdf"), "Open", "OPEN", "Downloads", "Show roots"):
            if target in labels and target not in visited:
                x, y, right, bottom = map(int, re.findall(r"\d+", labels[target]))
                print(f"Document picker: {target} at {labels[target]}", flush=True)
                command("adb", "shell", "input", "tap", str((x + right) // 2), str((y + bottom) // 2))
                if target in ("Downloads", "Show roots"):
                    visited.add(target)
                break
        time.sleep(.5)
    (folder / "android-picker.xml").write_text(xml, encoding="utf-8")
    (folder / "android-log.txt").write_text(command("adb", "logcat", "-d", "-s", "MuPDF", "AndroidRuntime", "ActivityTaskManager"), encoding="utf-8")
    raise AssertionError(f"Android's document picker did not open {name}: {list(labels)}")


def android(folder):
    package = "com.artifex.mupdf.mini.app"
    shots = {}
    for mode in ("original", "static", "off"):
        name = f"{mode}.pdf"
        path_on_device = f"/sdcard/Download/{name}"
        command("adb", "push", str(folder / mode / "sample.pdf"), path_on_device)
        command("adb", "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d", "file://" + path_on_device)
        choose_android_pdf(folder, package, name)
        path = folder / f"android-{mode}.png"
        for _ in range(25):
            time.sleep(1)
            path.write_bytes(subprocess.check_output(["adb", "exec-out", "screencap", "-p"]))
            with Image.open(path) as img:
                crop = text_crop(img)
            if crop is not None:
                shots[mode] = crop
                break
        assert mode in shots, f"MuPDF mini did not display the PDF text in {mode}"
    info = command("adb", "shell", "dumpsys", "package", package)
    version = next(line.partition("=")[2] for line in info.splitlines() if "versionName=" in line)
    return {"app": "MuPDF mini", "version": version, "emulatorAndroid": command("adb", "shell", "getprop",
            "ro.build.version.release"), **compare_pages(shots)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    readers = {"books": books, "iphone": iphone, "android": android}
    parser.add_argument("reader", choices=readers)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    folder = args.output.resolve()
    make_sample(folder)
    result = readers[args.reader](folder)
    (folder / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(result)
