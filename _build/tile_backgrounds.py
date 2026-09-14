"""Pick one tile per band/subject, erase its course title + teacher name, save a JPEG
background, and build a contact sheet for review."""
import os, re, json
from PIL import Image, ImageDraw

SRC = r"C:/Users/JESSIC~1/AppData/Local/Temp/claude/C--Users-JessicaDrexel/4699dc26-1d13-4b19-b532-773d977ef5fb/scratchpad/tiles"
OUT = os.path.join(SRC, 'out')
os.makedirs(OUT, exist_ok=True)

BAND_Y0, BAND_Y1 = 320, 545      # title + teacher-name block
X0, XMAX = 40, 1000              # never look right of the text column

def title_len(fname):
    # English_1_Thalia_Trussell_Live_Tile.png -> course title is everything before the
    # teacher's name; approximate by length up to the mode marker minus two name tokens
    stem = re.sub(r'_(Live|OD)_Tile\.png$', '', fname)
    parts = stem.split('_')
    return len(' '.join(parts[:-2]))

def dark_cols(img):
    px = img.load()
    cols = []
    for x in range(X0, XMAX):
        n = 0
        for y in range(BAND_Y0, BAND_Y1, 2):
            r, g, b = px[x, y][:3]
            if 0.299*r + 0.587*g + 0.114*b < 150: n += 1
        cols.append(n)
    return cols

def text_right_edge(cols):
    # walk right from the first dark column; stop at a gap of 70+ clean columns
    edge, gap, started = X0, 0, False
    for i, n in enumerate(cols):
        x = X0 + i
        if n > 0:
            started = True; edge = x; gap = 0
        elif started:
            gap += 1
            if gap > 70: break
    return edge

from PIL import ImageFilter
def erase_text(img):
    """Find the title/name rows (dark pixels in the left column), then white out only
    text pixels (plus a 4px halo) so faint decoration behind the text survives."""
    px = img.load()
    rows = []
    for y in range(240, 820):
        n = 0
        for x in range(60, 700, 2):
            r, g, b = px[x, y][:3]
            if 0.299*r + 0.587*g + 0.114*b < 150: n += 1
        rows.append(n > 0)
    # group into runs, merge gaps under 90px, keep the tallest group
    runs, start = [], None
    for i, on in enumerate(rows + [False]):
        if on and start is None: start = i
        if not on and start is not None: runs.append([start + 240, i - 1 + 240]); start = None
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < 90: merged[-1][1] = r[1]
        else: merged.append(r)
    if not merged: return 0
    y0, y1 = max(merged, key=lambda r: r[1] - r[0])
    y0 -= 14; y1 += 14
    # right edge of the text: last dark column before a 70px clean gap
    cols = []
    for x in range(X0, XMAX):
        n = 0
        for y in range(y0, y1, 2):
            r, g, b = px[x, y][:3]
            if 0.299*r + 0.587*g + 0.114*b < 150: n += 1
        cols.append(n)
    edge = text_right_edge(cols) + 16
    box = (X0 - 10, y0, edge, y1)
    region = img.crop(box)
    lum = region.convert('L').filter(ImageFilter.MinFilter(9))   # dilate dark by 4px
    mask = lum.point(lambda v: 255 if v < 215 else 0)
    # fill masked pixels by interpolating along each row between the nearest
    # unmasked neighbours, so faint decoration behind the text carries through
    import numpy as np
    a = np.array(region).astype(float); m = np.array(mask) > 0
    for y in range(a.shape[0]):
        row = m[y]
        if not row.any(): continue
        xs = np.where(~row)[0]
        if len(xs) < 2: a[y][row] = 255; continue
        for c in range(3):
            a[y, :, c] = np.interp(np.arange(a.shape[1]), xs, a[y, xs, c])
    region = Image.fromarray(a.clip(0, 255).astype('uint8'))
    img.paste(region, box)
    return edge

def erase_pill(img):
    """Remove the LIVE / ON-DEMAND pill. Its white ring is found inside a fixed box,
    the ring's bounding rectangle (plus a halo) is masked, and OpenCV inpaints the
    hole from the wave around it."""
    import numpy as np, cv2
    x0, y0, x1, y1 = 20, 880, 580, 1045
    a = np.array(img)
    reg = a[y0:y1, x0:x1].astype(float)
    lum = 0.299*reg[:, :, 0] + 0.587*reg[:, :, 1] + 0.114*reg[:, :, 2]
    # the ring = white pixels within 6px of the pill's navy fill (keeps white ground out)
    navy = (lum < 60).astype(np.uint8)
    near = cv2.dilate(navy, np.ones((13, 13), np.uint8)) > 0
    ring = ((lum > 228) & near).astype(np.uint8)
    # keep the white pieces that could be part of a pill (ring segments, label letters);
    # drop anything pill-sized or bigger or touching the zone edge (white ground)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ring, connectivity=8)
    keep = np.zeros(ring.shape, bool)
    for i in range(1, n):
        L, T, W, Hh, A = stats[i]
        if W > 560 or Hh > 175 or A > 60000: continue
        if L == 0 or T == 0 or L + W >= ring.shape[1] or T + Hh >= ring.shape[0]: continue
        keep |= (lab == i)
    ring = keep
    ys, xs = np.where(ring)
    if len(xs) < 200:
        rx0, ry0, rx1, ry1 = 30, 900, 530, 1030
    else:
        rx0, rx1 = x0 + xs.min(), x0 + xs.max()
        ry0, ry1 = y0 + ys.min(), y0 + ys.max()
    # hole = the ring plus everything dark inside it (fill + label), with a 5px halo;
    # the bounding rectangle's corners were pulling the navy band into the fill
    inner = np.zeros(lum.shape, bool)
    iy0, iy1 = ry0 - y0 + 2, ry1 - y0 - 2
    ix0, ix1 = rx0 - x0 + 2, rx1 - x0 - 2
    inner[iy0:iy1, ix0:ix1] = True
    hole = ring | ((lum < 60) & inner) | ((lum > 228) & inner)
    hole = cv2.dilate(hole.astype(np.uint8), np.ones((11, 11), np.uint8))
    full = np.zeros(a.shape[:2], bool)
    full[y0:y1, x0:x1] = hole > 0
    # Some tiles back the pill with a flat navy rectangle (straight vertical edge to
    # its right). Take that block out too, or it is left orphaned on the wave.
    A = a.astype(float)
    L = 0.299*A[:, :, 0] + 0.587*A[:, :, 1] + 0.114*A[:, :, 2]
    for xe in range(rx1 + 10, min(a.shape[1] - 3, rx1 + 220)):
        edge = (L[y0:y1, xe] < 60) & (L[y0:y1, xe + 2] > 90)
        if edge.sum() > 60:    # a long straight vertical edge = the block's right side
            top = int(np.where(edge)[0].min()) + y0 - 4
            full[max(0, top):a.shape[0], 0:xe + 3] |= True
            break
    a = shear_fill(a, full)
    img.paste(Image.fromarray(a))
    return (rx0, ry0, rx1, ry1)

def shear_fill(a, hole):
    """Fill a hole in the wave: find where the deep-navy band starts in the columns
    just left and right of the hole, interpolate that boundary across the hole, and
    copy each column from the side columns shifted so the boundary lines up. Bands
    stay flat and their edge stays sharp."""
    import numpy as np
    a = a.copy().astype(float)
    lum = 0.299*a[:, :, 0] + 0.587*a[:, :, 1] + 0.114*a[:, :, 2]
    ys, xs = np.where(hole)
    hy0, hy1, hx0, hx1 = ys.min(), ys.max(), xs.min(), xs.max()
    H = a.shape[0]
    def navy_start(x):
        col = lum[max(0, hy0 - 120):H, x]
        run = 0
        for i, v in enumerate(col):
            run = run + 1 if v < 70 else 0
            if run >= 6: return max(0, hy0 - 120) + i - 5
        return None
    xL, xR = max(0, hx0 - 12), min(a.shape[1] - 1, hx1 + 12)
    sx, sy = [], []
    for x in list(range(max(0, hx0 - 70), hx0 - 6)) + list(range(hx1 + 7, min(a.shape[1], hx1 + 71))):
        e = navy_start(x)
        if e is not None: sx.append(x); sy.append(e)
    if len(sx) >= 6:
        poly = np.poly1d(np.polyfit(sx, sy, 2))
    else:
        poly = np.poly1d([0.0])
    eL, eR = poly(xL), poly(xR)
    for x in range(hx0, hx1 + 1):
        rows = np.where(hole[:, x])[0]
        if not len(rows): continue
        t = (x - xL) / float(xR - xL)
        b = poly(x)
        for y in rows:
            yl = int(round(y - (b - eL))); yr = int(round(y - (b - eR)))
            yl = min(H - 1, max(0, yl)); yr = min(H - 1, max(0, yr))
            a[y, x] = (1 - t) * a[yl, xL] + t * a[yr, xR]
    return a.clip(0, 255).astype('uint8')

manifest = []
sheet_tiles = []
for band in ('Middle', 'Upper'):
    root = os.path.join(SRC, band, band)
    for subject in sorted(os.listdir(root)):
        files = sorted(os.listdir(os.path.join(root, subject)))
        files = [f for f in files if f.endswith('.png')]
        # prefer the shortest title; among ties prefer OD (its pill is wider = covered anyway)
        files.sort(key=lambda f: (title_len(f), 'OD' not in f))
        pick = files[0]
        img = Image.open(os.path.join(root, subject, pick)).convert('RGB')
        edge = erase_text(img)
        erase_pill(img)
        key = re.sub(r'[^a-z0-9]+', '-', subject.lower()).strip('-')
        name = '%s-%s.jpg' % (band.lower(), key)
        img.save(os.path.join(OUT, name), 'JPEG', quality=86, optimize=True)
        manifest.append({'band': band, 'subject': subject, 'key': key, 'file': name, 'source': pick, 'erased_to_x': edge})
        sheet_tiles.append((band + ' / ' + subject, img.copy()))
        print(band, subject, '<-', pick, 'edge', edge, os.path.getsize(os.path.join(OUT, name)) // 1024, 'KB')

json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)

# contact sheet: 4 across
W, H = 480, 270
cols_n = 4
rows_n = (len(sheet_tiles) + cols_n - 1) // cols_n
sheet = Image.new('RGB', (cols_n * W, rows_n * (H + 24)), (240, 240, 240))
sd = ImageDraw.Draw(sheet)
for i, (label, im) in enumerate(sheet_tiles):
    x, y = (i % cols_n) * W, (i // cols_n) * (H + 24)
    sheet.paste(im.resize((W, H)), (x, y + 24))
    sd.text((x + 6, y + 5), label, fill=(20, 20, 20))
sheet.save(os.path.join(OUT, 'contact_sheet.png'))
print('sheet', sheet.size)
