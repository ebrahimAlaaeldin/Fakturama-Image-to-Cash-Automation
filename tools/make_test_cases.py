"""Generate test-case order images from the sample (samples/cases/*.png + expected.json).

Values are repainted in place using the sample's OCR boxes (tests/fixtures/sample_ocr_tokens.json):
the box is filled with the surrounding background and the new text is drawn in the original
colour and size. Each case states what extraction must return and which branch of the PDF flow
it exercises.

    python tools/make_test_cases.py
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "order_WEB-2026-0714-A17.png"
TOKENS = json.loads((ROOT / "tests" / "fixtures" / "sample_ocr_tokens.json").read_text(encoding="utf-8"))
OUT = ROOT / "samples" / "cases"
FONT = {False: "C:/Windows/Fonts/segoeui.ttf", True: "C:/Windows/Fonts/segoeuib.ttf"}

BASE = {
    "external_reference": "WEB-2026-0714-A17",
    "order_date": "2026-07-14",
    "company": "Northstar Office GmbH",
    "contact": ["Marta", "Klein"],
    "alias": "NORTHSTAR-BERLIN",
    "billing": ["Friedrichstrasse 88", "10117", "Berlin"],
    "delivery": ["Beusselstrasse 44", "10553", "Berlin"],
    "payment": ["Bank Transfer", "PAID", "2026-07-18"],
    "items": [["CHR-ERG-01", "Ergonomic Desk Chair", "2", "250.00", "10", "19", "450.00"],
              ["MAT-DESK-02", "Anti-Fatigue Desk Mat", "3", "40.00", "0", "19", "120.00"]],
    "totals": ["570.00", "108.30", "678.30"],
}


def boxes(text: str) -> list[tuple[int, int, int, int]]:
    hits = [t for t in TOKENS if t["text"] == text]
    if not hits:
        raise KeyError(f"no OCR token {text!r} in the sample")
    return [tuple(round(t[k]) for k in ("x0", "y0", "x1", "y1")) for t in hits]


def repaint(img: Image.Image, old: str, new: str, bold: bool = False, which: int | None = None) -> None:
    """Replace every occurrence (or occurrence ``which``) of OCR token ``old`` with ``new``."""
    arr = np.asarray(img.convert("RGB"))
    draw = ImageDraw.Draw(img)
    for i, (x0, y0, x1, y1) in enumerate(boxes(old)):
        if which is not None and i != which:
            continue
        region = arr[y0:y1, x0:x1].reshape(-1, 3)
        ink = tuple(int(c) for c in region[region.sum(axis=1).argmin()])
        ring = np.concatenate([arr[max(0, y0 - 3), x0:x1], arr[min(arr.shape[0] - 1, y1 + 3), x0:x1]])
        bg = tuple(int(c) for c in np.median(ring, axis=0))
        draw.rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], fill=bg)
        if not new:
            continue
        h = y1 - y0
        font = ImageFont.truetype(FONT[bold], max(8, round(h * 1.05)))
        top = font.getbbox(new)[1]
        draw.text((x0, y0 - top), new, fill=ink, font=font)


def degrade(img: Image.Image) -> Image.Image:
    """A photographed/scanned look: slight rotation, blur, lower resolution, JPEG artefacts."""
    img = img.rotate(1.2, resample=Image.BICUBIC, expand=True, fillcolor="white")
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    img = img.resize((round(img.width * 0.6), round(img.height * 0.6)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=55)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def case(name: str, expect: dict, purpose: str, edit=None, post=None, error: str | None = None) -> dict:
    img = Image.open(SAMPLE).convert("RGB")
    if edit:
        edit(img)
    if post:
        img = post(img)
    path = OUT / f"{name}.png"
    img.save(path)
    return {"image": path.name, "purpose": purpose, "expect_error": error, "expected": expect}


def with_(**changes) -> dict:
    exp = json.loads(json.dumps(BASE))
    exp.update(changes)
    return exp


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    cases = {}

    cases["01_original"] = case("01_original", BASE, "The supplied sample: full create path on an empty workspace.")

    cases["02_degraded_scan"] = case(
        "02_degraded_scan", BASE, "Same order as a skewed, blurred, low-resolution JPEG: extraction must still be exact.",
        post=degrade)

    def unpaid(img):
        for ref in ("WEB-2026-0714-A17",):
            repaint(img, ref, "WEB-2026-0714-A18", bold=True, which=0)
            repaint(img, ref, "WEB-2026-0714-A18", which=1)
        repaint(img, "PAID", "OPEN", bold=True)
        repaint(img, "2026-07-18", "")
    cases["03_unpaid"] = case(
        "03_unpaid", with_(external_reference="WEB-2026-0714-A18", payment=["Bank Transfer", "UNPAID", None]),
        "Not paid: PDF 5.3 'leave paid clear and do not invent a date or value'.", edit=unpaid)

    def same_address(img):
        repaint(img, "WEB-2026-0714-A17", "WEB-2026-0714-A19", bold=True, which=0)
        repaint(img, "WEB-2026-0714-A17", "WEB-2026-0714-A19", which=1)
        repaint(img, "Northstar Office Warehouse", "Northstar Office GmbH")
        repaint(img, "Beusselstrasse 44", "Friedrichstrasse 88")
        repaint(img, "10553 Berlin", "10117 Berlin")
    cases["04_same_address"] = case(
        "04_same_address", with_(external_reference="WEB-2026-0714-A19", delivery=["Friedrichstrasse 88", "10117", "Berlin"]),
        "Billing == delivery: PDF 2.8 assigns both roles to the Main address (on a workspace without this Debtor).",
        edit=same_address)

    def new_product_card(img):
        repaint(img, "WEB-2026-0714-A17", "WEB-2026-0815-B02", bold=True, which=0)
        repaint(img, "WEB-2026-0714-A17", "WEB-2026-0815-B02", which=1)
        repaint(img, "MAT-DESK-02", "LMP-DESK-03", bold=True)
        repaint(img, "Anti-Fatigue Desk Mat", "LED Desk Lamp")
        repaint(img, "Bank Transfer", "Credit Card", bold=True)
    cases["05_new_product_credit_card"] = case(
        "05_new_product_credit_card",
        with_(external_reference="WEB-2026-0815-B02", payment=["Credit Card", "PAID", "2026-07-18"],
              items=[BASE["items"][0], ["LMP-DESK-03", "LED Desk Lamp", "3", "40.00", "0", "19", "120.00"]]),
        "Existing Debtor + Product reused, one new Product created. 'Credit Card' is not on the existing "
        "Debtor -> PDF 5.2 stops for manual review; create the method, then --resume finishes the Invoice.",
        edit=new_product_card)

    def wrong_total(img):
        repaint(img, "450.00", "460.00", bold=True)
    cases["06_line_total_wrong"] = case(
        "06_line_total_wrong", BASE, "Line total does not match qty x price x (1-discount): extraction must fail closed.",
        edit=wrong_total, error="ExtractionError")

    (OUT / "expected.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    for name, c in cases.items():
        print(f"{name:28} {c['image']:34} {c['purpose'][:70]}")


if __name__ == "__main__":
    main()
