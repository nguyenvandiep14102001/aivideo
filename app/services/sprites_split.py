from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


def _has_meaningful_alpha(im: Image.Image, min_transparent_ratio: float = 0.02) -> bool:
    """True if image already has transparent areas (user removed background)."""
    if im.mode != "RGBA":
        return False
    a = np.asarray(im)[:, :, 3]
    transparent = (a < 240).sum()
    return transparent >= a.size * min_transparent_ratio


def _key_dark_background(im: Image.Image) -> Image.Image:
    """Remove near-black background connected to image borders only."""
    rgb_u8 = np.asarray(im.convert("RGB"))
    rgb = rgb_u8.astype(np.float32)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    luma = (r + g + b) / 3.0
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    candidate_bg = (
        (luma < 42) & (chroma < 22)
        | ((luma > 238) & (chroma < 18))
        | ((chroma < 16) & (luma > 200) & (luma < 235))
    )

    h, w = candidate_bg.shape
    visited = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    # Seed from borders only so interior black outlines are preserved.
    for x in range(w):
        if candidate_bg[0, x]:
            q.append((0, x))
            visited[0, x] = True
        if candidate_bg[h - 1, x] and not visited[h - 1, x]:
            q.append((h - 1, x))
            visited[h - 1, x] = True
    for y in range(h):
        if candidate_bg[y, 0] and not visited[y, 0]:
            q.append((y, 0))
            visited[y, 0] = True
        if candidate_bg[y, w - 1] and not visited[y, w - 1]:
            q.append((y, w - 1))
            visited[y, w - 1] = True

    while q:
        y, x = q.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and candidate_bg[ny, nx] and not visited[ny, nx]:
                visited[ny, nx] = True
                q.append((ny, nx))

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = rgb_u8
    rgba[:, :, 3] = np.where(visited, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def remove_background(im: Image.Image, *, skip_rembg: bool = False) -> Image.Image:
    rgba = im.convert("RGBA")
    has_alpha = _has_meaningful_alpha(rgba)
    if has_alpha:
        out = rgba
        # Still key obvious black export backdrops
        a = np.asarray(out)[:, :, 3]
        if (a < 128).mean() < 0.15:
            out = _key_dark_background(out)
        return _clean_alpha_fringe(out)

    # If user marked "already removed background" but file has no alpha,
    # prefer rembg first (safer than forcing a dark-color key).
    if not skip_rembg:
        try:
            from rembg import remove

            cut = remove(rgba)
            arr = np.asarray(cut)
            if (arr[:, :, 3] > 10).mean() > 0.04:
                return _clean_alpha_fringe(cut)
        except (ImportError, OSError, ValueError, RuntimeError):
            pass

    # Fallback for difficult black/checker backgrounds
    return _clean_alpha_fringe(_key_dark_background(rgba))


def _clean_alpha_fringe(im: Image.Image) -> Image.Image:
    """Remove white/gray halos on cutout edges (common after manual bg removal)."""
    arr = np.asarray(im.convert("RGBA")).copy()
    rgb = arr[:, :, 0:3].astype(np.float32)
    a = arr[:, :, 3].astype(np.float32)
    luma = rgb.mean(axis=2)

    # Drop obvious white halo pixels
    halo_white = (a > 8) & (a < 250) & (rgb.min(axis=2) > 232)
    a = np.where(halo_white, a * 0.35, a)

    # Gray fringe on semi-transparent edge
    fringe = (a > 12) & (a < 220) & (luma > 175) & (luma < 245)
    a = np.where(fringe, a * 0.65, a)

    arr[:, :, 3] = np.clip(a, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def _mass_split_bounds(mask: np.ndarray, n: int) -> list[int]:
    """Split content into n parts by equal foreground mass (better than equal width)."""
    col = mask.sum(axis=0).astype(np.float64)
    if col.sum() <= 0:
        w = mask.shape[1]
        return [0] + [int(round(w * i / n)) for i in range(1, n)] + [w]
    csum = col.cumsum()
    total = csum[-1]
    bounds = [0]
    for i in range(1, n):
        target = total * (i / n)
        idx = int(np.searchsorted(csum, target))
        bounds.append(min(mask.shape[1], max(bounds[-1] + 1, idx)))
    bounds.append(mask.shape[1])
    return bounds


def _segments_from_columns(
    mask: np.ndarray, *, min_col_pixels: int = 8, min_segment_width: int = 12
) -> list[tuple[int, int]]:
    """Find continuous foreground column segments."""
    col = mask.sum(axis=0)
    on = col > min_col_pixels
    segments: list[tuple[int, int]] = []
    start = None
    for i, flag in enumerate(on):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_segment_width:
                segments.append((start, i))
            start = None
    if start is not None and len(on) - start >= min_segment_width:
        segments.append((start, len(on)))
    return segments


def _merge_segments_to_n(segments: list[tuple[int, int]], n: int) -> list[tuple[int, int]]:
    """Merge nearest segments until count equals n."""
    merged = segments[:]
    while len(merged) > n:
        best_i = 0
        best_gap = 10**9
        for i in range(len(merged) - 1):
            gap = merged[i + 1][0] - merged[i][1]
            if gap < best_gap:
                best_gap = gap
                best_i = i
        l0, _ = merged[best_i]
        _, r1 = merged[best_i + 1]
        merged[best_i : best_i + 2] = [(l0, r1)]
    return merged


def _resize_pose(crop: Image.Image, target_height: int) -> Image.Image:
    if crop.height <= 0:
        return crop
    if crop.height == target_height:
        return crop
    ratio = target_height / crop.height
    new_w = max(1, int(round(crop.width * ratio)))
    # Upscale line art: LANCZOS is still best; avoid over-sharpening halos
    resample = Image.Resampling.LANCZOS
    return crop.resize((new_w, target_height), resample)


def _save_pose_png(crop: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(path, format="PNG", compress_level=1)


def split_pose_sheet(
    im: Image.Image,
    out_dir: Path,
    names: list[str],
    height: int = 1200,
    *,
    skip_rembg: bool = False,
) -> list[str]:
    """Split a horizontal multi-pose sheet into named PNG files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = remove_background(im, skip_rembg=skip_rembg)
    _save_pose_png(sheet, out_dir / "_sheet.png")

    arr = np.asarray(sheet)
    mask = arr[:, :, 3] > 15
    ys, xs = np.where(mask)
    if len(xs) == 0:
        name = names[min(2, len(names) - 1)]
        _save_pose_png(sheet, out_dir / f"{name}.png")
        return [name]

    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    content = sheet.crop((x0, y0, x1 + 1, y1 + 1))
    content_mask = np.asarray(content)[:, :, 3] > 15

    n = len(names)
    segments = _segments_from_columns(content_mask)
    bounds = None
    if len(segments) >= n:
        segments = _merge_segments_to_n(segments, n)
    if len(segments) == n:
        # Convert segments to boundaries.
        b = [segments[0][0]]
        for i in range(n - 1):
            b.append((segments[i][1] + segments[i + 1][0]) // 2)
        b.append(segments[-1][1])
        bounds = b
    if bounds is None:
        bounds = _mass_split_bounds(content_mask, n)
    saved: list[str] = []
    for i, name in enumerate(names):
        left = bounds[i]
        right = bounds[i + 1]
        if right <= left:
            continue
        crop = content.crop((left, 0, right, content.height))
        ca = np.asarray(crop)
        m = ca[:, :, 3] > 15
        if not m.any():
            continue
        yy, xx = np.where(m)
        min_x, max_x = int(xx.min()), int(xx.max())
        min_y, max_y = int(yy.min()), int(yy.max())
        pad_x = max(2, int((max_x - min_x + 1) * 0.04))
        pad_y = max(2, int((max_y - min_y + 1) * 0.03))
        min_x = max(0, min_x - pad_x)
        min_y = max(0, min_y - pad_y)
        max_x = min(crop.width - 1, max_x + pad_x)
        max_y = min(crop.height - 1, max_y + pad_y)
        crop = crop.crop((min_x, min_y, max_x + 1, max_y + 1))
        crop = _resize_pose(crop, height)
        _save_pose_png(crop, out_dir / f"{name}.png")
        saved.append(name)
    return saved
