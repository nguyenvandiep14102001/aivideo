"""Split TuTi sprite sheet into left / right / center pose PNGs."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(
    r"C:\Users\DIEPNV\.cursor\projects\a-AIvideo\assets"
    r"\c__Users_DIEPNV_AppData_Roaming_Cursor_User_workspaceStorage_"
    r"89d541a21c5a1403947fc29f7a303b45_images_tuti-962b2bda-996f-4716-8dce-dce9c771fd7a.png"
)
OUT = Path(r"a:\AIvideo\data\characters\builtin\tuti")
OUT.mkdir(parents=True, exist_ok=True)

# Sheet order: point_left, point_right, center, point_left_smile, point_right_b
NAMES = [
    "point_left",
    "point_right",
    "center",
    "point_left_smile",
    "point_right_b",
]


def black_to_alpha(im: Image.Image, thr: int = 28) -> Image.Image:
    arr = np.asarray(im.convert("RGBA")).copy()
    rgb = arr[:, :, :3].astype(np.int16)
    luma = rgb.mean(axis=2)
    # pure/near black background → transparent
    bg = luma <= thr
    arr[bg, 3] = 0
    # keep dark glasses/beret: already non-bg if slightly above thr and near white body
    return Image.fromarray(arr, "RGBA")


def main() -> None:
    raw = Image.open(SRC).convert("RGBA")
    sheet = black_to_alpha(raw)
    sheet.save(OUT / "_sheet.png")

    arr = np.asarray(sheet)
    mask = arr[:, :, 3] > 20
    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    content = sheet.crop((x0, y0, x1 + 1, y1 + 1))
    cw, ch = content.size
    step = cw / 5.0

    for i, name in enumerate(NAMES):
        left = int(round(i * step))
        right = int(round((i + 1) * step))
        crop = content.crop((left, 0, right, ch))
        ca = np.asarray(crop)
        m = ca[:, :, 3] > 20
        if not m.any():
            continue
        yy, xx = np.where(m)
        crop = crop.crop((int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1))
        th = 1100
        ratio = th / crop.height
        crop = crop.resize((max(1, int(crop.width * ratio)), th), Image.Resampling.LANCZOS)
        crop.save(OUT / f"{name}.png")
        print(name, crop.size)

    # Canonical aliases used by pose resolver
    Image.open(OUT / "point_left_smile.png").save(OUT / "point_1.png")  # smile left = panel 1
    Image.open(OUT / "point_right.png").save(OUT / "point_2.png")
    Image.open(OUT / "center.png").save(OUT / "point_center.png")

    preview = Image.open(OUT / "center.png").copy()
    preview.thumbnail((360, 480))
    preview.save(OUT / "preview.png")
    print("done", OUT)


if __name__ == "__main__":
    main()
