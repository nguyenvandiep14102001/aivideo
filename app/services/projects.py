from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import PROJECTS_DIR, ensure_dirs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_frame_dict(frame: dict | None) -> dict:
    base = {"mode": "cover", "zoom": 1.0, "x": 0.5, "y": 0.5}
    cur = frame if isinstance(frame, dict) else {}
    merged = {**base, **cur}
    mode = str(merged.get("mode", "cover")).lower()
    merged["mode"] = "contain" if mode == "contain" else "cover"
    try:
        merged["zoom"] = max(1.0, min(3.0, float(merged.get("zoom", 1.0) or 1.0)))
    except (TypeError, ValueError):
        merged["zoom"] = 1.0
    for axis in ("x", "y"):
        try:
            merged[axis] = max(0.0, min(1.0, float(merged.get(axis, 0.5))))
        except (TypeError, ValueError):
            merged[axis] = 0.5
    return merged


def _defaults() -> dict[str, Any]:
    return {
        "character_id": "tuti",
        "character_position": "center",
        "auto_pose": True,
        "layout": "compare",
        "karaoke": True,
        "clean_export": True,
        "brand_name": "",
        "caption_1": "",
        "caption_2": "",
        "frame_1": {"mode": "cover", "zoom": 1.0, "x": 0.5, "y": 0.5},
        "frame_2": {"mode": "cover", "zoom": 1.0, "x": 0.5, "y": 0.5},
        "image_frames": {},
        "speed": 1.0,
        "render_fps": 20,
        "sfx_clips": [],
        "base_file": None,
        "scene_setup": [],
        "script_count": 1,
    }


def normalize_project(data: dict[str, Any]) -> dict[str, Any]:
    for key, value in _defaults().items():
        data.setdefault(key, value)
    for key in ("frame_1", "frame_2"):
        data[key] = _normalize_frame_dict(data.get(key))
    # Per-image frames keyed by filename
    raw_frames = data.get("image_frames")
    if not isinstance(raw_frames, dict):
        raw_frames = {}
    cleaned_frames: dict[str, Any] = {}
    for name, fr in raw_frames.items():
        key = str(name or "").strip()
        if not key:
            continue
        cleaned_frames[key] = _normalize_frame_dict(fr if isinstance(fr, dict) else {})
    # Seed from frame_1/frame_2 for first two images if missing
    images = data.get("images") if isinstance(data.get("images"), list) else []
    if len(images) >= 1 and images[0].get("name") and images[0]["name"] not in cleaned_frames:
        cleaned_frames[images[0]["name"]] = dict(data["frame_1"])
    if len(images) >= 2 and images[1].get("name") and images[1]["name"] not in cleaned_frames:
        cleaned_frames[images[1]["name"]] = dict(data["frame_2"])
    data["image_frames"] = cleaned_frames
    try:
        from app.services.tts import normalize_speed

        data["speed"] = normalize_speed(data.get("speed", 1.0))
    except Exception:  # noqa: BLE001
        data["speed"] = 1.0
    try:
        fps = int(float(data.get("render_fps", 24)))
    except (TypeError, ValueError):
        fps = 24
    data["render_fps"] = fps if fps in {20, 24, 30} else 24
    setup = data.get("scene_setup")
    if not isinstance(setup, list):
        setup = []
    cleaned_setup = []
    for item in setup:
        if not isinstance(item, dict):
            continue
        cleaned_setup.append(
            {
                "left": str(item.get("left") or "").strip() or None,
                "right": str(item.get("right") or "").strip() or None,
                "caption_1": str(item.get("caption_1") or "").strip()[:60],
                "caption_2": str(item.get("caption_2") or "").strip()[:60],
            }
        )
    data["scene_setup"] = cleaned_setup
    try:
        sc = int(float(data.get("script_count", 1)))
    except (TypeError, ValueError):
        sc = 1
    data["script_count"] = max(1, min(6, sc))
    return data


def project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def meta_path(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def load_project(project_id: str) -> dict[str, Any]:
    path = meta_path(project_id)
    if not path.exists():
        raise FileNotFoundError(project_id)
    return normalize_project(json.loads(path.read_text(encoding="utf-8")))


def save_project(data: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    data = normalize_project(data)
    pid = data["id"]
    folder = project_dir(pid)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "images").mkdir(exist_ok=True)
    (folder / "audio").mkdir(exist_ok=True)
    (folder / "output").mkdir(exist_ok=True)
    data["updated_at"] = _now()
    meta_path(pid).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


def create_project(title: str = "Dự án mới") -> dict[str, Any]:
    ensure_dirs()
    pid = uuid.uuid4().hex[:12]
    data = {
        "id": pid,
        "title": title.strip() or "Dự án mới",
        "script": "",
        "voice": "vi-VN-HoaiMyNeural",
        "render_fps": 20,
        "images": [],
        "status": "draft",
        "output_file": None,
        "created_at": _now(),
        "updated_at": _now(),
        "error": None,
        **_defaults(),
    }
    return save_project(data)


def list_projects() -> list[dict[str, Any]]:
    ensure_dirs()
    items: list[dict[str, Any]] = []
    for path in PROJECTS_DIR.glob("*/project.json"):
        try:
            items.append(normalize_project(json.loads(path.read_text(encoding="utf-8"))))
        except (json.JSONDecodeError, OSError):
            continue
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return items


def delete_project(project_id: str) -> None:
    folder = project_dir(project_id)
    if folder.exists():
        shutil.rmtree(folder)


def add_image(project_id: str, filename: str, data: bytes) -> dict[str, Any]:
    project = load_project(project_id)
    safe = Path(filename).name
    ext = Path(safe).suffix.lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        raise ValueError("Unsupported image type")
    name = f"{uuid.uuid4().hex[:8]}{ext}"
    dest = project_dir(project_id) / "images" / name
    dest.write_bytes(data)
    project["images"].append({"name": name, "original": safe})
    return save_project(project)


def remove_image(project_id: str, name: str) -> dict[str, Any]:
    project = load_project(project_id)
    safe = Path(name).name
    img = project_dir(project_id) / "images" / safe
    if img.exists():
        img.unlink()
    project["images"] = [i for i in project["images"] if i["name"] != safe]
    return save_project(project)


def update_sfx_clips(project_id: str, clips: list[dict[str, Any]]) -> dict[str, Any]:
    project = load_project(project_id)
    cleaned = []
    for clip in clips:
        try:
            start = float(clip.get("start", 0))
            volume = float(clip.get("volume", 0.85))
        except (TypeError, ValueError):
            continue
        sfx_id = str(clip.get("sfx_id", "")).strip()
        if not sfx_id:
            continue
        cleaned.append(
            {
                "id": str(clip.get("id") or uuid.uuid4().hex[:8]),
                "sfx_id": Path(sfx_id).name,
                "start": max(0.0, start),
                "volume": min(1.5, max(0.05, volume)),
            }
        )
    project["sfx_clips"] = cleaned
    return save_project(project)
