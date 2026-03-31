from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import fitz  # PyMuPDF
from PIL import Image


@dataclass(frozen=True)
class PageImage:
    image: Image.Image  # RGB
    page_rect: fitz.Rect

    @property
    def sx(self) -> float:
        return self.image.width / float(self.page_rect.width)

    @property
    def sy(self) -> float:
        return self.image.height / float(self.page_rect.height)


def render_page_image(page: fitz.Page, *, dpi: int = 150) -> PageImage:
    pix = page.get_pixmap(dpi=dpi)
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)
    img_bytes = pix.tobytes("png")
    img = Image.open(BytesIO(img_bytes)).convert("RGB")
    return PageImage(image=img, page_rect=page.rect)


def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


def sample_background_rgb(page_img: PageImage, rect: fitz.Rect) -> tuple[int, int, int]:
    """Sample background color under rect using a small grid of points."""
    img = page_img.image
    pr = page_img.page_rect

    r = rect & pr
    if r.is_empty:
        return (255, 255, 255)

    # sample slightly inset to avoid text strokes
    inset_x = max(1.0, r.width * 0.08)
    inset_y = max(1.0, r.height * 0.12)
    x0 = r.x0 + inset_x
    x1 = r.x1 - inset_x
    y0 = r.y0 + inset_y
    y1 = r.y1 - inset_y
    if x1 <= x0 or y1 <= y0:
        x0, x1, y0, y1 = r.x0, r.x1, r.y0, r.y1

    # grid points (3x3)
    xs = [x0, (x0 + x1) / 2, x1]
    ys = [y0, (y0 + y1) / 2, y1]

    rs: list[int] = []
    gs: list[int] = []
    bs: list[int] = []

    for x in xs:
        for y in ys:
            px = int(round((x - pr.x0) * page_img.sx))
            py = int(round((y - pr.y0) * page_img.sy))
            px = _clamp(px, 0, img.width - 1)
            py = _clamp(py, 0, img.height - 1)
            rr, gg, bb = img.getpixel((px, py))
            rs.append(int(rr))
            gs.append(int(gg))
            bs.append(int(bb))

    # Use median for robustness
    rs.sort()
    gs.sort()
    bs.sort()
    mid = len(rs) // 2
    return rs[mid], gs[mid], bs[mid]


def pick_text_rgb(bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b = bg_rgb
    # perceived luminance
    lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return (255, 255, 255) if lum < 0.5 else (0, 0, 0)


def rgb255_to_float(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = rgb
    return (r / 255.0, g / 255.0, b / 255.0)

