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
VIDEO_FPS = 30

DEFAULT_VOICE = "vi-VN-HoaiMyNeural"
VOICES = [
    {"id": "vi-VN-HoaiMyNeural", "label": "Hoài My (nữ)"},
    {"id": "vi-VN-NamMinhNeural", "label": "Nam Minh (nam)"},
    {"id": "en-US-JennyNeural", "label": "Jenny (EN female)"},
    {"id": "en-US-GuyNeural", "label": "Guy (EN male)"},
]

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
