from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.poses import (
    POSE_CENTER,
    extract_target_and_speech,
)


@dataclass
class Scene:
    index: int
    text: str  # spoken (markers stripped)
    target: str = POSE_CENTER
    raw: str = ""
    segment: int = 1  # 1-based script part split by #


_HASH_SPLIT = re.compile(r"(?m)^\s*#\s*$")


def split_script_segments(script: str) -> list[str]:
    """
    Split major scripts by a lone '#' line.
    Example:
      kịch bản 1
      #
      kịch bản 2
    """
    text = (script or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    parts = [p.strip() for p in _HASH_SPLIT.split(text) if p.strip()]
    return parts or ([text] if text else [])


def _parse_blocks_legacy(text: str) -> list[str]:
    """Old scene splitting: blank lines → numbered headers → sentences."""
    text = (text or "").strip()
    if not text:
        return []

    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]

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
    return blocks


def parse_script(script: str) -> list[Scene]:
    """
    '#' on its own line splits major scripts (image pairs).
    Inside each part, keep the old scene logic (blank lines / 1. / 2. / sentences).
    """
    segments = split_script_segments(script)
    if not segments:
        return []

    scenes: list[Scene] = []
    global_idx = 0
    for seg_i, seg_text in enumerate(segments):
        for block in _parse_blocks_legacy(seg_text):
            target, speech = extract_target_and_speech(block)
            if target == POSE_CENTER:
                speech2 = re.sub(r"^\s*\d+\s*[\.\)\:\-–—]\s*", "", block).strip()
                if speech2:
                    speech = speech2
            if not speech:
                continue
            # Skip separator leftovers like #### or lone hashes
            if re.fullmatch(r"#+\s*", speech):
                continue
            global_idx += 1
            scenes.append(
                Scene(
                    index=global_idx,
                    text=speech,
                    target=target,
                    raw=block,
                    segment=seg_i + 1,
                )
            )
    return scenes


def list_script_segments(script: str) -> list[dict]:
    """UI helper: one entry per '#'-separated script with nested scenes."""
    segments = split_script_segments(script)
    out: list[dict] = []
    for seg_i, seg_text in enumerate(segments):
        local_scenes = []
        for j, block in enumerate(_parse_blocks_legacy(seg_text)):
            target, speech = extract_target_and_speech(block)
            if target == POSE_CENTER:
                speech2 = re.sub(r"^\s*\d+\s*[\.\)\:\-–—]\s*", "", block).strip()
                if speech2:
                    speech = speech2
            if not speech:
                speech = "..."
            local_scenes.append(
                {
                    "index": j + 1,
                    "text": speech,
                    "target": target,
                }
            )
        out.append(
            {
                "index": seg_i + 1,
                "raw": seg_text,
                "scenes": local_scenes,
            }
        )
    return out
