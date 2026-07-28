from pathlib import Path

from app.config import CHARACTERS_DIR
from app.services.poses import POSE_CENTER, POSE_POINT_1, POSE_POINT_2, detect_target_from_text
from app.services.renderer import _make_compare_frame

OUT = Path(r"a:\AIvideo\data\layout_preview")
OUT.mkdir(parents=True, exist_ok=True)

# Use project images if present
proj = Path(r"a:\AIvideo\data\projects\50aec53d4f87\images")
imgs = sorted(proj.glob("*.jpg")) if proj.exists() else []
left = imgs[0] if imgs else None
right = imgs[1] if len(imgs) > 1 else left

pose_dir = CHARACTERS_DIR / "builtin" / "tuti"
cues = [
    {"text": "Nhìn", "offset": 0.0, "duration": 0.3},
    {"text": "ảnh", "offset": 0.3, "duration": 0.3},
    {"text": "1", "offset": 0.6, "duration": 0.4},
    {"text": "bên", "offset": 1.0, "duration": 0.3},
    {"text": "trái", "offset": 1.3, "duration": 0.4},
]

for name, target, t, text in [
    ("center", POSE_CENTER, 0.2, "So sánh hai ảnh này"),
    ("point1", POSE_POINT_1, 0.7, "Nhìn ảnh 1 bên trái"),
    ("point2", POSE_POINT_2, 0.5, "Còn ảnh 2 bên phải"),
]:
    char = pose_dir / ("point_center.png" if target == POSE_CENTER else "point_1.png" if target == POSE_POINT_1 else "point_2.png")
    frame = _make_compare_frame(
        left, right, cues if name != "center" else [], t, text, char, True, "", True, target, bob=0
    )
    frame.save(OUT / f"{name}.jpg", quality=90)
    print(name, detect_target_from_text(text), "->", OUT / f"{name}.jpg")
