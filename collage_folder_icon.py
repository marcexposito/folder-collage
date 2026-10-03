#!/usr/bin/env python3
"""
collage_folder_icon.py — turn a macOS folder's icon into a scrapbook collage of what's inside it,
like the photo-collage binders of the 2000s.

Usage:
    python3 collage_folder_icon.py FOLDER [FOLDER ...]
    python3 collage_folder_icon.py FOLDER --no-title          # skip the cut-out letters
    python3 collage_folder_icon.py FOLDER --seed 3            # reshuffle the collage
    python3 collage_folder_icon.py FOLDER --preview out.png   # just render, don't apply
    python3 collage_folder_icon.py FOLDER --reset             # back to the normal folder icon

What it uses, in order:
  1. Photos in the folder (and its subfolders, two levels deep)
  2. If there are fewer than 3 photos: Quick Look previews of documents/videos (macOS only)
  3. Nothing usable: leaves the icon alone and says so

Requires: Python 3.10+, Pillow >= 12.3.0; optional pillow-heif >= 1.6.0 for iPhone HEIC photos.
Security notes: see SECURITY.md.
"""
import argparse, glob, json, os, random, shutil, subprocess, sys, tempfile, warnings
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageEnhance

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HAVE_HEIF = True
except ImportError:
    HAVE_HEIF = False

# --- Security limits -------------------------------------------------------------------------
# Only these decoders may run. Pillow otherwise sniffs file *contents* and would happily parse
# obscure formats (McIdas, GD, FITS, PCF fonts…) that have had memory-safety bugs, even inside a
# file named .jpg. (Multi-picture "MPO" camera JPEGs are handled by the JPEG opener.)
Image.init()
ALLOWED_FORMATS = [f for f in ["JPEG", "PNG", "WEBP", "TIFF", "BMP", "GIF", "HEIF"]
                   if f in Image.OPEN]     # only names Pillow actually registered, or open() fails
MAX_FILE_BYTES = 200 * 1024 * 1024        # skip anything bigger than 200 MB
Image.MAX_IMAGE_PIXELS = 120_000_000      # ~120 MP (an iPhone 48 MP photo is well under this)
warnings.simplefilter("error", Image.DecompressionBombWarning)   # treat suspicious images as errors

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
DOC_EXTS = {".pdf", ".doc", ".docx", ".pages", ".key", ".ppt", ".pptx", ".numbers", ".xls", ".xlsx",
            ".txt", ".rtf", ".md", ".mov", ".mp4", ".m4v", ".psd", ".ai", ".sketch", ".epub"}
MAX_PIECES = 14
S = 1024                          # icon canvas (macOS uses up to 1024x1024)
TAB = (90, 168, 430, 262)         # folder tab
BODY = (70, 220, 954, 860)        # back panel
FRONT = (62, 292, 962, 884)       # front cover: the collage lives here
RADIUS = 44

# Paper scraps for the ransom-note letters: (background, ink)
SCRAPS = [((255, 255, 255), (20, 20, 20)), ((20, 20, 20), (255, 255, 255)), ((225, 35, 45), (255, 255, 255)),
          ((255, 222, 40), (20, 20, 20)), ((255, 120, 190), (20, 20, 20)), ((40, 170, 230), (255, 255, 255)),
          ((245, 240, 225), (200, 30, 40)), ((90, 200, 110), (20, 20, 20)), ((255, 255, 255), (220, 30, 60)),
          ((150, 90, 200), (255, 240, 120))]


# ---------------------------------------------------------------- gathering sources

# Why files were skipped, so the user gets a useful message instead of "no photos".
SKIPS = {"no_access": 0, "heic": 0, "cloud": 0, "too_big": 0, "unreadable": 0, "tiny": 0}
OTHER_EXTS = {}
SF_DATALESS = 0x40000000      # macOS flag: file is in iCloud, not downloaded to this Mac


def _walk(folder, depth):
    """Files in folder and subfolders, skipping hidden files and app/photo-library bundles."""
    out = []
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name)
    except PermissionError:
        SKIPS["no_access"] += 1
        return out
    except OSError:
        return out
    for e in entries:
        if e.name.startswith(".") or e.name == "Icon\r":
            continue
        if e.is_dir(follow_symlinks=False):
            if depth > 0 and Path(e.name).suffix.lower() not in {".app", ".photoslibrary", ".bundle", ".pkg"}:
                out += _walk(e.path, depth - 1)
        elif e.is_file(follow_symlinks=False):     # never follow links out of the folder
            out.append(Path(e.path))
        if len(out) > 3000:
            break
    return out


def _open(path, formats=None):
    """Decode one image defensively; any problem means the file is simply skipped."""
    try:
        st = os.stat(path)
        if getattr(st, "st_flags", 0) & SF_DATALESS:
            SKIPS["cloud"] += 1
            return None
        if st.st_size > MAX_FILE_BYTES:
            SKIPS["too_big"] += 1
            return None
        if Path(path).suffix.lower() in {".heic", ".heif"} and not HAVE_HEIF:
            SKIPS["heic"] += 1
            return None
        with Image.open(path, formats=formats or ALLOWED_FORMATS) as im:
            im.draft("RGB", (1400, 1400))     # fast downscale for big JPEGs
            im = ImageOps.exif_transpose(im)
            im.thumbnail((1400, 1400))
            return im.convert("RGB")
    except PermissionError:
        SKIPS["no_access"] += 1
    except Exception:
        SKIPS["unreadable"] += 1
    return None


def _quicklook(paths, size=900):
    """Thumbnails of documents/videos via macOS Quick Look. Empty list elsewhere."""
    if sys.platform != "darwin" or not paths or not shutil.which("qlmanage"):
        return []
    tmp = tempfile.mkdtemp(prefix="collage_ql_")
    try:
        subprocess.run(["qlmanage", "-t", "-s", str(size), "-o", tmp, *map(str, paths)],
                       capture_output=True, timeout=60)
    except Exception:
        pass
    ims = [_open(p, ["PNG"]) for p in sorted(Path(tmp).glob("*.png"))]
    shutil.rmtree(tmp, ignore_errors=True)
    return [i for i in ims if i]


def gather(folder, seed, depth=2, use_docs=True):
    rnd = random.Random(seed)
    files = _walk(folder, depth)
    photos = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
    docs = [p for p in files if p.suffix.lower() in DOC_EXTS]
    for p in files:
        ext = p.suffix.lower()
        if ext and ext not in IMAGE_EXTS and ext not in DOC_EXTS:
            OTHER_EXTS[ext] = OTHER_EXTS.get(ext, 0) + 1
    rnd.shuffle(photos)
    rnd.shuffle(docs)
    imgs = []
    for p in photos:
        im = _open(p)
        if im and min(im.size) < 64:
            SKIPS["tiny"] += 1
        elif im:
            imgs.append(im)
        if len(imgs) >= MAX_PIECES:
            break
    if use_docs and len(imgs) < 3 and docs:
        imgs += _quicklook(docs[:MAX_PIECES - len(imgs)])
    return imgs


# ---------------------------------------------------------------- collage pieces

def random_crop(im, aspect, rnd, zoom=(0.55, 1.0)):
    """Cut a piece out of a photo at the given aspect ratio, like scissors through a magazine."""
    w, h = im.size
    if w / h > aspect:
        cw, ch = h * aspect, h
    else:
        cw, ch = w, w / aspect
    z = rnd.uniform(*zoom)
    cw, ch = cw * z, ch * z
    x = rnd.uniform(0, w - cw)
    # bias crops slightly upward: faces tend to be in the upper part of photos
    y = rnd.uniform(0, (h - ch) * 0.75)
    return im.crop((int(x), int(y), int(x + cw), int(y + ch)))


def treat(piece, rnd, bw_chance):
    """Occasional photo-booth black & white, plus a bit of print punch."""
    if rnd.random() < bw_chance:
        piece = ImageOps.autocontrast(ImageOps.grayscale(piece), cutoff=2).convert("RGB")
    else:
        piece = ImageEnhance.Color(piece).enhance(rnd.uniform(1.0, 1.25))
        piece = ImageEnhance.Contrast(piece).enhance(rnd.uniform(1.0, 1.12))
    return piece


def scissor_mask(size, rnd, jag):
    """Slightly irregular hand-cut edge: a rectangle whose corners and edges wobble."""
    w, h = size
    pts = []
    def wob():
        return rnd.uniform(-jag, jag)
    steps = 6
    for i in range(steps):     pts.append((w * i / steps + wob(), abs(wob())))
    for i in range(steps):     pts.append((w - abs(wob()), h * i / steps + wob()))
    for i in range(steps):     pts.append((w - w * i / steps + wob(), h - abs(wob())))
    for i in range(steps):     pts.append((abs(wob()), h - h * i / steps + wob()))
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m


def glue(canvas, piece, mask, center, angle, shadow=0.45):
    """Rotate a cut-out, drop a soft shadow, and stick it onto the canvas."""
    rgba = piece.convert("RGBA")
    rgba.putalpha(mask)
    rgba = rgba.rotate(angle, expand=True, resample=Image.BICUBIC)
    x, y = int(center[0] - rgba.width / 2), int(center[1] - rgba.height / 2)
    if shadow:
        sh = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
        sh.putalpha(rgba.getchannel("A").point(lambda a: int(a * shadow)))
        sh = sh.filter(ImageFilter.GaussianBlur(7))
        _paste_clip(canvas, sh, x + 5, y + 8)
    _paste_clip(canvas, rgba, x, y)


def _paste_clip(canvas, im, x, y):
    """alpha_composite that tolerates pieces hanging off the edge."""
    l, t = max(0, -x), max(0, -y)
    r, b = min(im.width, canvas.width - x), min(im.height, canvas.height - y)
    if r > l and b > t:
        canvas.alpha_composite(im.crop((l, t, r, b)), (x + l, y + t))


def split_tiles(w, h, n, rnd):
    """Divide the cover into n rectangles of varied size (no gaps), like a glued-down base layer."""
    rects = [(0, 0, w, h)]
    while len(rects) < n:
        rects.sort(key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
        x0, y0, x1, y1 = rects.pop()
        rw, rh = x1 - x0, y1 - y0
        f = rnd.uniform(0.36, 0.64)
        if rw > rh * rnd.uniform(0.8, 1.25):
            cut = x0 + rw * f
            rects += [(x0, y0, cut, y1), (cut, y0, x1, y1)]
        else:
            cut = y0 + rh * f
            rects += [(x0, y0, x1, cut), (x0, cut, x1, y1)]
    return rects


# ---------------------------------------------------------------- ransom-note title

def _fonts():
    pats = ["/System/Library/Fonts/Supplemental/Impact.ttf", "/System/Library/Fonts/Supplemental/Arial Black.ttf",
            "/System/Library/Fonts/Supplemental/Georgia Bold.ttf", "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
            "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf", "/System/Library/Fonts/Supplemental/Chalkduster.ttf",
            "/System/Library/Fonts/Supplemental/Rockwell.ttc", "/System/Library/Fonts/Supplemental/Copperplate.ttc",
            "/System/Library/Fonts/Supplemental/American Typewriter.ttc", "/System/Library/Fonts/Supplemental/Didot.ttc",
            "/System/Library/Fonts/Supplemental/Futura.ttc", "/System/Library/Fonts/Supplemental/Bodoni 72.ttc",
            "/System/Library/Fonts/MarkerFelt.ttc", "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVu*Bold*.ttf", "/usr/share/fonts/truetype/liberation*/*Bold*.ttf"]
    found = []
    for p in pats:
        found += glob.glob(p)
    return found


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def ransom_title(canvas, text, rnd, photos):
    text = "".join(c for c in text if c.isalnum() or c == " ").strip()
    if not text:
        return
    words = text.split()
    # one or two lines, at most ~11 letters per line so letters stay readable at icon size
    lines, cur = [], ""
    for wd in words:
        if cur and len(cur) + 1 + len(wd) > 11:
            lines.append(cur); cur = wd
        else:
            cur = (cur + " " + wd).strip()
    lines.append(cur)
    lines = [l[:11] for l in lines[:2]]

    fonts = _fonts() or [None]
    W, H = canvas.size
    longest = max(len(l) for l in lines)
    cell = min(118, int((W - 50) / max(longest, 3)))
    total_h = cell * 1.12 * len(lines)
    top = H * 0.52 - total_h / 2 if len(lines) == 1 else H * 0.44 - total_h / 2
    for li, line in enumerate(lines):
        x = (W - cell * len(line)) / 2 + cell / 2
        y = top + li * cell * 1.12 + cell / 2
        for ch in line:
            if ch == " ":
                x += cell; continue
            bg, ink = rnd.choice(SCRAPS)
            fsize = int(cell * rnd.uniform(0.78, 1.0))
            font = _font(rnd.choice(fonts), fsize) if fonts[0] else _font(None, fsize)
            if rnd.random() < 0.5:
                ch = ch.upper()
            bbox = font.getbbox(ch)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad = int(cell * rnd.uniform(0.08, 0.16))
            sw, shh = max(tw + 2 * pad, int(cell * 0.62)), th + 2 * pad
            # sometimes the scrap is cut from one of the photos, like letters cut from a magazine page
            if photos and rnd.random() < 0.2:
                scrap = random_crop(rnd.choice(photos), sw / shh, rnd, (0.2, 0.4)).resize((sw, shh))
                scrap = ImageEnhance.Brightness(scrap).enhance(0.55)
                ink = (255, 255, 255)
            else:
                scrap = Image.new("RGB", (sw, shh), bg)
            ImageDraw.Draw(scrap).text(((sw - tw) / 2 - bbox[0], (shh - th) / 2 - bbox[1]), ch, font=font, fill=ink)
            glue(canvas, scrap, scissor_mask(scrap.size, rnd, 3), (x + rnd.uniform(-4, 4), y + rnd.uniform(-9, 9)),
                 rnd.uniform(-13, 13), shadow=0.55)
            x += cell * rnd.uniform(0.9, 1.0)


# ---------------------------------------------------------------- the collage

def make_collage(imgs, w, h, rnd, title):
    canvas = Image.new("RGBA", (w, h), (240, 234, 222, 255))
    n = len(imgs)
    bw = 0.22 if n >= 3 else 0.12

    # 1) base layer: the whole cover is papered edge to edge
    base_n = max(3, min(8, n + 2))
    order = list(range(n)); rnd.shuffle(order)
    for i, (x0, y0, x1, y1) in enumerate(split_tiles(w, h, base_n, rnd)):
        im = imgs[order[i % n]]
        grow = 14
        tw, th = int(x1 - x0 + 2 * grow), int(y1 - y0 + 2 * grow)
        piece = treat(random_crop(im, tw / th, rnd, (0.7, 1.0)).resize((tw, th), Image.LANCZOS), rnd, bw)
        glue(canvas, piece, scissor_mask(piece.size, rnd, 5),
             ((x0 + x1) / 2, (y0 + y1) / 2), rnd.uniform(-2.5, 2.5), shadow=0.35)

    # 2) cut-outs layered on top, varied sizes, some with white print borders
    over_n = max(3, min(7, n))
    for i in range(over_n):
        im = imgs[order[(i + base_n) % n]]
        pw = int(w * rnd.uniform(0.2, 0.36))
        ph = int(pw * rnd.uniform(0.75, 1.35))
        piece = treat(random_crop(im, pw / ph, rnd, (0.45, 0.9)).resize((pw, ph), Image.LANCZOS), rnd, bw)
        if rnd.random() < 0.45:                        # printed photo with a white border
            b = max(6, pw // 18)
            framed = Image.new("RGB", (pw + 2 * b, ph + 2 * b), (252, 252, 250))
            framed.paste(piece, (b, b)); piece = framed
            mask = Image.new("L", piece.size, 255)
        else:                                          # cut straight out of a magazine
            mask = scissor_mask(piece.size, rnd, 4)
        cx = rnd.uniform(0.08, 0.92) * w
        cy = rnd.uniform(0.1, 0.9) * h
        glue(canvas, piece, mask, (cx, cy), rnd.uniform(-11, 11))

    # 3) a strip of photo-booth frames, if there are enough photos
    if n >= 5 and rnd.random() < 0.6:
        fw = int(w * 0.13)
        frames = [treat(random_crop(imgs[order[k % n]], 1.0, rnd, (0.4, 0.7)).resize((fw, fw)), rnd, 1.0)
                  for k in range(3)]
        strip = Image.new("RGB", (fw + 16, 3 * fw + 32), (245, 245, 245))
        for k, f in enumerate(frames):
            strip.paste(f, (8, 8 + k * (fw + 8)))
        glue(canvas, strip, Image.new("L", strip.size, 255),
             (rnd.choice([0.08, 0.92]) * w, rnd.uniform(0.35, 0.65) * h), rnd.uniform(-8, 8))

    # 4) folder name in cut-out letters
    if title:
        ransom_title(canvas, title, rnd, imgs)
    return canvas


def build_icon(imgs, title, seed, tint):
    rnd = random.Random(seed)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((76, 236, 948, 904), RADIUS, fill=(0, 0, 0, 120))
    icon.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)))

    d = ImageDraw.Draw(icon)
    back = tuple(int(c * 0.72) for c in tint)
    d.rounded_rectangle(TAB, 34, fill=back)
    d.rounded_rectangle(BODY, RADIUS, fill=back)
    d.rounded_rectangle((104, 246, 920, 400), 18, fill=(250, 250, 247))      # paper peeking out

    fw, fh = FRONT[2] - FRONT[0], FRONT[3] - FRONT[1]
    art = make_collage(imgs, fw, fh, rnd, title)
    cover = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cover.alpha_composite(art, FRONT[:2])
    clip = Image.new("L", (S, S), 0)
    ImageDraw.Draw(clip).rounded_rectangle(FRONT, RADIUS, fill=255)
    cover.putalpha(Image.composite(cover.getchannel("A"), clip, clip))
    icon.alpha_composite(cover)

    # clear plastic sleeve: diagonal sheen + soft edge darkening
    sheen = Image.new("L", (S, S), 0)
    sd = ImageDraw.Draw(sheen)
    sd.polygon([(FRONT[0], FRONT[1] + 30), (FRONT[0] + 330, FRONT[1]), (FRONT[0] + 470, FRONT[1]),
                (FRONT[0], FRONT[1] + 300)], fill=60)
    sd.polygon([(FRONT[0] + 520, FRONT[1]), (FRONT[0] + 560, FRONT[1]), (FRONT[0], FRONT[1] + 350),
                (FRONT[0], FRONT[1] + 320)], fill=40)
    sheen = sheen.filter(ImageFilter.GaussianBlur(18))
    vign = Image.new("L", (S, S), 0)
    ImageDraw.Draw(vign).rounded_rectangle(FRONT, RADIUS, outline=70, width=40)
    vign = vign.filter(ImageFilter.GaussianBlur(26))
    white = Image.new("RGBA", (S, S), (255, 255, 255, 0)); white.putalpha(Image.composite(sheen, Image.new("L", (S, S), 0), clip))
    black = Image.new("RGBA", (S, S), (0, 0, 0, 0)); black.putalpha(Image.composite(vign, Image.new("L", (S, S), 0), clip))
    icon.alpha_composite(black)
    icon.alpha_composite(white)

    ImageDraw.Draw(icon).rounded_rectangle(FRONT, RADIUS, outline=tint + (255,), width=9)
    return icon


# ---------------------------------------------------------------- applying to Finder
# The JavaScript below is fixed text. File paths and messages are passed as separate argv
# entries, never pasted into the script, so a folder named e.g. `"); doShellScript("…` is
# just a strange name, not code.

_SET_ICON_JS = """
ObjC.import("AppKit");
function run(argv) {
  var img = argv[0] === "" ? null : $.NSImage.alloc.initWithContentsOfFile(argv[0]);
  if (argv[0] !== "" && (!img || img.isNil())) return "false";
  var ws = $.NSWorkspace.sharedWorkspace;
  // Finder caches custom icons: clear the old one first so the new one is picked up right away.
  // Refresh steps are best-effort only; they must never stop the icon itself from being set.
  if (argv[0] !== "") { try { ws.setIconForFileOptions(null, argv[1], 0); } catch (e) {} }
  var ok = ws.setIconForFileOptions(img, argv[1], 0);
  try { ws.noteFileSystemChanged(argv[1]); } catch (e) {}   // ask Finder to redraw now
  return ok ? "true" : "false";
}
"""

_NOTIFY_JS = """
function run(argv) {
  var app = Application.currentApplication();
  app.includeStandardAdditions = true;
  app.displayNotification(argv[0], {withTitle: "Folder Collage"});
}
"""


def _jxa(script, *args):
    try:
        return subprocess.run(["osascript", "-l", "JavaScript", "-e", script, *map(str, args)],
                              capture_output=True, text=True, timeout=30)
    except Exception:
        return None


def set_folder_icon(png, folder):
    r = _jxa(_SET_ICON_JS, png, folder)
    ok = bool(r) and r.returncode == 0 and r.stdout.strip() == "true"
    if not ok and r is not None:                 # details for anyone running it in Terminal
        print("macOS said:", (r.stderr or r.stdout).strip() or "(no details)", file=sys.stderr)
    if ok:
        try:
            os.utime(folder)                   # bump the modified time, another cue for Finder to refresh
        except OSError:
            pass
    return ok


def reset_folder_icon(folder):
    return set_folder_icon("", folder)          # nil image = back to the standard icon


def notify(msg):
    if sys.platform == "darwin":
        _jxa(_NOTIFY_JS, msg)


def explain_empty(name):
    """Best explanation for why nothing could be used."""
    k = SKIPS
    if k["no_access"]:
        return (f"macOS didn't let Folder Collage read “{name}”. Open System Settings → Privacy & Security → "
                f"Files and Folders and allow access to this location, then try again.")
    if k["heic"]:
        return (f"“{name}” has {k['heic']} iPhone HEIC photo{'s' if k['heic'] > 1 else ''}, but HEIC support "
                f"isn't installed. Re-run the installer to add it.")
    if k["cloud"]:
        return (f"The photos in “{name}” are stored in iCloud and not downloaded yet. Right-click the folder → "
                f"Download Now, then try again.")
    parts = []
    if k["unreadable"]:
        parts.append(f"{k['unreadable']} image{'s' if k['unreadable'] > 1 else ''} couldn't be opened")
    if k["too_big"]:
        parts.append(f"{k['too_big']} {'were' if k['too_big'] > 1 else 'was'} over 200 MB")
    if k["tiny"]:
        parts.append(f"{k['tiny']} {'were' if k['tiny'] > 1 else 'was'} too small")
    if OTHER_EXTS:
        top = ", ".join(sorted(OTHER_EXTS, key=OTHER_EXTS.get, reverse=True)[:3])
        parts.append(f"unsupported file types ({top})")
    if parts:
        return f"Nothing usable in “{name}”: " + "; ".join(parts) + "."
    return f"“{name}” has no photos or previewable documents, so its icon was left as is."


def main():
    ap = argparse.ArgumentParser(description="Make a folder's icon a collage of what's inside.")
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--seed", type=int, default=None, help="fixed seed for a repeatable collage (default: new each run)")
    ap.add_argument("--no-title", action="store_true", help="don't spell the folder name in cut-out letters")
    ap.add_argument("--no-subfolders", action="store_true", help="only use photos directly inside the folder")
    ap.add_argument("--no-documents", action="store_true", help="never use Quick Look previews of documents")
    ap.add_argument("--tint", default="70,150,220", help="folder color as R,G,B")
    ap.add_argument("--preview", metavar="PNG", help="write the icon to this PNG instead of applying it")
    ap.add_argument("--reset", action="store_true", help="restore the default folder icon")
    ap.add_argument("--notify", action="store_true", help="show a macOS notification with the result")
    a = ap.parse_args()
    try:
        tint = tuple(max(0, min(255, int(x))) for x in a.tint.split(","))
        assert len(tint) == 3
    except (ValueError, AssertionError):
        sys.exit("--tint must look like 70,150,220")

    def report(msg):
        print(msg)
        if a.notify:
            notify(msg)

    status = 0
    for f in a.folders:
        folder = Path(f).expanduser().resolve()
        if not folder.is_dir():
            report(f"Not a folder: {folder}"); status = 1; continue
        if a.reset:
            ok = reset_folder_icon(folder)
            report(f"Restored the normal icon for “{folder.name}”." if ok else f"Couldn't reset “{folder.name}”.")
            status |= 0 if ok else 1
            continue

        for key in SKIPS:
            SKIPS[key] = 0
        OTHER_EXTS.clear()
        seed = a.seed if a.seed is not None else random.randrange(1 << 30)
        imgs = gather(folder, seed, depth=0 if a.no_subfolders else 2, use_docs=not a.no_documents)
        if not imgs:
            report(explain_empty(folder.name))
            status = 1; continue

        icon = build_icon(imgs, None if a.no_title else folder.name, seed, tint)
        if a.preview:
            out = Path(a.preview) if len(a.folders) == 1 else Path(a.preview).with_stem(f"{Path(a.preview).stem}_{folder.name}")
            icon.save(out); print(f"Preview written to {out}"); continue
        if sys.platform != "darwin":
            sys.exit("Applying icons only works on macOS; use --preview to render a PNG.")
        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="collage_")   # private (0600) temp file
        try:
            os.close(fd)
            icon.save(tmp)
            ok = set_folder_icon(tmp, folder)
        finally:
            os.unlink(tmp)
        report(f"Collaged “{folder.name}” from {len(imgs)} item{'s' if len(imgs) != 1 else ''}." if ok
               else f"Couldn't set the icon for “{folder.name}” (is it on a read-only or cloud drive?).")
        status |= 0 if ok else 1
    # From the Finder menu (--notify), the notification already told the user what happened.
    # A non-zero exit would make Automator show a second, blank "Run Shell Script" error box.
    sys.exit(0 if a.notify else status)


if __name__ == "__main__":
    main()
