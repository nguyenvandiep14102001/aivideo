"""Re-import TuTi sprite sheet with sharp transparent pipeline."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.services.sprites_split import split_pose_sheet

SRC = Path(
    r"C:\Users\DIEPNV\.cursor\projects\a-AIvideo\assets"
    r"\c__Users_DIEPNV_AppData_Roaming_Cursor_User_workspaceStorage_"
    r"89d541a21c5a1403947fc29f7a303b45_images_tutifinal-12d86bf8-f519-44ca-9e9d-5382b2591e34.png"
)
OUT = Path(r"a:\AIvideo\data\characters\builtin\tuti")

NAMES = [
    "point_left",
    "point_right",
    "center",
    "point_left_smile",
    "point_right_b",
]


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Missing source: {SRC}")
    OUT.mkdir(parents=True, exist_ok=True)
    im = Image.open(SRC)
    split_pose_sheet(im, OUT, NAMES, skip_rembg=True)
    Image.open(OUT / "point_left_smile.png").save(OUT / "point_1.png", compress_level=1)
    Image.open(OUT / "point_right.png").save(OUT / "point_2.png", compress_level=1)
    Image.open(OUT / "center.png").save(OUT / "point_center.png", compress_level=1)
    preview = Image.open(OUT / "center.png").copy()
    preview.thumbnail((400, 520), Image.Resampling.LANCZOS)
    preview.save(OUT / "preview.png", compress_level=1)
    print("done", OUT)


if __name__ == "__main__":
    main()
