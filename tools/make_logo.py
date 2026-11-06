"""معالجة شعار وأيقونة النظام المعتمدين: إزالة الخلفية وضبط الأحجام."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "brand"
ASSETS = ROOT / "amdh_hr" / "assets"
BG = (248, 246, 239, 255)


def _cut_background(path: Path, tolerance: int = 10) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"تعذّر قراءة الصورة: {path}")
    height, width = image.shape[:2]
    mask = np.zeros((height + 2, width + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    work = image.copy()
    seeds = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    seeds += [(x, 0) for x in range(20, width, max(1, width // 12))]
    seeds += [(x, height - 1) for x in range(20, width, max(1, width // 12))]
    seeds += [(0, y) for y in range(20, height, max(1, height // 12))]
    seeds += [(width - 1, y) for y in range(20, height, max(1, height // 12))]
    for seed in seeds:
        if mask[seed[1] + 1, seed[0] + 1]:
            continue
        cv2.floodFill(work, mask, seed, 0, (tolerance,) * 3, (tolerance,) * 3, flags)
    alpha = np.where(mask[1:-1, 1:-1] > 0, 0, 255).astype(np.uint8)
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return np.dstack([rgb, alpha])


def _trim(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[:, :, 3]
    points = cv2.findNonZero((alpha > 8).astype(np.uint8))
    if points is None:
        raise SystemExit("الصورة فارغة بعد إزالة الخلفية.")
    x, y, width, height = cv2.boundingRect(points)
    return rgba[y:y + height, x:x + width]


def _fit(rgba: np.ndarray, size: int, padding: float = 0.04) -> np.ndarray:
    h, w = rgba.shape[:2]
    inner = int(size * (1 - 2 * padding))
    scale = min(inner / w, inner / h)
    resized = cv2.resize(rgba, (max(1, int(w * scale)), max(1, int(h * scale))),
                         interpolation=cv2.INTER_AREA)
    canvas = np.zeros((size, size, 4), np.uint8)
    x = (size - resized.shape[1]) // 2
    y = (size - resized.shape[0]) // 2
    canvas[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
    return canvas


def _badge(logo: np.ndarray, size: int = 512) -> np.ndarray:
    canvas = np.zeros((size, size, 4), np.uint8)
    radius = int(size * 0.22)
    cv2.rectangle(canvas, (radius, 0), (size - radius, size), BG, -1)
    cv2.rectangle(canvas, (0, radius), (size, size - radius), BG, -1)
    for cx, cy in ((radius, radius), (size - radius, radius),
                   (radius, size - radius), (size - radius, size - radius)):
        cv2.circle(canvas, (cx, cy), radius, BG, -1)
    inner = int(size * 0.74)
    logo = _fit(logo, inner, padding=0.02)
    top = (size - inner) // 2
    left = (size - inner) // 2
    region = canvas[top:top + inner, left:left + inner].astype(np.float32)
    alpha = (logo[:, :, 3:4].astype(np.float32) / 255.0)
    blended = logo.astype(np.float32) * alpha + region * (1.0 - alpha)
    canvas[top:top + inner, left:left + inner] = blended.astype(np.uint8)
    return canvas


def _save(rgba: np.ndarray, path: Path) -> None:
    cv2.imwrite(str(path), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    logo = _fit(_trim(_cut_background(SOURCE / "source_logo.jpg")), 512, padding=0.03)
    icon = _fit(_trim(_cut_background(SOURCE / "source_icon.jpg")), 512, padding=0.01)
    _save(logo, ASSETS / "logo.png")
    _save(_badge(logo, 512), ASSETS / "logo_badge.png")
    _save(_fit(_badge(logo, 512), 128, padding=0), ASSETS / "logo_small.png")
    _save(icon, ASSETS / "app_icon.png")
    from PIL import Image
    Image.open(ASSETS / "app_icon.png").save(
        ASSETS / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("saved", ASSETS / "logo.png", ASSETS / "app_icon.png", ASSETS / "icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
