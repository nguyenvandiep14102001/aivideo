from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROJECTS_DIR = DATA_DIR / "projects"
CHARACTERS_DIR = DATA_DIR / "characters"
SFX_DIR = DATA_DIR / "sfx"
STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 24  # default balanced; project can override 20/24/30

DEFAULT_VOICE = "vi-VN-HoaiMyNeural"
# edge_voice = real Edge TTS id; pitch / rate_bias customize delivery
# Note: Edge only has 2 native Vietnamese voices (Hoài My / Nam Minh).
# Multilingual male voices can read Vietnamese with a foreign accent but often
# handle tricky words (béo/báo…) differently — useful as alternatives.
VOICES = [
    {
        "id": "vi-VN-HoaiMyNeural",
        "label": "Hoài My (nữ · Việt)",
        "edge_voice": "vi-VN-HoaiMyNeural",
        "pitch": "+0Hz",
        "rate_bias": 0.0,
    },
    {
        "id": "vi-VN-NamMinhNeural",
        "label": "Nam Minh (nam · Việt)",
        "edge_voice": "vi-VN-NamMinhNeural",
        "pitch": "+0Hz",
        "rate_bias": 0.0,
    },
    {
        "id": "vi-VN-NamMinh-Express",
        "label": "Nam Minh truyền cảm (nhấn nhá)",
        "edge_voice": "vi-VN-NamMinhNeural",
        # Keep mild — strong pitch/rate often makes Edge return no audio on long scenes
        "pitch": "+2Hz",
        "rate_bias": -0.03,
    },
    {
        "id": "vi-VN-NamMinh-Deep",
        "label": "Nam Minh trầm (nam · trầm hơn)",
        "edge_voice": "vi-VN-NamMinhNeural",
        "pitch": "-8Hz",
        "rate_bias": -0.02,
    },
    {
        "id": "en-US-BrianMultilingualNeural",
        "label": "Brian (nam · Mỹ đa ngữ · ấm)",
        "edge_voice": "en-US-BrianMultilingualNeural",
        "pitch": "+2Hz",
        "rate_bias": -0.04,
    },
    {
        "id": "en-US-AndrewMultilingualNeural",
        "label": "Andrew (nam · Mỹ đa ngữ · truyền cảm)",
        "edge_voice": "en-US-AndrewMultilingualNeural",
        "pitch": "+6Hz",
        "rate_bias": -0.05,
    },
    {
        "id": "en-AU-WilliamMultilingualNeural",
        "label": "William (nam · Úc đa ngữ)",
        "edge_voice": "en-AU-WilliamMultilingualNeural",
        "pitch": "+0Hz",
        "rate_bias": -0.03,
    },
    {
        "id": "fr-FR-RemyMultilingualNeural",
        "label": "Rémy (nam · Pháp đa ngữ)",
        "edge_voice": "fr-FR-RemyMultilingualNeural",
        "pitch": "+0Hz",
        "rate_bias": -0.03,
    },
    {
        "id": "de-DE-FlorianMultilingualNeural",
        "label": "Florian (nam · Đức đa ngữ)",
        "edge_voice": "de-DE-FlorianMultilingualNeural",
        "pitch": "-2Hz",
        "rate_bias": -0.03,
    },
    {
        "id": "it-IT-GiuseppeMultilingualNeural",
        "label": "Giuseppe (nam · Ý đa ngữ)",
        "edge_voice": "it-IT-GiuseppeMultilingualNeural",
        "pitch": "+0Hz",
        "rate_bias": -0.03,
    },
    {
        "id": "ko-KR-HyunsuMultilingualNeural",
        "label": "Hyunsu (nam · Hàn đa ngữ)",
        "edge_voice": "ko-KR-HyunsuMultilingualNeural",
        "pitch": "+0Hz",
        "rate_bias": -0.03,
    },
    {
        "id": "en-US-JennyNeural",
        "label": "Jenny (nữ · tiếng Anh)",
        "edge_voice": "en-US-JennyNeural",
        "pitch": "+0Hz",
        "rate_bias": 0.0,
    },
    {
        "id": "en-US-GuyNeural",
        "label": "Guy (nam · tiếng Anh)",
        "edge_voice": "en-US-GuyNeural",
        "pitch": "+0Hz",
        "rate_bias": 0.0,
    },
]


def resolve_voice(voice_id: str | None) -> dict:
    """Map UI voice id → Edge TTS settings."""
    vid = (voice_id or DEFAULT_VOICE).strip()
    for v in VOICES:
        if v["id"] == vid:
            return dict(v)
    return {
        "id": vid,
        "label": vid,
        "edge_voice": vid,
        "pitch": "+0Hz",
        "rate_bias": 0.0,
    }


CHARACTER_POSITIONS = [
    {"id": "left", "label": "Trái"},
    {"id": "right", "label": "Phải"},
    {"id": "center", "label": "Giữa (nhỏ)"},
    {"id": "hidden", "label": "Ẩn nhân vật"},
]


def ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    (CHARACTERS_DIR / "custom").mkdir(parents=True, exist_ok=True)
    SFX_DIR.mkdir(parents=True, exist_ok=True)
