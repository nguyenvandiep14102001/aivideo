from __future__ import annotations

import json
import uuid
from io import BytesIO
from typing import Any

from PIL import Image

from app.config import CHARACTERS_DIR, ensure_dirs
from app.services.sprites_split import split_pose_sheet


POSE_ORDER = [
    "point_left",
    "point_right",
    "center",
    "point_left_smile",
    "point_right_b",
]


def import_sprite_sheet(
    data: bytes,
    label: str | None = None,
    character_id: str | None = None,
    *,
    skip_rembg: bool = False,
) -> dict[str, Any]:
    """Upload a horizontal sprite sheet → animated character pack."""
    ensure_dirs()
    cid = character_id or uuid.uuid4().hex[:10]
    out_dir = CHARACTERS_DIR / "custom" / cid
    if out_dir.exists():
        for old in out_dir.glob("*.png"):
            old.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(BytesIO(data)).convert("RGBA")
    split_pose_sheet(img, out_dir, POSE_ORDER, skip_rembg=skip_rembg)

    # aliases
    mapping = {
        "point_1": "point_left_smile" if (out_dir / "point_left_smile.png").exists() else "point_left",
        "point_2": "point_right",
        "point_center": "center",
    }
    for alias, src in mapping.items():
        src_path = out_dir / f"{src}.png"
        if src_path.exists():
            Image.open(src_path).save(out_dir / f"{alias}.png", compress_level=1)

    preview_src = out_dir / "center.png"
    if not preview_src.exists():
        preview_src = next(out_dir.glob("*.png"))
    preview = Image.open(preview_src).copy()
    preview.thumbnail((400, 520), Image.Resampling.LANCZOS)
    preview.save(out_dir / "preview.png", compress_level=1)

    entry = {
        "id": cid,
        "label": (label or "Nhân vật sheet").strip()[:40],
        "kind": "animated",
        "file": f"custom/{cid}/preview.png",
        "pose_dir": f"custom/{cid}",
    }
    _upsert_custom_index(entry)
    entry["url"] = f"/characters/{cid}"
    return entry


def _upsert_custom_index(entry: dict[str, Any]) -> None:
    custom_dir = CHARACTERS_DIR / "custom"
    meta_file = custom_dir / "index.json"
    items = []
    if meta_file.exists():
        try:
            items = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            items = []
    items = [i for i in items if i.get("id") != entry["id"]]
    items.append(
        {
            "id": entry["id"],
            "label": entry["label"],
            "file": entry["file"],
            "pose_dir": entry.get("pose_dir"),
            "kind": "animated",
        }
    )
    meta_file.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
