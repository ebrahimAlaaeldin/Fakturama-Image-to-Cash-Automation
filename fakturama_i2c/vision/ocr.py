"""PaddleOCR wrapper -> list[OcrToken] (text, confidence, box in source-image pixels).

Shared by the order-image extraction and by the UI layer, which OCRs screenshots of
NatTable grids that expose no rows to UI Automation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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


def ocr_image(img: Image.Image, scale: float = 1.0, fast: bool = False) -> list[OcrToken]:
    """OCR a PIL image, optionally upscaled first; boxes are mapped back to ``img`` pixels."""
    img = img.convert("RGB")
    if scale > 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    bgr = np.asarray(img)[:, :, ::-1].copy()
    tokens: list[OcrToken] = []
    for page in _engine(fast).predict(bgr):
        for text, score, box in zip(page["rec_texts"], page["rec_scores"], page["rec_boxes"]):
            if text.strip():
                x0, y0, x1, y1 = (float(v) / scale for v in box)
                tokens.append(OcrToken(text=text.strip(), conf=float(score), x0=x0, y0=y0, x1=x1, y1=y1))
    return tokens


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
    return ocr_image(img, scale=max(1.0, min_width / img.width))
