from pathlib import Path
import numpy as np
from PIL import Image, ImageOps

SRC = Path(r"a:\AIvideo\data\characters\builtin\panboy\_sheet_clean.png")
OUT = Path(r"a:\AIvideo\data\characters\builtin\panboy")
NAMES = ["point_up_left", "point_up_right", "confused", "point_right", "triumph"]

im = Image.open(SRC).convert("RGBA")
arr = np.asarray(im)
mask = arr[:, :, 3] > 15
ys, xs = np.where(mask)
y0, y1 = int(ys.min()), int(ys.max())
x0, x1 = int(xs.min()), int(xs.max())
# trim vertical a bit
content = im.crop((x0, y0, x1 + 1, y1 + 1))
cw, ch = content.size
step = cw / 5

for i, name in enumerate(NAMES):
    left = int(i * step)
    right = int((i + 1) * step)
    # small overlap trim
    crop = content.crop((left, 0, right, ch))
    # clear pixels that belong to neighbors by keeping only central blob:
    ca = np.asarray(crop)
    m = ca[:, :, 3] > 15
    # if almost empty skip
    if not m.any():
        continue
    # trim
    yy, xx = np.where(m)
    crop = crop.crop((int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1))
    th = 1000
    ratio = th / crop.height
    crop = crop.resize((max(1, int(crop.width * ratio)), th), Image.Resampling.LANCZOS)
    crop.save(OUT / f"{name}.png")
    print(name, crop.size)

ImageOps.mirror(Image.open(OUT / "point_right.png")).save(OUT / "point_left.png")
# preview card for picker
preview = Image.open(OUT / "point_up_right.png").copy()
preview.thumbnail((360, 480))
preview.save(OUT / "preview.png")
print("ok")
