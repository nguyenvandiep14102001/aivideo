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
VOICES = [
    {
        "id": "vi-VN-HoaiMyNeural",
        "label": "Hoài My (nữ)",
        "edge_voice": "vi-VN-HoaiMyNeural",
        "pitch": "+0Hz",
        "rate_bias": 0.0,
    },
    {
        "id": "vi-VN-NamMinhNeural",
        "label": "Nam Minh (nam)",
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
        "id": "en-US-BrianMultilingualNeural",
        "label": "Brian (nam đa ngữ · ấm)",
        "edge_voice": "en-US-BrianMultilingualNeural",
        "pitch": "+2Hz",
        "rate_bias": -0.04,
    },
    {
        "id": "en-US-AndrewMultilingualNeural",
        "label": "Andrew (nam đa ngữ · truyền cảm)",
        "edge_voice": "en-US-AndrewMultilingualNeural",
        "pitch": "+6Hz",
        "rate_bias": -0.05,
    },
    {
        "id": "en-US-JennyNeural",
        "label": "Jenny (EN female)",
        "edge_voice": "en-US-JennyNeural",
        "pitch": "+0Hz",
        "rate_bias": 0.0,
    },
    {
        "id": "en-US-GuyNeural",
        "label": "Guy (EN male)",
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
