"""توليد أيقونات صغيرة (أسهم الحقول وعلامة الاختيار) مرة واحدة."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "amdh_hr" / "assets"


def chevron(name: str, up: bool, color=(148, 163, 184)) -> None:
    image = Image.new("RGBA", (18, 12), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    points = [(2, 9), (9, 2), (16, 9)] if up else [(2, 3), (9, 10), (16, 3)]
    draw.line(points, fill=color + (255,), width=3, joint="curve")
    image.save(ASSETS / name)


def check() -> None:
    image = Image.new("RGBA", (20, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.line([(3, 8), (8, 13), (17, 2)], fill=(255, 255, 255, 255), width=3,
              joint="curve")
    image.save(ASSETS / "check.png")


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    chevron("chevron_up.png", True)
    chevron("chevron_down.png", False)
    check()
    print("assets:", [p.name for p in sorted(ASSETS.iterdir())])


if __name__ == "__main__":
    main()
