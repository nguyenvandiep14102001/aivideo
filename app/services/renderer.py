from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from app.config import VIDEO_FPS, VIDEO_HEIGHT, VIDEO_WIDTH
from app.services.characters import character_file, character_pose_dir
from app.services.poses import (
    POSE_CENTER,
    POSE_POINT_1,
    POSE_POINT_2,
    bounce_offset,
    pose_at_time,
    resolve_pose_file,
    sway_offset,
)
from app.services.script_parser import Scene, parse_script
from app.services.sfx import sfx_path
from app.services.tts import normalize_speed, synthesize_with_subtitles


def _ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run_ffmpeg(cmd: list[str], label: str, *, expect_file: Path | None = None) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return
    err = (result.stderr or result.stdout or "")[-1500:]
    # Ctrl+C / signal 2 can hit the child after encode already finished.
    if expect_file is not None:
        try:
            ok_size = expect_file.exists() and expect_file.stat().st_size > 1024
        except OSError:
            ok_size = False
        if ok_size and (
            "signal 2" in err
            or "Exiting normally" in err
            or "muxing overhead" in err
            or "Lsize=" in err
        ):
            return
    raise RuntimeError(f"FFmpeg failed ({label}):\n{err}")


def _audio_duration(path: Path) -> float:
    from app.services.tts import _audio_duration_ffprobe

    return _audio_duration_ffprobe(path)


def _fit_cover(img: Image.Image, width: int, height: int) -> Image.Image:
    return _fit_framed(img, width, height, mode="cover", zoom=1.0, focus_x=0.5, focus_y=0.5)


def _fit_framed(
    img: Image.Image,
    width: int,
    height: int,
    *,
    mode: str = "cover",
    zoom: float = 1.0,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    bg=(235, 235, 238),
) -> Image.Image:
    """Fit image into panel with optional zoom + focus (0..1)."""
    src_w, src_h = img.size
    zoom = max(1.0, min(3.0, float(zoom or 1.0)))
    fx = max(0.0, min(1.0, float(focus_x if focus_x is not None else 0.5)))
    fy = max(0.0, min(1.0, float(focus_y if focus_y is not None else 0.5)))
    mode = (mode or "cover").lower()

    if mode == "contain":
        scale = min(width / src_w, height / src_h) * zoom
        new_w = max(1, int(src_w * scale))
        new_h = max(1, int(src_h * scale))
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), bg)
        # focus shifts where the contained image sits if larger than box
        if new_w <= width:
            x = (width - new_w) // 2
        else:
            x = int(-(new_w - width) * fx)
        if new_h <= height:
            y = (height - new_h) // 2
        else:
            y = int(-(new_h - height) * fy)
        canvas.paste(resized, (x, y))
        return canvas

    # cover: fill box, crop by focus
    scale = max(width / src_w, height / src_h) * zoom
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    max_left = max(0, new_w - width)
    max_top = max(0, new_h - height)
    left = int(max_left * fx)
    top = int(max_top * fy)
    return resized.crop((left, top, left + width, top + height))


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    key = (size, bold)
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\tahomabd.ttf" if bold else r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\arialuni.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            font = ImageFont.truetype(path, size=size)
            _FONT_CACHE[key] = font
            return font
    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _fit_contain(img: Image.Image, width: int, height: int, bg=(235, 235, 238)) -> Image.Image:
    """Fit image inside box preserving aspect, letterbox with bg."""
    canvas = Image.new("RGB", (width, height), bg)
    src_w, src_h = img.size
    scale = min(width / src_w, height / src_h)
    new_w, new_h = max(1, int(src_w * scale)), max(1, int(src_h * scale))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = (width - new_w) // 2
    y = (height - new_h) // 2
    canvas.paste(resized, (x, y))
    return canvas


_FONT_CACHE: dict[tuple[int, bool], ImageFont.ImageFont] = {}
_STUDIO_BG: Image.Image | None = None
_FOCUS_BG: dict[str, Image.Image] = {}
_CHAR_CACHE: dict[str, Image.Image] = {}
_PANEL_FIT_CACHE: dict[tuple, Image.Image] = {}


def _clear_render_caches() -> None:
    global _STUDIO_BG
    _STUDIO_BG = None
    _FOCUS_BG.clear()
    _CHAR_CACHE.clear()
    _PANEL_FIT_CACHE.clear()


def _draw_light_bulb(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    size: float,
    *,
    lit: bool = False,
    wire_top: int = 0,
) -> None:
    """Minimal hanging light-bulb motif (ideas / creative studio)."""
    s = max(10, int(size))
    # Cord
    draw.line((cx, wire_top, cx, cy - int(s * 0.55)), fill=(55, 52, 48, 160), width=max(1, s // 14))
    # Cap
    cap_h = max(4, s // 5)
    draw.rounded_rectangle(
        (cx - s // 5, cy - int(s * 0.55), cx + s // 5, cy - int(s * 0.55) + cap_h),
        radius=2,
        fill=(70, 66, 60, 200) if not lit else (90, 78, 50, 230),
    )
    # Glass
    glass = (
        (255, 214, 70, 235)
        if lit
        else (72, 70, 68, 175)
    )
    outline = (255, 240, 160, 255) if lit else (245, 245, 242, 200)
    bx0, by0 = cx - int(s * 0.38), cy - int(s * 0.28)
    bx1, by1 = cx + int(s * 0.38), cy + int(s * 0.55)
    draw.ellipse((bx0, by0, bx1, by1), fill=glass, outline=outline, width=max(1, s // 16))
    # Filament
    fy = cy + int(s * 0.05)
    fcol = (255, 250, 210, 255) if lit else (210, 210, 205, 180)
    draw.arc((cx - s // 6, fy - s // 8, cx + s // 6, fy + s // 8), 200, 340, fill=fcol, width=max(1, s // 18))
    if lit:
        # Soft rays
        ray = (255, 200, 80, 90)
        for dx, dy in ((-s, 0), (s, 0), (-s * 0.7, s * 0.55), (s * 0.7, s * 0.55), (-s * 0.55, -s * 0.4), (s * 0.55, -s * 0.4)):
            draw.line((cx + dx * 0.45, cy + dy * 0.35, cx + dx, cy + dy), fill=ray, width=max(1, s // 20))


def _draw_creative_doodles(layer: Image.Image) -> None:
    """Chalk-soft doodles: stars, clouds, notes, gentle shapes — not a dense math board."""
    import math

    d = ImageDraw.Draw(layer)
    w, h = layer.size
    ink = (90, 110, 130, 55)
    ink2 = (200, 120, 90, 48)
    ink3 = (60, 150, 140, 50)

    def star(x, y, r, col):
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rad = r if i % 2 == 0 else r * 0.42
            pts.append((x + rad * math.cos(ang), y + rad * math.sin(ang)))
        d.polygon(pts, fill=col)

    def cloud(x, y, s, col):
        d.ellipse((x, y, x + s, y + s * 0.7), fill=col)
        d.ellipse((x + s * 0.35, y - s * 0.25, x + s * 1.1, y + s * 0.55), fill=col)
        d.ellipse((x + s * 0.7, y, x + s * 1.35, y + s * 0.65), fill=col)

    def note(x, y, col):
        d.ellipse((x, y + 14, x + 12, y + 24), fill=col)
        d.line((x + 11, y + 18, x + 11, y), fill=col, width=2)
        d.line((x + 11, y, x + 22, y + 4), fill=col, width=2)

    # Sparse layout — keep center clear for panels / character
    for x, y, r in ((70, 160, 14), (w - 90, 220, 11), (120, h - 280, 10), (w - 140, h - 340, 13)):
        star(x, y, r, ink)
    for x, y, s in ((40, 420, 48), (w - 160, 480, 42), (80, h - 520, 36)):
        cloud(x, y, s, (ink[0], ink[1], ink[2], 38))
    for x, y in ((w - 100, 620), (60, 700), (w - 160, h - 420)):
        note(x, y, ink2)

    # Soft arcs / swirls
    for box, col in (
        ((w * 0.72, h * 0.72, w * 0.95, h * 0.88), ink3),
        ((30, h * 0.55, 180, h * 0.7), ink),
        ((w * 0.08, h * 0.18, w * 0.28, h * 0.32), ink2),
    ):
        d.arc(box, 20, 200, fill=col, width=2)

    # Tiny hearts / diamonds
    for x, y, col in ((w - 70, 780, ink2), (95, 860, ink3), (w - 200, 900, ink)):
        d.polygon([(x, y + 8), (x + 7, y), (x + 14, y + 8), (x + 7, y + 16)], fill=col)

    # Faint geometric accents (triangle / circle) — creative, not exam-board dense
    d.polygon([(55, h - 200), (95, h - 280), (135, h - 200)], outline=ink3)
    d.ellipse((w - 160, h - 240, w - 90, h - 170), outline=ink, width=2)
    d.line((w - 200, 160, w - 40, 200), fill=ink, width=1)
    d.line((40, h - 160, 200, h - 120), fill=ink2, width=1)


def _build_studio_bg() -> Image.Image:
    """Creative 'idea studio' backdrop — warm paper, hanging bulbs, soft doodles."""
    import numpy as np

    h, w = VIDEO_HEIGHT, VIDEO_WIDTH
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    xx = np.linspace(0, 1, w, dtype=np.float32)[None, :]

    # Warm parchment wash (bright, airy — not chalkboard)
    r = 248 - 10 * yy + 8 * xx
    g = 244 - 14 * yy + 6 * (1 - xx)
    b = 232 - 18 * yy + 14 * xx

    # Soft amber glow near top-center (hero bulb zone)
    dist = np.sqrt((xx - 0.5) ** 2 + ((yy - 0.12) * 1.6) ** 2)
    glow = np.clip(1.0 - dist * 1.7, 0, 1) ** 1.6
    r = r + 28 * glow
    g = g + 18 * glow
    b = b + 4 * glow

    # Soft color orbs along edges
    for ox, oy, rad, cr, cg, cb, strength in (
        (0.12, 0.08, 0.22, 255, 200, 120, 0.22),
        (0.88, 0.10, 0.2, 140, 210, 200, 0.18),
        (0.5, 0.55, 0.42, 255, 230, 190, 0.1),
        (0.1, 0.85, 0.2, 160, 200, 230, 0.12),
        (0.9, 0.8, 0.18, 255, 170, 140, 0.14),
    ):
        d = np.sqrt((xx - ox) ** 2 + ((yy - oy) * (h / w)) ** 2)
        blob = np.clip(1.0 - d / rad, 0, 1) ** 2 * strength
        r = r * (1 - blob) + cr * blob
        g = g * (1 - blob) + cg * blob
        b = b * (1 - blob) + cb * blob

    rng = np.random.default_rng(7)
    grain = rng.normal(0, 2.0, (h, w)).astype(np.float32)
    arr = np.stack([r, g, b], axis=-1) + grain[:, :, None]
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, mode="RGB").convert("RGBA")

    doodles = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    _draw_creative_doodles(doodles)
    img = Image.alpha_composite(img, doodles)

    bulbs = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bulbs)
    # Unlit side bulbs + one large lit hero bulb
    for cx, cy, size, lit in (
        (int(w * 0.12), 110, 38, False),
        (int(w * 0.28), 78, 32, False),
        (int(w * 0.72), 82, 34, False),
        (int(w * 0.88), 118, 40, False),
        (int(w * 0.5), 150, 78, True),
    ):
        _draw_light_bulb(bd, cx, cy, size, lit=lit, wire_top=0)
    img = Image.alpha_composite(img, bulbs)

    # Soft edge vignette
    vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    for i, alpha in enumerate((18, 10, 5)):
        inset = 12 + i * 48
        vd.rounded_rectangle(
            (inset, inset, w - inset, h - inset),
            radius=90,
            outline=(60, 50, 40, alpha),
            width=48,
        )
    return Image.alpha_composite(img, vignette).convert("RGB")


def _paper_bg(t: float = 0.0, focus: str = POSE_CENTER) -> Image.Image:
    """Idea-studio background with pulsing bulb glow + soft spotlight."""
    global _STUDIO_BG
    phase = int((max(0.0, t) * 2.2) % 6)
    cache_key = (focus, phase)
    cached = _FOCUS_BG.get(cache_key)
    if cached is not None:
        return cached.copy()

    if _STUDIO_BG is None:
        _STUDIO_BG = _build_studio_bg()
    canvas = _STUDIO_BG.copy().convert("RGBA")
    light = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    ld = ImageDraw.Draw(light)

    import math

    pulse = 0.78 + 0.18 * math.sin(phase * 1.05)
    # Hero bulb pulse
    bx, by = VIDEO_WIDTH // 2, 150
    for i, (rad, alpha) in enumerate(
        ((110, int(50 * pulse)), (170, int(28 * pulse)), (240, int(12 * pulse)))
    ):
        ld.ellipse(
            (bx - rad, by - rad + 20, bx + rad, by + rad + 40),
            fill=(255, 210, 90, alpha),
        )

    shimmer = int(10 + 12 * pulse)
    drift_x = int(18 * math.sin(phase * 0.9))
    drift_y = int(10 * math.cos(phase * 0.7))
    ld.ellipse(
        (
            VIDEO_WIDTH * 0.2 + drift_x,
            40 + drift_y,
            VIDEO_WIDTH * 0.8 + drift_x,
            VIDEO_HEIGHT * 0.4 + drift_y,
        ),
        fill=(255, 248, 220, shimmer),
    )

    if focus == POSE_POINT_1:
        cx0, cx1 = 40, VIDEO_WIDTH // 2 - 10
    elif focus == POSE_POINT_2:
        cx0, cx1 = VIDEO_WIDTH // 2 + 10, VIDEO_WIDTH - 40
    else:
        cx0, cx1 = VIDEO_WIDTH * 0.22, VIDEO_WIDTH * 0.78

    for i, alpha in enumerate((int(64 * pulse), int(36 * pulse), int(18 * pulse))):
        pad = 28 + i * 34
        ld.ellipse(
            (cx0 - pad, 36 - i * 8, cx1 + pad, VIDEO_HEIGHT * 0.46 + pad),
            fill=(255, 220, 150, alpha) if focus != POSE_CENTER else (255, 245, 220, alpha // 2),
        )

    canvas = Image.alpha_composite(canvas, light).convert("RGB")
    _FOCUS_BG[cache_key] = canvas
    return canvas.copy()


def _normalize_frame(frame: dict | None) -> dict:
    frame = frame or {}
    return {
        "mode": "contain" if str(frame.get("mode", "cover")).lower() == "contain" else "cover",
        "zoom": max(1.0, min(3.0, float(frame.get("zoom", 1.0) or 1.0))),
        "x": max(0.0, min(1.0, float(frame.get("x", 0.5) if frame.get("x") is not None else 0.5))),
        "y": max(0.0, min(1.0, float(frame.get("y", 0.5) if frame.get("y") is not None else 0.5))),
    }


def _tone_panel_image(fitted: Image.Image, *, active: bool, dimmed: bool) -> Image.Image:
    """Brighten the spoken panel; gently dim the other."""
    img = fitted
    if active:
        img = ImageEnhance.Brightness(img).enhance(1.22)
        img = ImageEnhance.Contrast(img).enhance(1.12)
        img = ImageEnhance.Color(img).enhance(1.08)
    elif dimmed:
        img = ImageEnhance.Brightness(img).enhance(0.68)
        img = ImageEnhance.Color(img).enhance(0.78)
        img = ImageEnhance.Contrast(img).enhance(0.92)
    else:
        img = ImageEnhance.Brightness(img).enhance(1.04)
    return img


def _draw_panel(
    canvas: Image.Image,
    img_path: Path | None,
    box: tuple[int, int, int, int],
    label: str,
    active: bool,
    caption: str = "",
    frame: dict | None = None,
    dimmed: bool = False,
    t: float = 0.0,
) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    draw = ImageDraw.Draw(canvas)

    # Soft outer glow for active panel (static — no per-frame pulse)
    if active:
        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        pulse = 0.9
        for i, alpha in enumerate((int(90 * pulse), int(55 * pulse), int(28 * pulse))):
            pad = 18 + i * 14
            gd.rounded_rectangle(
                (x0 - pad, y0 - pad, x1 + pad, y1 + pad + 12),
                radius=24 + i * 4,
                fill=(255, 170, 110, alpha),
            )
        canvas_rgba = Image.alpha_composite(canvas.convert("RGBA"), glow)
        canvas.paste(canvas_rgba.convert("RGB"))
        draw = ImageDraw.Draw(canvas)

    if active:
        frame_color = (36, 28, 24)
        rim = (255, 140, 70)
    elif dimmed:
        frame_color = (120, 118, 122)
        rim = (170, 168, 174)
    else:
        frame_color = (78, 74, 80)
        rim = (140, 136, 142)

    draw.rounded_rectangle((x0 - 8, y0 - 8, x1 + 8, y1 + 18), radius=18, fill=frame_color)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=10, fill=(20, 20, 24))

    if img_path and img_path.exists():
        fr = _normalize_frame(frame)
        cache_key = (
            str(img_path),
            w,
            h,
            fr["mode"],
            round(fr["zoom"], 3),
            round(fr["x"], 3),
            round(fr["y"], 3),
            active,
            dimmed,
        )
        fitted = _PANEL_FIT_CACHE.get(cache_key)
        if fitted is None:
            img = Image.open(img_path).convert("RGB")
            fitted = _fit_framed(
                img,
                w,
                h,
                mode=fr["mode"],
                zoom=fr["zoom"],
                focus_x=fr["x"],
                focus_y=fr["y"],
            )
            fitted = _tone_panel_image(fitted, active=active, dimmed=dimmed)
            _PANEL_FIT_CACHE[cache_key] = fitted
        canvas.paste(fitted, (x0, y0))
    else:
        draw.rectangle((x0, y0, x1, y1), fill=(55, 55, 62))
        font = _load_font(36, bold=True)
        tw = draw.textlength(f"Ảnh {label}", font=font)
        draw.text(((x0 + x1 - tw) / 2, (y0 + y1) / 2 - 18), f"Ảnh {label}", font=font, fill=(200, 200, 205))

    # Active: bright edge; dimmed: muted edge
    edge_w = 6 if active else 3
    draw.rounded_rectangle(
        (x0 - 10, y0 - 10, x1 + 10, y1 + 20),
        radius=20,
        outline=rim,
        width=edge_w,
    )
    if active:
        # Inner light rim
        draw.rounded_rectangle(
            (x0 - 2, y0 - 2, x1 + 2, y1 + 2),
            radius=12,
            outline=(255, 236, 210),
            width=3,
        )

    badge_bg = (255, 96, 64) if active else ((70, 70, 76) if not dimmed else (95, 95, 100))
    bx0, by0 = x0 + 14, y0 + 14
    draw.rounded_rectangle((bx0, by0, bx0 + 46, by0 + 46), radius=10, fill=badge_bg)
    if active:
        draw.rounded_rectangle(
            (bx0 - 3, by0 - 3, bx0 + 49, by0 + 49),
            radius=12,
            outline=(255, 220, 180),
            width=2,
        )
    bf = _load_font(28, bold=True)
    draw.text((bx0 + 14, by0 + 6), label, font=bf, fill=(255, 255, 255))

    note = (caption or "").strip()
    if note:
        cf = _load_font(28, bold=True)
        words = note.split()
        lines: list[str] = []
        cur = ""
        max_w = w - 28
        for word in words:
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=cf) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        lines = lines[:3]
        pad = 10
        line_h = 34
        box_h = pad * 2 + line_h * len(lines)
        by1 = y1 - 8
        by0c = by1 - box_h
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        note_alpha = 200 if active else (150 if not dimmed else 120)
        od.rounded_rectangle((x0 + 8, by0c, x1 - 8, by1), radius=12, fill=(0, 0, 0, note_alpha))
        composited = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        canvas.paste(composited)
        draw = ImageDraw.Draw(canvas)
        ty = by0c + pad
        note_color = (255, 255, 255) if not dimmed else (210, 210, 214)
        for line in lines:
            tw = draw.textlength(line, font=cf)
            draw.text(((x0 + x1 - tw) / 2, ty), line, font=cf, fill=note_color)
            ty += line_h


def _paste_character_center(
    canvas: Image.Image,
    char_path: Path | None,
    bob: int = 0,
    sway: int = 0,
    target: str = POSE_CENTER,
    mouth: float = 0.0,
) -> Image.Image:
    if not char_path or not char_path.exists():
        return canvas
    key = str(char_path.resolve()) if char_path.exists() else str(char_path)
    char = _CHAR_CACHE.get(key)
    if char is None:
        char = Image.open(char_path).convert("RGBA")
        target_h = int(VIDEO_HEIGHT * 0.44)
        ratio = target_h / char.height
        char = char.resize((max(1, int(char.width * ratio)), target_h), Image.Resampling.LANCZOS)
        _CHAR_CACHE[key] = char
    # Mouth lip-sync disabled — paste sprite as-is (no overlay)
    _ = mouth
    base = canvas.convert("RGBA")
    x = (VIDEO_WIDTH - char.width) // 2 + sway
    y = VIDEO_HEIGHT - char.height + 16 - bob
    if target == POSE_POINT_1:
        x -= 36
    elif target == POSE_POINT_2:
        x += 36
    base.alpha_composite(char, (x, y))
    return base.convert("RGB")


def _build_karaoke_chunks(cues: list[dict], max_words: int = 7) -> list[list[dict]]:
    """Split cues into display segments (show whole segment, then advance)."""
    if not cues:
        return []
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for c in cues:
        cur.append(c)
        text = str(c.get("text") or "")
        hard_break = text.endswith((".", "!", "?", "…"))
        soft_break = text.endswith((",", ";", ":")) and len(cur) >= 4
        if len(cur) >= max_words or hard_break or soft_break:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def _karaoke_chunk(cues: list[dict], t: float, max_words: int = 7) -> tuple[list[dict], int]:
    """
    Show one full text segment at a time.
    Words already spoken (and current) are red; upcoming stay muted.
    """
    chunks = _build_karaoke_chunks(cues, max_words=max_words)
    if not chunks:
        return [], -1

    active_global = -1
    for i, c in enumerate(cues):
        if t >= float(c["offset"]):
            active_global = i
        else:
            break

    if active_global < 0:
        return chunks[0], -1

    # Map global index → chunk
    cursor = 0
    for chunk in chunks:
        end = cursor + len(chunk)
        if active_global < end:
            return chunk, active_global - cursor
        cursor = end
    last = chunks[-1]
    return last, len(last) - 1


def _draw_karaoke_light(
    draw: ImageDraw.ImageDraw,
    cues_window: list[dict],
    active_local: int,
    y_base: int,
) -> None:
    """Segment karaoke: full chunk visible first; spoken words turn red. No underline."""
    if not cues_window:
        return
    font = _load_font(52, bold=True)
    gap = 16
    max_w = VIDEO_WIDTH - 140

    lines: list[list[tuple[dict, int]]] = [[]]
    line_w = 0
    for i, c in enumerate(cues_window):
        w = draw.textlength(c["text"], font=font)
        extra = 0 if not lines[-1] else gap
        if line_w + extra + w > max_w and lines[-1]:
            lines.append([])
            line_w = 0
            extra = 0
        lines[-1].append((c, i))
        line_w += extra + w

    line_h = 70
    total_h = line_h * len(lines) + 28
    max_line_w = 0
    for line in lines:
        lw = sum(draw.textlength(c["text"], font=font) for c, _ in line) + gap * max(0, len(line) - 1)
        max_line_w = max(max_line_w, lw)

    pill_w = min(VIDEO_WIDTH - 72, max_line_w + 72)
    pill_x0 = (VIDEO_WIDTH - pill_w) / 2
    pill_y0 = y_base - 10
    pill_y1 = pill_y0 + total_h
    draw.rounded_rectangle(
        (pill_x0 + 3, pill_y0 + 5, pill_x0 + pill_w + 3, pill_y1 + 5),
        radius=28,
        fill=(215, 215, 222),
    )
    draw.rounded_rectangle(
        (pill_x0, pill_y0, pill_x0 + pill_w, pill_y1),
        radius=28,
        fill=(255, 255, 255),
    )
    draw.rounded_rectangle(
        (pill_x0, pill_y0, pill_x0 + pill_w, pill_y1),
        radius=28,
        outline=(236, 236, 240),
        width=2,
    )

    y = pill_y0 + 20
    for line in lines:
        lw = sum(draw.textlength(c["text"], font=font) for c, _ in line) + gap * max(0, len(line) - 1)
        x = (VIDEO_WIDTH - lw) / 2
        for c, i in line:
            word = c["text"]
            ww = draw.textlength(word, font=font)
            if active_local >= 0 and i <= active_local:
                color = (220, 40, 36)  # spoken / current → red
            else:
                color = (72, 72, 80)  # upcoming → visible dark gray
            draw.text((x, y), word, font=font, fill=color)
            x += ww + gap
        y += line_h


def _make_compare_frame(
    left_img: Path | None,
    right_img: Path | None,
    cues: list[dict],
    t: float,
    fallback_text: str,
    char_path: Path | None,
    karaoke: bool,
    brand_name: str,
    clean_export: bool,
    target: str,
    bob: int = 0,
    caption_1: str = "",
    caption_2: str = "",
    frame_1: dict | None = None,
    frame_2: dict | None = None,
    layer_cache: dict[str, Image.Image] | None = None,
) -> Image.Image:
    margin = 72
    gap = 28
    panel_w = (VIDEO_WIDTH - margin * 2 - gap) // 2
    panel_h = int(VIDEO_HEIGHT * 0.34)
    top = 92
    left_box = (margin, top, margin + panel_w, top + panel_h)
    right_box = (margin + panel_w + gap, top, margin + panel_w + gap + panel_w, top + panel_h)
    y_sub = top + panel_h + 90

    # Cache static base (bg + panels) per pointing target + bg phase
    phase = int((max(0.0, t) * 2.2) % 6)
    cache_key = f"{target}:{phase}"
    base = layer_cache.get(cache_key) if layer_cache is not None else None
    if base is None:
        canvas = _paper_bg(t=t, focus=target)
        spotlight = target in {POSE_POINT_1, POSE_POINT_2}
        _draw_panel(
            canvas,
            left_img,
            left_box,
            "1",
            active=(target == POSE_POINT_1),
            caption=caption_1,
            frame=frame_1,
            dimmed=spotlight and target != POSE_POINT_1,
            t=t,
        )
        _draw_panel(
            canvas,
            right_img,
            right_box,
            "2",
            active=(target == POSE_POINT_2),
            caption=caption_2,
            frame=frame_2,
            dimmed=spotlight and target != POSE_POINT_2,
            t=t,
        )
        if brand_name.strip() and not clean_export:
            draw0 = ImageDraw.Draw(canvas)
            draw0.text(
                (40, 24),
                brand_name.strip(),
                font=_load_font(26, bold=True),
                fill=(100, 100, 110),
            )
        if layer_cache is not None:
            layer_cache[cache_key] = canvas.copy()
        base = canvas
    canvas = base.copy()

    draw = ImageDraw.Draw(canvas)
    if karaoke and cues:
        window, active_local = _karaoke_chunk(cues, t)
        _draw_karaoke_light(draw, window, active_local, y_sub)
    else:
        text = fallback_text
        if cues:
            window, _ = _karaoke_chunk(cues, t)
            text = " ".join(c["text"] for c in window) if window else fallback_text
        font = _load_font(48, bold=True)
        words = text.split()
        lines: list[str] = []
        cur = ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if draw.textlength(trial, font=font) <= VIDEO_WIDTH - 120:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        y = y_sub
        for line in lines[:3]:
            tw = draw.textlength(line, font=font)
            draw.text(((VIDEO_WIDTH - tw) / 2, y), line, font=font, fill=(35, 35, 40))
            y += 60

    # Soft idle motion only — mouth lip-sync off
    sway = sway_offset(t, False, target, mouth=0.0)
    bob = bounce_offset(t, False, mouth=0.0)
    canvas = _paste_character_center(
        canvas, char_path, bob=bob, sway=sway, target=target, mouth=0.0
    )
    return canvas


def _make_frame(
    image_path: Path | None,
    cues: list[dict],
    t: float,
    fallback_text: str,
    char_path: Path | None,
    char_pos: str,
    karaoke: bool,
    clean_export: bool,
    brand_name: str,
    scene_hint: str,
    bob: int = 0,
    left_img: Path | None = None,
    right_img: Path | None = None,
    target: str = POSE_CENTER,
    layout: str = "compare",
    caption_1: str = "",
    caption_2: str = "",
    frame_1: dict | None = None,
    frame_2: dict | None = None,
    layer_cache: dict[str, Image.Image] | None = None,
) -> Image.Image:
    if layout == "compare":
        return _make_compare_frame(
            left_img or image_path,
            right_img or image_path,
            cues,
            t,
            fallback_text,
            char_path,
            karaoke,
            brand_name,
            clean_export,
            target,
            bob=bob,
            caption_1=caption_1,
            caption_2=caption_2,
            frame_1=frame_1,
            frame_2=frame_2,
            layer_cache=layer_cache,
        )

    # Legacy full-bleed layout
    canvas = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (18, 18, 20))
    if image_path and image_path.exists():
        img = Image.open(image_path).convert("RGB")
        fr = _normalize_frame(frame_1)
        canvas = _fit_framed(
            img,
            VIDEO_WIDTH,
            VIDEO_HEIGHT,
            mode=fr["mode"],
            zoom=fr["zoom"],
            focus_x=fr["x"],
            focus_y=fr["y"],
            bg=(18, 18, 20),
        )
    else:
        draw_bg = ImageDraw.Draw(canvas)
        draw_bg.rectangle((0, 0, VIDEO_WIDTH, VIDEO_HEIGHT), fill=(24, 24, 28))

    # Soft idle motion only — mouth lip-sync off
    sway = sway_offset(t, False, target, mouth=0.0)
    bob = bounce_offset(t, False, mouth=0.0)
    canvas = _paste_character_center(
        canvas, char_path, bob=bob, sway=sway, target=target, mouth=0.0
    )
    draw = ImageDraw.Draw(canvas)
    y_sub = VIDEO_HEIGHT - 220
    if karaoke and cues:
        window, active_local = _karaoke_chunk(cues, t)
        _draw_karaoke_light(draw, window, active_local, y_sub)
    else:
        text = fallback_text
        if cues:
            window, _ = _karaoke_chunk(cues, t)
            text = " ".join(c["text"] for c in window) if window else fallback_text
        font = _load_font(48, bold=True)
        words = text.split()
        lines: list[str] = []
        cur = ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if draw.textlength(trial, font=font) <= VIDEO_WIDTH - 120:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        y = y_sub
        for line in lines[:3]:
            tw = draw.textlength(line, font=font)
            draw.text(((VIDEO_WIDTH - tw) / 2, y), line, font=font, fill=(255, 255, 255))
            y += 60
    return canvas


def _paste_character(
    canvas: Image.Image,
    char_path: Path | None,
    position: str,
    bob: int = 0,
) -> Image.Image:
    return _paste_character_center(canvas, char_path, bob=bob, target=POSE_CENTER)


def _mix_audio_with_sfx(
    voice_path: Path,
    sfx_clips: list[dict],
    out_path: Path,
    total_duration: float,
) -> Path:
    if not sfx_clips:
        # Re-encode for stable mux later
        mixed = out_path.with_suffix(".m4a")
        _run_ffmpeg(
            [
                _ffmpeg(),
                "-y",
                "-i",
                str(voice_path),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(mixed),
            ],
            "voice-encode",
            expect_file=mixed,
        )
        return mixed

    inputs = ["-i", str(voice_path)]
    filter_parts = []
    mixed_labels = ["[0:a]"]
    valid = 0
    for clip in sfx_clips:
        try:
            path = sfx_path(clip["sfx_id"])
        except FileNotFoundError:
            continue
        delay_ms = int(max(0.0, float(clip.get("start", 0))) * 1000)
        vol = float(clip.get("volume", 0.85))
        inputs += ["-i", str(path)]
        idx = valid + 1
        label = f"s{valid}"
        filter_parts.append(
            f"[{idx}:a]adelay={delay_ms}|{delay_ms},volume={vol}[{label}]"
        )
        mixed_labels.append(f"[{label}]")
        valid += 1

    if valid == 0:
        return _mix_audio_with_sfx(voice_path, [], out_path, total_duration)

    n = valid + 1
    filter_parts.append(
        "".join(mixed_labels)
        + f"amix=inputs={n}:duration=first:dropout_transition=0:normalize=0[aout]"
    )
    mixed = out_path.with_suffix(".m4a")
    _run_ffmpeg(
        [
            _ffmpeg(),
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[aout]",
            "-t",
            f"{total_duration:.3f}",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(mixed),
        ],
        "sfx-mix",
        expect_file=mixed,
    )
    return mixed


def _resolve_char_for_frame(
    *,
    character_id: str | None,
    char_pos: str,
    auto_pose: bool,
    cues: list[dict],
    t: float,
    scene_text: str,
    static_path: Path | None,
    pose_dir: Path | None,
    scene_target: str = POSE_CENTER,
) -> tuple[Path | None, int, str]:
    if char_pos == "hidden":
        return None, 0, POSE_CENTER
    # Mouth disabled — gentle idle bob only
    bob = bounce_offset(t, False, mouth=0.0)
    target = scene_target if scene_target in {POSE_POINT_1, POSE_POINT_2, POSE_CENTER} else POSE_CENTER
    if auto_pose and pose_dir and pose_dir.exists():
        target = pose_at_time(cues, t, scene_text, scene_target=target)
        path = resolve_pose_file(target, char_pos, pose_dir)
        if path.exists():
            return path, bob, target
    return static_path, bob, target


class RenderCancelled(Exception):
    """Raised when the user cancels an in-progress render."""


async def _wait_if_paused(
    pause_event: asyncio.Event | None,
    cancel_event: asyncio.Event | None = None,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RenderCancelled("Render cancelled by user")
    if pause_event is None:
        return
    while not pause_event.is_set():
        if cancel_event is not None and cancel_event.is_set():
            raise RenderCancelled("Render cancelled by user")
        await asyncio.sleep(0.25)


async def render_project(
    project: dict,
    project_folder: Path,
    pause_event: asyncio.Event | None = None,
    cancel_event: asyncio.Event | None = None,
    progress_cb=None,
) -> Path:
    def report(percent: float, message: str = "") -> None:
        if progress_cb:
            try:
                progress_cb(percent, message)
            except Exception:  # noqa: BLE001
                pass

    script = (project.get("script") or "").strip()
    if not script:
        raise ValueError(
            "Kịch bản đang trống. Hãy nhập nội dung (tự động lưu) trước khi Render."
        )

    scenes = parse_script(script)
    if not scenes:
        scenes = [Scene(index=1, text=script)]

    images = project.get("images") or []
    image_paths = [project_folder / "images" / i["name"] for i in images]
    left_img = image_paths[0] if len(image_paths) >= 1 else None
    right_img = image_paths[1] if len(image_paths) >= 2 else left_img
    voice = project.get("voice") or "vi-VN-HoaiMyNeural"
    karaoke = bool(project.get("karaoke", True))
    clean_export = bool(project.get("clean_export", True))
    brand_name = project.get("brand_name") or ""
    char_pos = project.get("character_position") or "center"
    auto_pose = bool(project.get("auto_pose", True))
    character_id = project.get("character_id") or "tuti"
    layout = project.get("layout") or "compare"
    caption_1 = project.get("caption_1") or ""
    caption_2 = project.get("caption_2") or ""
    frame_1 = _normalize_frame(project.get("frame_1"))
    frame_2 = _normalize_frame(project.get("frame_2"))
    image_frames_raw = project.get("image_frames") if isinstance(project.get("image_frames"), dict) else {}
    image_frames = {
        str(k): _normalize_frame(v) for k, v in image_frames_raw.items() if k
    }
    # Keep legacy frame_1/2 as defaults for first two filenames
    if images:
        n0 = images[0].get("name")
        if n0 and n0 not in image_frames:
            image_frames[n0] = frame_1
        if len(images) >= 2:
            n1 = images[1].get("name")
            if n1 and n1 not in image_frames:
                image_frames[n1] = frame_2
    speed = normalize_speed(project.get("speed", 1.0))
    try:
        fps = int(float(project.get("render_fps", VIDEO_FPS)))
    except (TypeError, ValueError):
        fps = VIDEO_FPS
    if fps not in {20, 24, 30}:
        fps = VIDEO_FPS

    _clear_render_caches()
    report(2, "Đang chuẩn bị…")

    static_path = None
    pose_dir = None
    if char_pos != "hidden":
        try:
            static_path = character_file(character_id)
        except FileNotFoundError:
            static_path = None
        pose_dir = character_pose_dir(character_id)

    audio_dir = project_folder / "audio"
    frames_dir = project_folder / "frames"
    if frames_dir.exists():
        for old in frames_dir.glob("*.jpg"):
            old.unlink()
    frames_dir.mkdir(exist_ok=True)
    audio_dir.mkdir(exist_ok=True)

    segment_audios: list[Path] = []
    frame_files: list[Path] = []
    global_frame = 0
    total_duration = 0.0
    total_scenes = max(1, len(scenes))

    # ---- Phase 1: all TTS first (fail fast; reuse cache; no wasted frames) ----
    scene_tts: list[tuple[Path, list[dict], float]] = []
    live_tts_count = 0
    for i, scene in enumerate(scenes):
        await _wait_if_paused(pause_event, cancel_event)
        tts_pct = 5 + (i / total_scenes) * 30
        report(tts_pct, f"Đang tạo giọng đọc cảnh {scene.index}/{total_scenes}…")
        audio_path = audio_dir / f"scene_{scene.index:03d}.mp3"
        vtt_path = audio_dir / f"scene_{scene.index:03d}.vtt"

        last_exc: Exception | None = None
        used_audio = audio_path
        cues: list[dict] = []
        from_cache = False
        # More scenes (2+ kịch bản) → more Edge pressure; retry whole scene
        scene_tries = 4 if total_scenes >= 4 else 3
        for attempt in range(scene_tries):
            try:
                used_audio, _, cues, from_cache = await synthesize_with_subtitles(
                    scene.text, voice, audio_path, vtt_path, speed=speed
                )
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                report(
                    tts_pct,
                    f"TTS cảnh {scene.index} lỗi — thử lại {attempt + 1}/{scene_tries}…",
                )
                await asyncio.sleep(1.2 + attempt * 1.5)
        if last_exc is not None:
            raise RuntimeError(
                f"TTS lỗi ở cảnh {scene.index}. Kiểm tra mạng / giọng đọc.\n{last_exc}"
            ) from last_exc

        if not used_audio.exists() or used_audio.stat().st_size < 100:
            raise RuntimeError(f"File giọng đọc cảnh {scene.index} tạo thất bại.")

        # Pace live Edge calls harder when many scenes (2+ scripts)
        if not from_cache:
            live_tts_count += 1
            if i + 1 < total_scenes:
                gap = 0.7 + min(live_tts_count, 6) * 0.35
                if total_scenes >= 4:
                    gap += 0.5
                await asyncio.sleep(gap)

        duration = max(_audio_duration(used_audio), 1.5)
        segment_audios.append(used_audio)
        total_duration += duration
        scene_tts.append((used_audio, cues, duration))

    report(35, "Đã có giọng đọc — đang vẽ khung hình…")

    # ---- Phase 2: frames (reuse identical visual states) ----
    import shutil

    for i, scene in enumerate(scenes):
        await _wait_if_paused(pause_event, cancel_event)
        _used_audio, cues, duration = scene_tts[i]

        scene_left = left_img
        scene_right = right_img
        scene_cap_1 = caption_1
        scene_cap_2 = caption_2
        seg = max(1, int(getattr(scene, "segment", 1) or 1))
        seg_i = seg - 1
        setup_list = project.get("scene_setup") if isinstance(project.get("scene_setup"), list) else []
        setup = setup_list[seg_i] if seg_i < len(setup_list) and isinstance(setup_list[seg_i], dict) else None
        if setup:
            name_to_path = {p.name: p for p in image_paths}
            if setup.get("left") and setup["left"] in name_to_path:
                scene_left = name_to_path[setup["left"]]
            if setup.get("right") and setup["right"] in name_to_path:
                scene_right = name_to_path[setup["right"]]
            if setup.get("caption_1"):
                scene_cap_1 = setup["caption_1"]
            if setup.get("caption_2"):
                scene_cap_2 = setup["caption_2"]
        elif len(image_paths) >= 2 * seg:
            scene_left = image_paths[2 * seg_i]
            scene_right = image_paths[2 * seg_i + 1]
        elif len(image_paths) >= 2:
            scene_left = image_paths[0]
            scene_right = image_paths[1]

        scene_frame_1 = image_frames.get(scene_left.name, frame_1) if scene_left else frame_1
        scene_frame_2 = image_frames.get(scene_right.name, frame_2) if scene_right else frame_2

        layer_cache: dict[str, Image.Image] = {}
        n_frames = max(int(round(duration * fps)), 1)
        scene_base = 35 + (i / total_scenes) * 55
        scene_span = 55 / total_scenes
        last_key: tuple | None = None
        last_frame_path: Path | None = None

        for f in range(n_frames):
            if f % 16 == 0:
                await _wait_if_paused(pause_event, cancel_event)
                frame_pct = scene_base + (f / max(1, n_frames)) * scene_span
                report(
                    frame_pct,
                    f"Đang vẽ frame cảnh {scene.index}/{total_scenes} ({f + 1}/{n_frames})",
                )
            t = min(duration - 1e-3, f / fps) if duration > 0 else 0.0
            char_path, bob, target = _resolve_char_for_frame(
                character_id=character_id,
                char_pos=char_pos,
                auto_pose=auto_pose,
                cues=cues,
                t=t,
                scene_text=scene.text,
                static_path=static_path,
                pose_dir=pose_dir,
                scene_target=getattr(scene, "target", POSE_CENTER),
            )
            _, active_local = _karaoke_chunk(cues, t) if (karaoke and cues) else ([], -1)
            bg_phase = int((max(0.0, t) * 2.2) % 6)
            # Quantize bob so tiny idle motion does not force a full redraw
            state_key = (
                str(char_path) if char_path else "",
                target,
                active_local,
                bg_phase,
                bob // 2,
            )
            out = frames_dir / f"frame_{global_frame:06d}.jpg"
            if last_key == state_key and last_frame_path is not None:
                shutil.copyfile(last_frame_path, out)
            else:
                frame = _make_frame(
                    scene_left,
                    cues,
                    t,
                    scene.text,
                    char_path,
                    char_pos,
                    karaoke,
                    clean_export,
                    brand_name,
                    f"Cảnh {scene.index}/{len(scenes)}",
                    bob=bob,
                    left_img=scene_left,
                    right_img=scene_right,
                    target=target,
                    layout=layout,
                    caption_1=scene_cap_1,
                    caption_2=scene_cap_2,
                    frame_1=scene_frame_1,
                    frame_2=scene_frame_2,
                    layer_cache=layer_cache,
                )
                frame.save(out, quality=78, optimize=False, subsampling=2)
                last_key = state_key
                last_frame_path = out
            frame_files.append(out)
            global_frame += 1

        layer_cache.clear()
        report(35 + ((i + 1) / total_scenes) * 55, f"Xong cảnh {scene.index}/{total_scenes}")

    list_file = audio_dir / "concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in segment_audios),
        encoding="utf-8",
    )
    merged_voice = audio_dir / "voice_all.mp3"
    await _wait_if_paused(pause_event, cancel_event)
    report(91, "Đang ghép âm thanh…")
    _run_ffmpeg(
        [
            _ffmpeg(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(merged_voice),
        ],
        "concat-voice",
        expect_file=merged_voice,
    )

    mixed_audio = _mix_audio_with_sfx(
        merged_voice,
        [],  # SFX applied AFTER render in timeline export step
        audio_dir / "final_audio.mp3",
        total_duration,
    )

    output_dir = project_folder / "output"
    output_dir.mkdir(exist_ok=True)
    base_mp4 = output_dir / "video_base.mp4"
    output_mp4 = output_dir / "video.mp4"

    await _wait_if_paused(pause_event, cancel_event)
    report(94, "Đang encode video MP4…")
    _run_ffmpeg(
        [
            _ffmpeg(),
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "frame_%06d.jpg"),
            "-i",
            str(mixed_audio),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{total_duration:.3f}",
            "-movflags",
            "+faststart",
            str(base_mp4),
        ],
        "encode-mp4",
        expect_file=base_mp4,
    )

    if not base_mp4.exists() or base_mp4.stat().st_size < 1000:
        raise RuntimeError("Xuất MP4 thất bại — file quá nhỏ hoặc không tạo được.")

    # Working preview starts as clean base (no SFX yet)
    shutil.copyfile(base_mp4, output_mp4)

    manifest = {
        "scenes": len(scenes),
        "frames": len(frame_files),
        "duration_sec": total_duration,
        "output": output_mp4.name,
        "base": base_mp4.name,
        "character": character_id,
        "auto_pose": auto_pose,
        "layout": layout,
        "speed": speed,
        "fps": fps,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    project["duration_sec"] = round(total_duration, 3)
    project["output_file"] = output_mp4.name
    project["base_file"] = base_mp4.name
    _clear_render_caches()
    report(99, "Sắp xong…")
    return output_mp4


def apply_sfx_export(project: dict, project_folder: Path) -> Path:
    """Mix SFX onto already-rendered base video (post-production step)."""
    output_dir = project_folder / "output"
    base_mp4 = output_dir / (project.get("base_file") or "video_base.mp4")
    if not base_mp4.exists():
        # fallback to current video as base
        base_mp4 = output_dir / (project.get("output_file") or "video.mp4")
    if not base_mp4.exists():
        raise FileNotFoundError("Chưa có video render. Hãy Render trước, rồi mới thêm SFX.")

    duration = float(project.get("duration_sec") or _audio_duration(base_mp4))
    clips = project.get("sfx_clips") or []
    out_mp4 = output_dir / "video.mp4"

    if not clips:
        import shutil

        shutil.copyfile(base_mp4, out_mp4)
        return out_mp4

    # Build filter: take video from base, mix audio with delayed SFX
    inputs = ["-i", str(base_mp4)]
    filter_parts = []
    labels = ["[0:a]"]
    valid = 0
    for clip in clips:
        try:
            path = sfx_path(clip["sfx_id"])
        except FileNotFoundError:
            continue
        delay_ms = int(max(0.0, float(clip.get("start", 0))) * 1000)
        vol = float(clip.get("volume", 0.85))
        inputs += ["-i", str(path)]
        idx = valid + 1
        lab = f"s{valid}"
        filter_parts.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms},volume={vol}[{lab}]")
        labels.append(f"[{lab}]")
        valid += 1

    if valid == 0:
        import shutil

        shutil.copyfile(base_mp4, out_mp4)
        return out_mp4

    filter_parts.append(
        "".join(labels)
        + f"amix=inputs={valid + 1}:duration=first:dropout_transition=0:normalize=0[aout]"
    )
    tmp = output_dir / "video_sfx_tmp.mp4"
    _run_ffmpeg(
        [
            _ffmpeg(),
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            "-t",
            f"{duration:.3f}",
            str(tmp),
        ],
        "apply-sfx",
        expect_file=tmp,
    )
    import shutil

    shutil.move(str(tmp), str(out_mp4))
    return out_mp4
