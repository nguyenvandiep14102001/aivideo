from __future__ import annotations

import asyncio
import json
import re
import subprocess
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from edge_tts.exceptions import NoAudioReceived


def speed_to_edge_rate(speed: float) -> str:
    """Map playback speed (0.7..1.5) to Edge TTS rate string like +20% / -15%."""
    try:
        s = float(speed)
    except (TypeError, ValueError):
        s = 1.0
    s = max(0.7, min(1.5, s))
    pct = int(round((s - 1.0) * 100))
    return f"{pct:+d}%"


def normalize_speed(speed: float | str | None) -> float:
    try:
        s = float(speed)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        s = 1.0
    return round(max(0.7, min(1.5, s)), 2)


def _sanitize_text(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if not re.search(r"[\w\u00C0-\u024F\u1E00-\u1EFF]", t, re.UNICODE):
        return "..."
    return t


def _word_weight(word: str) -> float:
    # Vietnamese: weight by letters (better than equal slots)
    letters = re.findall(r"[\w\u00C0-\u024F\u1E00-\u1EFF]", word, re.UNICODE)
    return max(1.0, float(len(letters)))


def _estimate_cues(text: str, duration: float) -> list[dict]:
    words = [w for w in re.findall(r"\S+", text) if w]
    if not words:
        return [{"text": text or "...", "offset": 0.0, "duration": max(duration, 0.4)}]
    weights = [_word_weight(w) for w in words]
    total_w = sum(weights) or 1.0
    usable = max(duration * 0.96, 0.4)
    cues = []
    t = 0.0
    for w, wt in zip(words, weights):
        slot = usable * (wt / total_w)
        cues.append({"text": w, "offset": t, "duration": max(0.05, slot * 0.95)})
        t += slot
    return _scale_cues(cues, duration)


def _scale_cues(cues: list[dict], audio_duration: float) -> list[dict]:
    if not cues or audio_duration <= 0:
        return cues
    end = cues[-1]["offset"] + max(cues[-1]["duration"], 0.01)
    if end <= 0.01:
        return cues
    # WordBoundary from Edge is usually already correct — only rescale if drift is large
    if abs(end - audio_duration) / max(audio_duration, 0.01) < 0.06:
        return cues
    target = max(0.2, audio_duration * 0.985)
    scale = target / end
    out = []
    for c in cues:
        out.append(
            {
                "text": c["text"],
                "offset": max(0.0, c["offset"] * scale),
                "duration": max(0.04, c["duration"] * scale),
            }
        )
    return out


def _align_cue_text(cues: list[dict], full_text: str) -> list[dict]:
    """Prefer script spelling when Edge word count matches."""
    words = [w for w in re.findall(r"\S+", full_text) if w]
    if not cues or not words:
        return cues
    if len(cues) == len(words):
        return [
            {"text": w, "offset": c["offset"], "duration": c["duration"]}
            for c, w in zip(cues, words)
        ]
    return cues


def _audio_duration_ffprobe(path: Path) -> float:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg, "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    for line in result.stderr.splitlines():
        if "Duration:" in line:
            part = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = part.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 2.0


def _cues_from_sentences(sentences: list[dict], full_text: str) -> list[dict]:
    """Distribute words inside each SentenceBoundary by character weight."""
    words_all = [w for w in re.findall(r"\S+", full_text) if w]
    if not sentences:
        return []
    if not words_all:
        return [
            {
                "text": s.get("text", ""),
                "offset": s["offset"],
                "duration": max(0.1, s["duration"]),
            }
            for s in sentences
        ]

    # Assign words to sentences in order
    cues: list[dict] = []
    wi = 0
    for s in sentences:
        sent_words = [w for w in re.findall(r"\S+", s.get("text") or "") if w]
        if not sent_words and wi < len(words_all):
            # fallback: take remaining proportionally
            remaining_sents = max(1, len(sentences) - sentences.index(s))
            take = max(1, (len(words_all) - wi + remaining_sents - 1) // remaining_sents)
            sent_words = words_all[wi : wi + take]
        # If sentence text empty, still advance using count estimate
        if not sent_words:
            continue
        # Prefer matching from global word list for consistency
        n = len(sent_words)
        chunk = words_all[wi : wi + n] or sent_words
        wi += len(chunk)
        weights = [_word_weight(w) for w in chunk]
        total_w = sum(weights) or 1.0
        t0 = s["offset"]
        dur = max(0.12, s["duration"])
        t = t0
        for w, wt in zip(chunk, weights):
            slot = dur * (wt / total_w)
            cues.append({"text": w, "offset": t, "duration": max(0.05, slot * 0.92)})
            t += slot
    # leftover words
    if wi < len(words_all) and cues:
        t = cues[-1]["offset"] + cues[-1]["duration"]
        for w in words_all[wi:]:
            cues.append({"text": w, "offset": t, "duration": 0.12})
            t += 0.12
    return cues


async def _edge_stream(
    text: str,
    voice: str,
    audio_path: Path,
    *,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> list[dict]:
    # WordBoundary is required for karaoke sync (default is SentenceBoundary only)
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch or "+0Hz",
        boundary="WordBoundary",
    )
    word_cues: list[dict] = []
    sentence_cues: list[dict] = []
    audio_bytes = 0
    with open(audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
                audio_bytes += len(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_cues.append(
                    {
                        "text": chunk["text"],
                        "offset": chunk["offset"] / 10_000_000,
                        "duration": max(0.04, chunk["duration"] / 10_000_000),
                    }
                )
            elif chunk["type"] == "SentenceBoundary":
                sentence_cues.append(
                    {
                        "text": chunk.get("text") or "",
                        "offset": chunk["offset"] / 10_000_000,
                        "duration": max(0.1, chunk["duration"] / 10_000_000),
                    }
                )
    if audio_bytes < 200:
        raise NoAudioReceived(
            "No audio was received. Please verify that your parameters are correct."
        )

    duration = _audio_duration_ffprobe(audio_path)
    expected_words = max(1, len(re.findall(r"\S+", text)))
    if word_cues and len(word_cues) >= max(2, expected_words // 2):
        return _scale_cues(_align_cue_text(word_cues, text), duration)
    if sentence_cues:
        cues = _cues_from_sentences(sentence_cues, text)
        if cues:
            return _scale_cues(cues, duration)
    return _estimate_cues(text, duration)


async def _edge_with_retries(
    text: str,
    voice: str,
    audio_path: Path,
    *,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> list[dict]:
    last_exc: Exception | None = None
    for attempt in range(6):
        try:
            if audio_path.exists():
                audio_path.unlink()
            return await _edge_stream(
                text, voice, audio_path, rate=rate, pitch=pitch
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            await asyncio.sleep(0.8 + attempt * 0.6)
    assert last_exc is not None
    raise last_exc


async def synthesize(
    text: str, voice: str, out_path: Path, *, speed: float = 1.0
) -> Path:
    audio_path, _, _ = await synthesize_with_subtitles(
        text, voice, out_path, out_path.with_suffix(".vtt"), speed=speed
    )
    return audio_path


async def synthesize_with_subtitles(
    text: str,
    voice: str,
    audio_path: Path,
    vtt_path: Path,
    *,
    speed: float = 1.0,
) -> tuple[Path, Path, list[dict]]:
    """Generate audio with selected voice only + synced word cues."""
    from app.config import resolve_voice

    text = _sanitize_text(text)
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    profile = resolve_voice(voice)
    edge_voice = profile.get("edge_voice") or voice
    pitch = str(profile.get("pitch") or "+0Hz")
    try:
        bias = float(profile.get("rate_bias") or 0.0)
    except (TypeError, ValueError):
        bias = 0.0
    effective_speed = normalize_speed(normalize_speed(speed) + bias)
    rate = speed_to_edge_rate(effective_speed)

    try:
        cues = await _edge_with_retries(
            text, edge_voice, audio_path, rate=rate, pitch=pitch
        )
    except Exception as edge_exc:
        raise RuntimeError(
            f"Không tạo được giọng đọc với đúng giọng đã chọn ({voice}).\n"
            f"{edge_exc}\n"
            "Thử lại sau vài giây hoặc kiểm tra mạng. App không đổi sang giọng khác."
        ) from edge_exc

    # Persist cues next to audio for debugging / reuse
    cues_path = audio_path.with_suffix(".cues.json")
    cues_path.write_text(json.dumps(cues, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_vtt(cues, text, vtt_path)
    return audio_path, vtt_path, cues


def _write_vtt(cues: list[dict], full_text: str, vtt_path: Path) -> None:
    lines = ["WEBVTT", ""]
    if cues:
        group: list[dict] = []
        for cue in cues:
            group.append(cue)
            if len(group) >= 6 or str(cue["text"]).endswith((".", "!", "?", "…")):
                start = group[0]["offset"]
                end = group[-1]["offset"] + group[-1]["duration"]
                text = " ".join(str(c["text"]) for c in group)
                lines.append(f"{_ts(start)} --> {_ts(end)}")
                lines.append(text)
                lines.append("")
                group = []
        if group:
            start = group[0]["offset"]
            end = group[-1]["offset"] + group[-1]["duration"]
            text = " ".join(str(c["text"]) for c in group)
            lines.append(f"{_ts(start)} --> {_ts(end)}")
            lines.append(text)
            lines.append("")
    else:
        lines.append("00:00:00.000 --> 00:00:05.000")
        lines.append(full_text)
        lines.append("")
    vtt_path.write_text("\n".join(lines), encoding="utf-8")


def _ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{milli:03d}"
