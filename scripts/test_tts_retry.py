import asyncio
from pathlib import Path

from app.services.tts import synthesize_with_subtitles

TEXT = "Bạn có phân biệt được rắn cạp long và rắn cạp nia không? Chúng nhìn khá giống nhau nên rất nhiều người dễ nhầm."
OUT = Path(r"a:\AIvideo\data\tts_retry_test.mp3")
VTT = Path(r"a:\AIvideo\data\tts_retry_test.vtt")
LOG = Path(r"a:\AIvideo\data\tts_retry_log.txt")


async def main() -> None:
    lines = []
    for voice in ["vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"]:
        try:
            path, _, cues, _ = await synthesize_with_subtitles(TEXT, voice, OUT, VTT)
            lines.append(f"OK {voice} -> {path} size={path.stat().st_size} cues={len(cues)}")
        except Exception as exc:
            lines.append(f"FAIL {voice}: {exc}")
    LOG.write_text("\n".join(lines), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
