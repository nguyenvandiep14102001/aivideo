import asyncio
import sys
from pathlib import Path

import edge_tts

OUT = Path(r"a:\AIvideo\data\tts_test_log.txt")


async def test(voice: str, text: str) -> str:
    try:
        communicate = edge_tts.Communicate(text=text, voice=voice)
        n = 0
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                n += len(chunk["data"])
        if n < 100:
            return f"FAIL {voice}: no/low audio bytes={n}"
        return f"OK {voice}: bytes={n}"
    except Exception as exc:
        return f"FAIL {voice}: {type(exc).__name__}: {exc}"


async def main() -> None:
    lines = []
    voices = await edge_tts.list_voices()
    vi = [v["ShortName"] for v in voices if v["ShortName"].startswith("vi-")]
    lines.append("vi voices: " + ", ".join(vi))

    sample = "Xin chao, day la kiem tra giong doc."
    sample_vi = "Xin chào, đây là kiểm tra giọng đọc số một."
    project_line = "Bạn có phân biệt được rắn cạp long và rắn cạp nia không?"

    for voice in ["vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural", "en-US-JennyNeural"]:
        for text in [sample, sample_vi, project_line]:
            lines.append(await test(voice, text))
            await asyncio.sleep(0.8)

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    asyncio.run(main())
