from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.poses import (
    POSE_CENTER,
    POSE_POINT_1,
    POSE_POINT_2,
    extract_target_and_speech,
)


@dataclass
class Scene:
    index: int
    text: str  # spoken (markers stripped)
    target: str = POSE_CENTER
    raw: str = ""


def parse_script(script: str) -> list[Scene]:
    """
    Prefer blank-line scene breaks.
    Leading 1. / 2. set point direction and are removed from TTS.
    """
    text = (script or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]

    # If one big block but has multiple 1./2./N. headers, split on those
    if len(blocks) == 1:
        numbered_parts = re.split(
            r"(?m)(?=^\s*(?:\[[12]\]|[12]\s*[\.\)\:\-–—]|\d+\s*[\.\)\:\-–—])\s*)",
            text,
        )
        numbered_parts = [p.strip() for p in numbered_parts if p.strip()]
        if len(numbered_parts) > 1:
            blocks = numbered_parts
        else:
            sentences = re.split(r"(?<=[.!?…。！？])\s+", text)
            blocks = [s.strip() for s in sentences if s.strip()]

    scenes: list[Scene] = []
    for i, block in enumerate(blocks):
        target, speech = extract_target_and_speech(block)
        if target == POSE_CENTER:
            speech2 = re.sub(r"^\s*\d+\s*[\.\)\:\-–—]\s*", "", block).strip()
            if speech2:
                speech = speech2
        if not speech:
            speech = "..."
        scenes.append(Scene(index=i + 1, text=speech, target=target, raw=block))
    return scenes
