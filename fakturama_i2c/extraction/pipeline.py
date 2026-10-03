"""PDF 1.1-1.2: image -> OCR -> rows -> LLM -> grounding -> normalize -> reconcile.

Every intermediate artefact is written to the run directory so a reviewer can see exactly
what OCR read, what the LLM was given, and what it returned.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..config import Settings
from ..errors import ExtractionError
from ..models import OrderExtraction, RawOrder
from ..vision import layout
from ..vision.ocr import run_ocr
from . import llm_structurer
from .grounding_check import accent_conflicts, check_grounding
from .layout_check import layout_conflicts
from .normalize import to_order
from .reconcile import ensure_reconciled

log = logging.getLogger(__name__)


def extract(image: Path, settings: Settings, out_dir: Path) -> OrderExtraction:
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("OCR %s", image)
    tokens = run_ocr(image, settings.ocr_min_width)
    _dump(out_dir / "ocr_tokens.json", [t.to_dict() for t in tokens])
    log.info("OCR found %d text fragments", len(tokens))
    accents = accent_conflicts(tokens)
    if accents:  # e.g. a blurry photo: 'Müller' and 'Muller' in the same image
        raise ExtractionError("the image is too unclear to read accented letters reliably", accents)

    rows_text = layout.render(layout.group_rows(tokens))
    (out_dir / "ocr_rows.txt").write_text(rows_text, encoding="utf-8")

    log.info("Structuring with %s", settings.groq_model)
    def check(raw):
        return [f"{field} must be {shown!r} (the value printed under its label)"
                for field, shown in layout_conflicts(raw, tokens).items()]

    raw = llm_structurer.structure(rows_text, settings, check=check)
    _dump(out_dir / "raw_order.json", raw.model_dump())

    issues = check_grounding(raw, tokens, settings.ocr_min_confidence) + check(raw)
    if issues:
        raise ExtractionError("extracted values are not grounded in the OCR layout", issues)

    order = finalize(raw)
    _dump(out_dir / "extraction.json", json.loads(order.model_dump_json()))
    log.info("Extraction OK: %s, %d items, gross %s", order.external_reference, len(order.items), order.totals.gross)
    return order


def finalize(raw: RawOrder) -> OrderExtraction:
    order = to_order(raw)
    ensure_reconciled(order)
    return order


def load(path: Path) -> OrderExtraction:
    """--from-json: accept either a typed extraction.json or a raw_order.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "customer" in data:
        order = OrderExtraction.model_validate(data)
        ensure_reconciled(order)
        return order
    return finalize(RawOrder.model_validate(data))


def _dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
