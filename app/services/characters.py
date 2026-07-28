from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.config import CHARACTERS_DIR, ensure_dirs

BUILTIN_IDS = frozenset({"tuti", "panboy", "maya", "khoi", "lan", "minh"})


def _index_entry(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": item["id"],
        "label": item["label"],
        "file": item["file"],
    }
    if item.get("pose_dir"):
        out["pose_dir"] = item["pose_dir"]
    if item.get("kind"):
        out["kind"] = item["kind"]
    return out


def is_custom_character(character_id: str) -> bool:
    cid = Path(character_id).name
    if cid in BUILTIN_IDS:
        return False
    return any(i["id"] == cid for i in list_custom_characters())


BUILTIN = [
    {"id": "maya", "label": "Maya", "accent": (232, 163, 90), "skin": (240, 200, 170), "hair": (40, 28, 22)},
    {"id": "khoi", "label": "Khôi", "accent": (106, 208, 224), "skin": (220, 175, 140), "hair": (25, 22, 20)},
    {"id": "lan", "label": "Lan", "accent": (224, 122, 106), "skin": (245, 210, 185), "hair": (90, 45, 30)},
    {"id": "minh", "label": "Minh", "accent": (125, 206, 160), "skin": (210, 168, 130), "hair": (50, 40, 35)},
]


def _font(size: int) -> ImageFont.ImageFont:
    for path in (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _draw_character(meta: dict, size: tuple[int, int] = (720, 1100)) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    accent = meta["accent"]
    skin = meta["skin"]
    hair = meta["hair"]

    # body
    d.rounded_rectangle((w * 0.28, h * 0.42, w * 0.72, h * 0.98), radius=80, fill=(*accent, 255))
    # neck
    d.rectangle((w * 0.45, h * 0.34, w * 0.55, h * 0.45), fill=(*skin, 255))
    # head
    d.ellipse((w * 0.30, h * 0.08, w * 0.70, h * 0.42), fill=(*skin, 255))
    # hair
    d.ellipse((w * 0.28, h * 0.05, w * 0.72, h * 0.28), fill=(*hair, 255))
    d.pieslice((w * 0.28, h * 0.12, w * 0.72, h * 0.40), 200, 340, fill=(*hair, 255))
    # eyes
    d.ellipse((w * 0.40, h * 0.22, w * 0.45, h * 0.26), fill=(30, 24, 20, 255))
    d.ellipse((w * 0.55, h * 0.22, w * 0.60, h * 0.26), fill=(30, 24, 20, 255))
    # smile
    d.arc((w * 0.43, h * 0.28, w * 0.57, h * 0.36), 20, 160, fill=(120, 70, 60, 255), width=4)
    # name badge
    badge = meta["label"]
    font = _font(42)
    tw = d.textlength(badge, font=font)
    d.rounded_rectangle(
        ((w - tw) / 2 - 18, h * 0.88, (w + tw) / 2 + 18, h * 0.94),
        radius=16,
        fill=(20, 18, 16, 210),
    )
    d.text(((w - tw) / 2, h * 0.888), badge, font=font, fill=(255, 255, 255, 255))
    return img


def ensure_builtin_characters() -> list[dict[str, Any]]:
    ensure_dirs()
    builtin_dir = CHARACTERS_DIR / "builtin"
    builtin_dir.mkdir(parents=True, exist_ok=True)
    items = []

    # TuTi compare-pack (1 left / 2 right / center)
    tuti_dir = builtin_dir / "tuti"
    tuti_preview = tuti_dir / "preview.png"
    if tuti_preview.exists() or (tuti_dir / "center.png").exists():
        if not tuti_preview.exists():
            src = tuti_dir / "center.png"
            img = Image.open(src).convert("RGBA")
            img.thumbnail((360, 480))
            img.save(tuti_preview)
        items.append(
            {
                "id": "tuti",
                "label": "TuTi (1/2/giữa)",
                "kind": "animated",
                "file": "builtin/tuti/preview.png",
                "pose_dir": "builtin/tuti",
                "url": "/characters/tuti",
            }
        )

    # Animated sprite pack (PanBoy)
    panboy_dir = builtin_dir / "panboy"
    panboy_preview = panboy_dir / "preview.png"
    if panboy_preview.exists() or (panboy_dir / "point_up_right.png").exists():
        if not panboy_preview.exists():
            src = panboy_dir / "point_up_right.png"
            img = Image.open(src).convert("RGBA")
            img.thumbnail((360, 480))
            img.save(panboy_preview)
        items.append(
            {
                "id": "panboy",
                "label": "PanBoy (động)",
                "kind": "animated",
                "file": "builtin/panboy/preview.png",
                "pose_dir": "builtin/panboy",
                "url": "/characters/panboy",
            }
        )

    for meta in BUILTIN:
        path = builtin_dir / f"{meta['id']}.png"
        if not path.exists():
            _draw_character(meta).save(path)
        items.append(
            {
                "id": meta["id"],
                "label": meta["label"],
                "kind": "builtin",
                "file": f"builtin/{meta['id']}.png",
                "url": f"/characters/{meta['id']}",
            }
        )
    return items


def get_character(character_id: str) -> dict[str, Any]:
    cid = Path(character_id).name
    for item in list_characters():
        if item["id"] == cid:
            return item
    raise FileNotFoundError(cid)


def character_file(character_id: str) -> Path:
    item = get_character(character_id)
    return CHARACTERS_DIR / item["file"]


def character_pose_dir(character_id: str) -> Path | None:
    try:
        item = get_character(character_id)
    except FileNotFoundError:
        return None
    pose_dir = item.get("pose_dir")
    if not pose_dir:
        return None
    path = CHARACTERS_DIR / pose_dir
    return path if path.exists() else None


def list_custom_characters() -> list[dict[str, Any]]:
    ensure_dirs()
    custom_dir = CHARACTERS_DIR / "custom"
    custom_dir.mkdir(parents=True, exist_ok=True)
    meta_file = custom_dir / "index.json"
    if not meta_file.exists():
        return []
    try:
        items = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    for item in items:
        item["kind"] = item.get("kind") or "custom"
        item["url"] = f"/characters/{item['id']}"
        if item.get("pose_dir"):
            item["kind"] = "animated"
    return items


def list_characters() -> list[dict[str, Any]]:
    # animated pack first
    return ensure_builtin_characters() + list_custom_characters()


def add_custom_character(filename: str, data: bytes, label: str | None = None) -> dict[str, Any]:
    ensure_dirs()
    custom_dir = CHARACTERS_DIR / "custom"
    custom_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower() or ".png"
    if ext not in {".png", ".webp", ".jpg", ".jpeg"}:
        raise ValueError("Character must be PNG/WebP/JPG (PNG có nền trong suốt tốt nhất)")
    cid = uuid.uuid4().hex[:10]
    name = f"{cid}{ext}"
    dest = custom_dir / name
    # Normalize to PNG with alpha when possible
    from io import BytesIO

    img = Image.open(BytesIO(data)).convert("RGBA")
    # Soft crop empty margins lightly by keeping as-is; just resize tall
    img.thumbnail((720, 1100), Image.Resampling.LANCZOS)
    out = custom_dir / f"{cid}.png"
    img.save(out)
    if dest != out and dest.exists():
        dest.unlink()

    entry = {
        "id": cid,
        "label": (label or Path(filename).stem or "Nhân vật").strip()[:40],
        "kind": "custom",
        "file": f"custom/{cid}.png",
    }
    meta_file = custom_dir / "index.json"
    items = list_custom_characters()
    # strip urls before save
    clean = [_index_entry(i) for i in items]
    clean.append(_index_entry(entry))
    meta_file.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    entry["url"] = f"/characters/{cid}"
    return entry


def delete_custom_character(character_id: str) -> None:
    cid = Path(character_id).name
    if cid in BUILTIN_IDS:
        raise ValueError("Không thể xóa nhân vật mặc định của app.")
    custom_dir = CHARACTERS_DIR / "custom"
    meta_file = custom_dir / "index.json"
    items = list_custom_characters()
    found = False
    keep: list[dict[str, Any]] = []
    for item in items:
        if item["id"] == cid:
            found = True
            pose_dir = item.get("pose_dir")
            if pose_dir:
                folder = CHARACTERS_DIR / pose_dir
                if folder.is_dir():
                    shutil.rmtree(folder, ignore_errors=True)
            path = CHARACTERS_DIR / item["file"]
            if path.is_file():
                path.unlink()
            flat = custom_dir / f"{cid}.png"
            if flat.is_file():
                flat.unlink()
        else:
            keep.append(_index_entry(item))
    if not found:
        raise FileNotFoundError(cid)
    meta_file.write_text(json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")
