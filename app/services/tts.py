from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from edge_tts.exceptions import NoAudioReceived


# Edge TTS is intermittent: fail fast + retry beats long hangs.
_TTS_ATTEMPT_TIMEOUT = 14.0
_TTS_WORD_TIMEOUT = 8.0
# Keep chunks short — long single requests hang or return no audio
_MAX_CHUNK_CHARS = 220
_DURATION_CACHE: dict[str, float] = {}
_TTS_MAX_TRIES = 6


def _is_busy_file_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        # WinError 32 sharing violation; errno 13/11 on some platforms
        if getattr(exc, "winerror", None) == 32:
            return True
        if exc.errno in {11, 13, 16}:
            return True
    return False


def _safe_unlink(path: Path, *, retries: int = 10, delay: float = 0.12) -> None:
    """Delete a file; retry on Windows 'in use' locks."""
    for i in range(retries):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError as exc:
            if not _is_busy_file_error(exc) or i == retries - 1:
                if path.exists():
                    raise
                return
            time.sleep(delay * (i + 1))


def _safe_replace(src: Path, dest: Path, *, retries: int = 10, delay: float = 0.12) -> None:
    """Atomically move src → dest, retrying WinError 32."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last: OSError | None = None
    for i in range(retries):
        try:
            os.replace(str(src), str(dest))
            return
        except OSError as exc:
            last = exc
            if not _is_busy_file_error(exc):
                raise
            # Prefer deleting the busy dest, then rename
            try:
                _safe_unlink(dest, retries=3, delay=delay)
                os.rename(str(src), str(dest))
                return
            except OSError:
                pass
            # Last resort: overwrite bytes then drop src
            try:
                data = src.read_bytes()
                with open(dest, "wb") as wf:
                    wf.write(data)
                    wf.flush()
                    os.fsync(wf.fileno())
                _safe_unlink(src)
                return
            except OSError:
                time.sleep(delay * (i + 1))
    assert last is not None
    raise last


def _part_path(final_path: Path) -> Path:
    return final_path.with_name(f"{final_path.stem}.{uuid.uuid4().hex[:8]}.part{final_path.suffix}")


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
    key = str(path.resolve())
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    cached = _DURATION_CACHE.get(f"{key}:{mtime}")
    if cached is not None:
        return cached

    # Prefer mutagen when available (much faster than spawning ffmpeg)
    try:
        from mutagen.mp3 import MP3  # type: ignore

        dur = float(MP3(str(path)).info.length)
        if dur > 0.05:
            _DURATION_CACHE[f"{key}:{mtime}"] = dur
            return dur
    except Exception:  # noqa: BLE001
        pass

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg, "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    dur = 2.0
    for line in result.stderr.splitlines():
        if "Duration:" in line:
            part = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = part.split(":")
            dur = int(h) * 3600 + int(m) * 60 + float(s)
            break
    _DURATION_CACHE[f"{key}:{mtime}"] = dur
    return dur


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

    cues: list[dict] = []
    wi = 0
    for s in sentences:
        sent_words = [w for w in re.findall(r"\S+", s.get("text") or "") if w]
        if not sent_words and wi < len(words_all):
            remaining_sents = max(1, len(sentences) - sentences.index(s))
            take = max(1, (len(words_all) - wi + remaining_sents - 1) // remaining_sents)
            sent_words = words_all[wi : wi + take]
        if not sent_words:
            continue
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
    if wi < len(words_all) and cues:
        t = cues[-1]["offset"] + cues[-1]["duration"]
        for w in words_all[wi:]:
            cues.append({"text": w, "offset": t, "duration": 0.12})
            t += 0.12
    return cues


def _split_text_chunks(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Split long scenes so one Edge failure does not sink the whole scene."""
    text = (text or "").strip()
    if not text:
        return ["..."]
    if len(text) <= max_chars:
        return [text]

    parts = re.split(r"(?<=[.!?…。！？])\s+", text)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not buf:
            buf = part
        elif len(buf) + 1 + len(part) <= max_chars:
            buf = f"{buf} {part}"
        else:
            chunks.append(buf)
            buf = part
    if buf:
        chunks.append(buf)

    # Hard-split any leftover oversized chunk by words
    out: list[str] = []
    for ch in chunks:
        if len(ch) <= max_chars:
            out.append(ch)
            continue
        words = ch.split()
        buf = ""
        for w in words:
            trial = f"{buf} {w}".strip()
            if len(trial) <= max_chars:
                buf = trial
            else:
                if buf:
                    out.append(buf)
                buf = w
        if buf:
            out.append(buf)
    return out or [text[:max_chars]]


def _concat_mp3(parts: list[Path], out_path: Path) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    if len(parts) == 1:
        tmp = _part_path(out_path)
        tmp.write_bytes(parts[0].read_bytes())
        _safe_replace(tmp, out_path)
        return
    with tempfile.TemporaryDirectory() as tmpdir:
        list_path = Path(tmpdir) / "concat.txt"
        tmp_out = Path(tmpdir) / "out.mp3"
        lines = []
        for p in parts:
            safe = str(p.resolve()).replace("'", r"'\''")
            lines.append(f"file '{safe}'")
        list_path.write_text("\n".join(lines), encoding="utf-8")
        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(tmp_out),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not tmp_out.exists() or tmp_out.stat().st_size < 100:
            cmd2 = [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c:a",
                "libmp3lame",
                "-q:a",
                "4",
                str(tmp_out),
            ]
            result2 = subprocess.run(cmd2, capture_output=True, text=True)
            if result2.returncode != 0 or not tmp_out.exists():
                err = (result2.stderr or result.stderr or "")[-800:]
                raise RuntimeError(f"FFmpeg concat voice failed:\n{err}")
        staging = _part_path(out_path)
        staging.write_bytes(tmp_out.read_bytes())
        _safe_replace(staging, out_path)

def _cache_key(text: str, edge_voice: str, rate: str, pitch: str) -> str:
    raw = f"{edge_voice}|{rate}|{pitch}|{text}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _load_cached(audio_path: Path, cache_key: str) -> list[dict] | None:
    meta_path = audio_path.with_suffix(".tts.json")
    cues_path = audio_path.with_suffix(".cues.json")
    if audio_path.exists() and audio_path.stat().st_size >= 200 and meta_path.exists() and cues_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("key") == cache_key:
                cues = json.loads(cues_path.read_text(encoding="utf-8"))
                if isinstance(cues, list):
                    return cues
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    # Reuse identical TTS from another scene file (common with 2+ kịch bản)
    audio_dir = audio_path.parent
    if not audio_dir.is_dir():
        return None
    for meta in audio_dir.glob("scene_*.tts.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if data.get("key") != cache_key:
            continue
        src_mp3 = audio_dir / meta.name.replace(".tts.json", ".mp3")
        src_cues = audio_dir / meta.name.replace(".tts.json", ".cues.json")
        if src_mp3.resolve() == audio_path.resolve():
            continue
        if not src_mp3.exists() or src_mp3.stat().st_size < 200 or not src_cues.exists():
            continue
        try:
            cues = json.loads(src_cues.read_text(encoding="utf-8"))
            if not isinstance(cues, list):
                continue
            tmp = _part_path(audio_path)
            tmp.write_bytes(src_mp3.read_bytes())
            _safe_replace(tmp, audio_path)
            _save_cache(audio_path, cache_key, cues, str(data.get("voice") or ""))
            return cues
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return None


def _save_cache(audio_path: Path, cache_key: str, cues: list[dict], voice_id: str) -> None:
    meta_path = audio_path.with_suffix(".tts.json")
    cues_path = audio_path.with_suffix(".cues.json")
    cues_path.write_text(json.dumps(cues, ensure_ascii=False, indent=2), encoding="utf-8")
    meta_path.write_text(
        json.dumps({"key": cache_key, "voice": voice_id}, ensure_ascii=False),
        encoding="utf-8",
    )


async def _edge_stream(
    text: str,
    voice: str,
    audio_path: Path,
    *,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    boundary: str = "SentenceBoundary",
    timeout: float | None = None,
) -> list[dict]:
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch or "+0Hz",
        boundary=boundary,  # type: ignore[arg-type]
        connect_timeout=8,
        receive_timeout=20,
    )
    word_cues: list[dict] = []
    sentence_cues: list[dict] = []
    audio_bytes = 0
    # Always write to a unique temp file — avoids WinError 32 on locked finals
    part = _part_path(audio_path)
    attempt_timeout = float(
        timeout
        if timeout is not None
        else (
            _TTS_WORD_TIMEOUT
            if boundary == "WordBoundary"
            else _TTS_ATTEMPT_TIMEOUT
        )
    )

    async def _consume() -> None:
        nonlocal audio_bytes
        with open(part, "wb") as audio_file:
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

    try:
        try:
            await asyncio.wait_for(_consume(), timeout=attempt_timeout)
        except asyncio.TimeoutError as exc:
            # Let file handle close before cleanup
            await asyncio.sleep(0.05)
            _safe_unlink(part)
            raise TimeoutError(
                f"Edge TTS timeout after {attempt_timeout:.0f}s "
                f"(voice={voice}, boundary={boundary})."
            ) from exc
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)
            _safe_unlink(part)
            raise

        if audio_bytes < 200:
            _safe_unlink(part)
            raise NoAudioReceived(
                "No audio was received. Please verify that your parameters are correct."
            )

        _safe_replace(part, audio_path)
    finally:
        # Leftover part from failed replace
        if part.exists() and part.resolve() != audio_path.resolve():
            _safe_unlink(part)

    duration = _audio_duration_ffprobe(audio_path)
    expected_words = max(1, len(re.findall(r"\S+", text)))
    if word_cues and len(word_cues) >= max(2, expected_words // 2):
        return _scale_cues(_align_cue_text(word_cues, text), duration)
    if sentence_cues:
        cues = _cues_from_sentences(sentence_cues, text)
        if cues:
            return _scale_cues(cues, duration)
    return _estimate_cues(text, duration)


async def _edge_save_fallback(
    text: str,
    voice: str,
    audio_path: Path,
    *,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> list[dict]:
    """Reliable path: Communicate.save() — no WordBoundary stream hang."""
    part = _part_path(audio_path)
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch or "+0Hz",
        boundary="SentenceBoundary",
        connect_timeout=8,
        receive_timeout=20,
    )
    try:
        await asyncio.wait_for(communicate.save(str(part)), timeout=_TTS_ATTEMPT_TIMEOUT)
    except asyncio.TimeoutError as exc:
        _safe_unlink(part)
        raise TimeoutError(
            f"Edge TTS save() timeout after {_TTS_ATTEMPT_TIMEOUT:.0f}s (voice={voice})."
        ) from exc
    if not part.exists() or part.stat().st_size < 200:
        _safe_unlink(part)
        raise NoAudioReceived(
            "No audio was received. Please verify that your parameters are correct."
        )
    _safe_replace(part, audio_path)
    duration = _audio_duration_ffprobe(audio_path)
    return _estimate_cues(text, duration)

def _pitch_variants(pitch: str) -> list[str]:
    """Same voice, progressively safer pitch values."""
    variants = [pitch or "+0Hz", "+0Hz"]
    m = re.fullmatch(r"([+-]?)(\d+)Hz", (pitch or "+0Hz").strip())
    if m:
        sign = -1 if m.group(1) == "-" else 1
        hz = int(m.group(2)) * sign
        if abs(hz) > 4:
            mid = int(round(hz * 0.45))
            variants.insert(1, f"{mid:+d}Hz")
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _rate_variants(rate: str) -> list[str]:
    variants = [rate or "+0%", "+0%"]
    m = re.fullmatch(r"([+-]?)(\d+)%", (rate or "+0%").strip())
    if m:
        sign = -1 if m.group(1) == "-" else 1
        pct = int(m.group(2)) * sign
        if abs(pct) > 8:
            mid = int(round(pct * 0.5))
            variants.insert(1, f"{mid:+d}%")
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


async def _edge_with_retries(
    text: str,
    voice: str,
    audio_path: Path,
    *,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> tuple[list[dict], str, str]:
    """
    Fail-fast save() retries. Edge often hangs randomly; short timeout + retry
    recovers faster than waiting 30s. Same speaker only.
    """
    last_exc: Exception | None = None
    variants: list[tuple[str, str]] = [
        (pitch or "+0Hz", rate or "+0%"),
        ("+0Hz", rate or "+0%"),
        ("+0Hz", "+0%"),
    ]
    for attempt in range(_TTS_MAX_TRIES):
        p, r = variants[min(attempt, len(variants) - 1)]
        try:
            cues = await _edge_save_fallback(
                text, voice, audio_path, rate=r, pitch=p
            )
            return cues, r, p
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            # Brief pause — Edge recovers quickly between hung sockets
            await asyncio.sleep(0.4 + attempt * 0.35)
    assert last_exc is not None
    raise last_exc


async def _synthesize_chunked(
    text: str,
    edge_voice: str,
    audio_path: Path,
    *,
    rate: str,
    pitch: str,
) -> list[dict]:
    """Always split long scenes into short chunks — Edge hangs on big requests."""
    chunks = _split_text_chunks(text, max_chars=_MAX_CHUNK_CHARS)
    if not chunks:
        chunks = ["..."]

    if len(chunks) == 1:
        cues, _, _ = await _edge_with_retries(
            chunks[0], edge_voice, audio_path, rate=rate, pitch=pitch
        )
        return cues

    part_files: list[Path] = []
    all_cues: list[dict] = []
    offset = 0.0
    try:
        for i, chunk in enumerate(chunks):
            part = audio_path.with_name(f"{audio_path.stem}.p{i}.{uuid.uuid4().hex[:6]}.mp3")
            if i > 0:
                await asyncio.sleep(0.55)
            # Per-chunk retries already inside _edge_with_retries
            cues, _, _ = await _edge_with_retries(
                chunk, edge_voice, part, rate=rate, pitch=pitch
            )
            part_files.append(part)
            for c in cues:
                all_cues.append(
                    {
                        "text": c["text"],
                        "offset": float(c["offset"]) + offset,
                        "duration": float(c["duration"]),
                    }
                )
            offset += max(_audio_duration_ffprobe(part), 0.15)
        _concat_mp3(part_files, audio_path)
        duration = _audio_duration_ffprobe(audio_path)
        return _scale_cues(all_cues, duration)
    finally:
        for p in part_files:
            _safe_unlink(p)

async def synthesize(
    text: str, voice: str, out_path: Path, *, speed: float = 1.0
) -> Path:
    audio_path, _, _, _ = await synthesize_with_subtitles(
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
) -> tuple[Path, Path, list[dict], bool]:
    """Generate audio with selected voice only + synced word cues.

    Returns (audio, vtt, cues, from_cache).
    """
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
    # Edge often rejects / hangs on extreme rate with Vietnamese long text
    effective_speed = round(max(0.85, min(1.15, effective_speed)), 2)
    rate = speed_to_edge_rate(effective_speed)
    cache_key = _cache_key(text, str(edge_voice), rate, pitch)

    cached = _load_cached(audio_path, cache_key)
    if cached is not None:
        _write_vtt(cached, text, vtt_path)
        return audio_path, vtt_path, cached, True

    try:
        cues = await _synthesize_chunked(
            text, str(edge_voice), audio_path, rate=rate, pitch=pitch
        )
    except Exception as edge_exc:
        raise RuntimeError(
            f"Không tạo được giọng đọc với đúng giọng đã chọn ({voice}).\n"
            f"{edge_exc}\n"
            "Nguyên nhân thường gặp: dịch vụ Edge TTS (Microsoft) treo/chặn tạm thời "
            "hoặc đoạn thoại quá dài trong 1 request — app đã tách câu ngắn + thử lại.\n"
            "Đợi 10–20 giây rồi Render lại. App không đổi sang giọng khác."
        ) from edge_exc

    _save_cache(audio_path, cache_key, cues, voice)
    _write_vtt(cues, text, vtt_path)
    return audio_path, vtt_path, cues, False


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
