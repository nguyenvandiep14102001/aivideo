"""Split panboy sprite sheet into transparent pose PNGs."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

SRC = Path(
    r"C:\Users\DIEPNV\.cursor\projects\a-AIvideo\assets"
    r"\c__Users_DIEPNV_AppData_Roaming_Cursor_User_workspaceStorage_"
    r"89d541a21c5a1403947fc29f7a303b45_images_image-267be8d7-eb39-4df2-9818-04f5b942ce49.png"
)
OUT = Path(r"a:\AIvideo\data\characters\builtin\panboy")
OUT.mkdir(parents=True, exist_ok=True)

POSE_NAMES = [
    "point_up_left",   # points up-left / toward left content
    "point_up_right",  # points up-right / toward right content
    "confused",        # shrug + ?
    "point_right",     # horizontal point right
    "triumph",         # pan raised
]


def character_mask(arr: np.ndarray) -> np.ndarray:
    """Keep white body, black lines, gray pan, pink blush — drop beige checker."""
    r = arr[:, :, 0].astype(np.float32)
    g = arr[:, :, 1].astype(np.float32)
    b = arr[:, :, 2].astype(np.float32)
    luma = (r + g + b) / 3.0
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)

    white = (luma > 238) & (chroma < 35)
    black = luma < 55
    gray_pan = (chroma < 25) & (luma >= 55) & (luma < 130)
    pink = (r > 200) & (g < 175) & (b < 175) & ((r - g) > 25)
    # soft near-white body shading
    soft_white = (luma > 220) & (chroma < 40) & (r > 210) & (g > 200) & (b > 190)

    mask = white | black | gray_pan | pink | soft_white

    # Drop classic checker beige (warm mid tones with low chroma)
    beige = (luma > 170) & (luma < 235) & (r > g) & (g > b) & (chroma < 55) & ~white & ~soft_white
    mask = mask & ~beige

    img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    # Close small holes inside body, open speckles
    img = img.filter(ImageFilter.MaxFilter(5))
    img = img.filter(ImageFilter.MinFilter(5))
    img = img.filter(ImageFilter.MinFilter(3))
    img = img.filter(ImageFilter.MaxFilter(3))
    return np.asarray(img) > 128


def flood_kill_bg(mask: np.ndarray, arr: np.ndarray) -> np.ndarray:
    """Anything reachable from image edges that looks like bg → transparent."""
    h, w = mask.shape
    r = arr[:, :, 0].astype(np.float32)
    g = arr[:, :, 1].astype(np.float32)
    b = arr[:, :, 2].astype(np.float32)
    luma = (r + g + b) / 3.0
    # seed edges that are NOT strong character blacks/whites already marked
    visited = np.zeros((h, w), dtype=bool)
    stack: list[tuple[int, int]] = []
    for x in range(w):
        stack.append((0, x))
        stack.append((h - 1, x))
    for y in range(h):
        stack.append((y, 0))
        stack.append((y, w - 1))

    while stack:
        y, x = stack.pop()
        if y < 0 or y >= h or x < 0 or x >= w or visited[y, x]:
            continue
        # stop at solid character ink
        if mask[y, x] and (luma[y, x] < 60 or luma[y, x] > 240):
            # allow walking through soft mask noise but not core character
            if luma[y, x] < 60 or luma[y, x] > 245:
                visited[y, x] = True
                continue
        visited[y, x] = True
        # treat as background if beige-ish or soft
        if luma[y, x] < 40:
            continue
        mask[y, x] = False
        stack.extend(((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)))
    return mask


def main() -> None:
    im = Image.open(SRC).convert("RGB")
    arr = np.asarray(im)
    h, w, _ = arr.shape
    mask = character_mask(arr)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = arr
    rgba[..., 3] = (mask * 255).astype(np.uint8)
    full = Image.fromarray(rgba, "RGBA")

    # Clean fringe: make near-transparent edge pixels fully transparent
    alpha = rgba[..., 3]
    # If alpha low-ish from morph, keep; erode alpha slightly for cleaner composite
    a_img = Image.fromarray(alpha, "L").filter(ImageFilter.MinFilter(3))
    rgba[..., 3] = np.asarray(a_img)
    # restore strong blacks lost by erode near outlines — dilate black onto alpha
    black = (arr.mean(axis=2) < 50).astype(np.uint8) * 255
    black_d = Image.fromarray(black, "L").filter(ImageFilter.MaxFilter(3))
    rgba[..., 3] = np.maximum(rgba[..., 3], np.asarray(black_d) & (arr.mean(axis=2) < 80).astype(np.uint8) * 255)

    full = Image.fromarray(rgba, "RGBA")
    full.save(OUT / "_sheet.png")

    # Find 5 pose columns via vertical projection of alpha
    alpha = rgba[..., 3] > 40
    col = alpha.mean(axis=0)
    # smooth
    kernel = np.ones(9) / 9
    col_s = np.convolve(col, kernel, mode="same")
    threshold = max(0.02, col_s.max() * 0.08)
    active = col_s > threshold

    runs: list[tuple[int, int]] = []
    start = None
    for i, a in enumerate(active):
        if a and start is None:
            start = i
        if not a and start is not None:
            if i - 1 - start > 20:
                runs.append((start, i - 1))
            start = None
    if start is not None and w - 1 - start > 20:
        runs.append((start, w - 1))

    print("runs", runs)

    ys, xs = np.where(alpha)
    y0, y1 = int(ys.min()), int(ys.max())

    if len(runs) != 5:
        # merge tiny gaps: cluster into 5 by equal width of content
        x0, x1 = int(xs.min()), int(xs.max())
        step = (x1 - x0 + 1) / 5
        boxes = [(int(x0 + i * step), int(x0 + (i + 1) * step) - 1) for i in range(5)]
    else:
        boxes = runs

    for name, (xa, xb) in zip(POSE_NAMES, boxes):
        pad = 4
        left = max(0, xa - pad)
        right = min(w - 1, xb + pad)
        crop = full.crop((left, y0, right + 1, y1 + 1))
        bbox = crop.getbbox()
        if bbox:
            crop = crop.crop(bbox)
        # Ensure pointing poses that should face content can be mirrored later
        target_h = 1000
        ratio = target_h / crop.height
        crop = crop.resize(
            (max(1, int(crop.width * ratio)), target_h), Image.Resampling.LANCZOS
        )
        crop.save(OUT / f"{name}.png")
        print("saved", name, crop.size, "alpha%", int(np.asarray(crop)[:, :, 3].mean() / 2.55))

    # Also create mirrored helpers for left-side pointing when character stands on right
    for src_name, dst_name in (
        ("point_right", "point_left"),
        ("point_up_right", "point_up_left_mirror"),
        ("point_up_left", "point_up_right_mirror"),
    ):
        p = OUT / f"{src_name}.png"
        if p.exists():
            ImageOps.mirror(Image.open(p)).save(OUT / f"{dst_name}.png")
            print("mirrored", dst_name)

    print("done")


if __name__ == "__main__":
    main()
