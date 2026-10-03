"""PaddleOCR wrapper -> list[OcrToken] (text, confidence, box in source-image pixels).

Shared by the order-image extraction and by the UI layer, which OCRs screenshots of
NatTable grids that expose no rows to UI Automation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


@dataclass(frozen=True)
class OcrToken:
    text: str
    conf: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    def to_dict(self) -> dict:
        return asdict(self)


@lru_cache(maxsize=2)
def _engine(fast: bool):
    """``fast`` = PP-OCRv5 mobile models (crisp screen text); otherwise server models (scans/photos)."""
    # Imported lazily: paddle is heavy and not needed for --from-json runs or unit tests.
    from paddleocr import PaddleOCR

    kind = "mobile" if fast else "server"
    return PaddleOCR(
        text_detection_model_name=f"PP-OCRv5_{kind}_det",
        text_recognition_model_name=f"PP-OCRv5_{kind}_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def ocr_image(img: Image.Image, scale: float = 1.0, fast: bool = False, restore_spaces: bool = False,
              deskew: bool = False) -> list[OcrToken]:
    """OCR a PIL image, optionally upscaled first; boxes are mapped back to ``img`` pixels.

    ``restore_spaces``: re-insert word spaces the recogniser dropped ('BankTransfer'), using the
    pixel gaps inside each text box (document extraction only)."""
    original = img = img.convert("RGB")
    if scale > 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    bgr = np.asarray(img)[:, :, ::-1].copy()
    gray = np.asarray(img.convert("L")).astype(np.int16) if restore_spaces else None
    tokens: list[OcrToken] = []
    for page in _engine(fast).predict(bgr):
        angle = _skew_degrees(page.get("rec_polys", []))
        if deskew and 0.3 <= abs(angle) <= 10:
            # a tilted scan/photo: cells of one table row land on different heights and get split
            # into separate layout rows. Straighten the page and read it again.
            fill = tuple(int(v) for v in np.median(np.asarray(original).reshape(-1, 3), axis=0))
            straight = original.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=fill)
            return ocr_image(straight, scale, fast, restore_spaces, deskew=False)
        for text, score, box in zip(page["rec_texts"], page["rec_scores"], page["rec_boxes"]):
            if text.strip():
                text = text.strip()
                if gray is not None:
                    text = restore_word_spaces(text, gray[int(box[1]):int(box[3]), int(box[0]):int(box[2])])
                x0, y0, x1, y1 = (float(v) / scale for v in box)
                tokens.append(OcrToken(text=text, conf=float(score), x0=x0, y0=y0, x1=x1, y1=y1))
    return tokens


def _skew_degrees(polys) -> float:
    """Median slope of the wide text-line polygons (degrees; 0 = level)."""
    angles = []
    for poly in polys:
        p = np.asarray(poly, dtype=float)
        if p.shape[0] >= 4 and np.linalg.norm(p[1] - p[0]) > 3 * np.linalg.norm(p[3] - p[0]):
            angles.append(math.degrees(math.atan2(p[1][1] - p[0][1], p[1][0] - p[0][0])))
    return float(np.median(angles)) if len(angles) >= 5 else 0.0


_NO_SPACES = re.compile(r"^[A-Z0-9][A-Z0-9./-]*$|@|https?:|^[\d\s.,%+()-]+$")  # SKUs, refs, e-mails, numbers


def _word_break(left: str, right: str) -> bool:
    """A plausible place for a lost space: 'kT', '.2', 'l2', '2V' - never inside a lowercase word."""
    return ((left.islower() and right.isupper()) or (left in ".,;:)" and right.isalnum())
            or (left.isalpha() and right.isdigit()) or (left.isdigit() and right.isalpha() and right.isupper()))


def restore_word_spaces(text: str, crop: np.ndarray) -> str:
    """Insert a space where the box shows a word-sized gap but the text has none.

    Conservative: the gap must be clearly wider than the letter gaps in the same box, and the
    nearest character boundary must be a natural word break. Grounding compares without
    whitespace, so this can never make an invented value look grounded."""
    if len(text) < 4 or _NO_SPACES.search(text) or crop.size == 0:
        return text
    bg, dark = np.median(crop), np.percentile(crop, 3)
    if abs(bg - dark) < 40:
        return text  # no usable contrast
    mask = np.abs(crop - bg) > 0.4 * abs(bg - dark)
    ink = mask.any(axis=0)
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(ink)
    if cols.size < 2:
        return text
    lo, hi = int(cols[0]), int(cols[-1])
    gaps, start = [], None
    for x in range(lo, hi + 1):
        if not ink[x] and start is None:
            start = x
        elif ink[x] and start is not None:
            gaps.append((start, x - start))
            start = None
    if not gaps:
        return text
    letter_gap = float(np.median([w for _, w in gaps]))
    h = int(rows[-1] - rows[0] + 1)  # height of the ink, not of the (padded) box
    chars = list(text)
    inserted = 0
    for gx, gw in sorted(gaps):
        if gw < max(2.0 * letter_gap, 0.25 * h, 4):
            continue
        est = (gx + gw / 2 - lo) / max(1, hi - lo) * len(text)  # proportional character position
        if any(c == " " and abs(i + 0.5 - est) <= 1.5 for i, c in enumerate(text)):
            continue  # this gap is an existing space
        best = min((i for i in range(1, len(text)) if _word_break(text[i - 1], text[i])),
                   key=lambda i: abs(i - est), default=None)
        if best is not None and abs(best - est) <= 1.5:
            chars.insert(best + inserted, " ")
            inserted += 1
    return "".join(chars)


def ocr_images(images: list[Image.Image], scale: float = 1.0, fast: bool = False) -> list[list[OcrToken]]:
    """OCR several images in one engine call (much less overhead than one call per image)."""
    if not images:
        return []
    arrays = []
    for img in images:
        img = img.convert("RGB")
        if scale > 1:
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        arrays.append(np.asarray(img)[:, :, ::-1].copy())
    out = []
    for page in _engine(fast).predict(arrays):
        tokens = []
        for text, score, box in zip(page["rec_texts"], page["rec_scores"], page["rec_boxes"]):
            if text.strip():
                x0, y0, x1, y1 = (float(v) / scale for v in box)
                tokens.append(OcrToken(text=text.strip(), conf=float(score), x0=x0, y0=y0, x1=x1, y1=y1))
        out.append(tokens)
    return out


def run_ocr(path: Path, min_width: int = 1400) -> list[OcrToken]:
    """OCR an image file; low-resolution scans/photos are upscaled so small labels stay readable."""
    img = ImageOps.exif_transpose(Image.open(path))
    return ocr_image(img, scale=max(1.0, min_width / img.width), restore_spaces=True, deskew=True)
