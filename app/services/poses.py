from __future__ import annotations

import re
from pathlib import Path

# Logical targets for compare layout
POSE_POINT_1 = "point_1"  # left panel
POSE_POINT_2 = "point_2"  # right panel
POSE_CENTER = "point_center"
POSE_CONFUSED = "confused"
POSE_IDLE = "idle"

_LEADING_MARK = re.compile(
    r"^\s*(?:\[(?P<a>[12])\]|(?P<b>[12])\s*[\.\)\:\-–—])\s*",
    re.UNICODE,
)
_FIRST_LINE_MARK = re.compile(
    r"^\s*(?:\[(?P<a>[12])\]|(?P<b>[12])\s*[\.\)\:\-–—]?)\s*$",
    re.UNICODE,
)


def extract_target_and_speech(block: str) -> tuple[str, str]:
    """
    Optional silent markers at scene start: 1. / 2. / [1] / [2]
    → set pointing target, strip marker from spoken TTS text.
    """
    raw = (block or "").strip()
    if not raw:
        return POSE_CENTER, ""

    lines = raw.splitlines()
    if lines:
        m0 = _FIRST_LINE_MARK.match(lines[0].strip())
        if m0 and len(lines) > 1:
            digit = m0.group("a") or m0.group("b")
            target = POSE_POINT_1 if digit == "1" else POSE_POINT_2
            return target, "\n".join(lines[1:]).strip()

    m = _LEADING_MARK.match(raw)
    if m:
        digit = m.group("a") or m.group("b")
        target = POSE_POINT_1 if digit == "1" else POSE_POINT_2
        return target, raw[m.end() :].strip()

    return POSE_CENTER, raw


def detect_target_from_text(text: str) -> str:
    target, _ = extract_target_and_speech(text)
    return target


def resolve_pose_file(
    pose: str,
    character_side: str,
    pose_dir: Path,
) -> Path:
    name_map = {
        POSE_POINT_1: ("point_1", "point_left_smile", "point_left", "point_up_left"),
        POSE_POINT_2: ("point_2", "point_right", "point_right_b", "point_up_right"),
        POSE_CENTER: ("point_center", "center", "confused"),
        POSE_CONFUSED: ("center", "confused", "point_center"),
        POSE_IDLE: ("point_center", "center", "point_right"),
        "point_content": ("point_1", "point_left", "point_right"),
        "point_left": ("point_1", "point_left", "point_left_smile"),
        "point_right": ("point_2", "point_right", "point_right_b"),
    }
    candidates = name_map.get(pose, ("point_center", "center", "point_right"))
    for name in candidates:
        path = pose_dir / f"{name}.png"
        if path.exists():
            return path
    for alt in sorted(pose_dir.glob("*.png")):
        if not alt.name.startswith("_") and alt.name != "preview.png":
            return alt
    return pose_dir / "preview.png"


def detect_pose_from_text(text: str) -> str:
    return detect_target_from_text(text)


def pose_at_time(
    cues: list[dict],
    t: float,
    scene_text: str,
    window: float = 0.9,
    scene_target: str | None = None,
) -> str:
    """Pointing from silent 1./2. markers only — never from spoken words."""
    if scene_target in {POSE_POINT_1, POSE_POINT_2, POSE_CENTER}:
        return scene_target
    return detect_target_from_text(scene_text)


def bounce_offset(t: float, speaking: bool) -> int:
    if not speaking:
        return 0
    import math

    return int(4 * math.sin(t * 6.5))
