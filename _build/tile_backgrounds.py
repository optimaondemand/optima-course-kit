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
