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


def bounce_offset(t: float, speaking: bool, mouth: float = 0.0) -> int:
    """Vertical bob locked to mouth openness so body and lips move together."""
    import math

    m = max(0.0, min(1.0, float(mouth or 0.0)))
    if m < 0.05 and not speaking:
        return int(1.0 * math.sin(t * 1.8))
    # Bob peaks with mouth open; tiny idle while speaking gaps
    return int(m * (7.0 * math.sin(t * 9.0) + 3.0) + (1.5 if speaking else 0))


def sway_offset(t: float, speaking: bool, target: str = POSE_CENTER, mouth: float = 0.0) -> int:
    """Horizontal sway driven by the same mouth signal."""
    import math

    m = max(0.0, min(1.0, float(mouth or 0.0)))
    base = 1.5 * math.sin(t * 2.2)
    base += m * 5.0 * math.sin(t * 6.5)
    if target == POSE_POINT_1:
        base -= 4
    elif target == POSE_POINT_2:
        base += 4
    return int(base)


_VI_VOWELS = set("aeiouyăâêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵAEIOUYĂÂÊÔƠƯ")


def mouth_open_amount(cues: list[dict], t: float) -> float:
    """
    0..1 lip openness synced to word-boundary cues.
    Opens quickly at word onset (when speech starts), closes at end —
    matches karaoke timing instead of peaking mid-word out of phase.
    """
    if not cues:
        return 0.0
    best = 0.0
    for c in cues:
        start = float(c.get("offset", 0))
        dur = max(0.06, float(c.get("duration", 0.12)))
        # Slight lead so mouth opens just as audio begins
        start -= 0.02
        end = start + dur + 0.03
        if t < start or t > end:
            continue
        local = t - start
        span = max(end - start, 0.05)
        # Fast attack (~18%), hold, quick release (~25%)
        attack = span * 0.18
        release = span * 0.28
        if local <= attack:
            amt = local / max(attack, 0.01)
        elif local >= span - release:
            amt = max(0.0, (span - local) / max(release, 0.01))
        else:
            amt = 1.0
        text = str(c.get("text") or "")
        letters = [ch for ch in text if ch.isalnum() or ch in _VI_VOWELS]
        has_vowel = any(ch in _VI_VOWELS for ch in text)
        # Consonant-only / very short → barely open
        if not has_vowel and len(letters) <= 2:
            amt *= 0.35
        elif has_vowel:
            amt *= 1.0
        else:
            amt *= 0.7
        # Micro pulse inside long words (syllable feel) — same phase as mouth
        if dur > 0.28 and amt > 0.2:
            import math

            syl = 0.55 + 0.45 * abs(math.sin((local / span) * math.pi * max(2, int(dur / 0.18))))
            amt *= syl
        best = max(best, max(0.0, min(1.0, amt)))
    return min(1.0, best)

