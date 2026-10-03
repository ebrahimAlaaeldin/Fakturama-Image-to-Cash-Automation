"""Render a synthetic order image in the layout of the supplied sample, from data.

    python tools/render_order.py        -> samples/stress/*.png + expected.json

The repainted cases in samples/cases only change existing text. These stress cases change the
*structure* a reviewer is likely to vary: more item rows, mixed VAT rates, thousands separators,
other payment methods and statuses, umlauts, three-part names, identical addresses, a photo.
"""

from __future__ import annotations

import io
import json
import random
import shutil
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples" / "stress"

NAVY, BLUE, GREY, LINE, PANEL, ROW = "#13294b", "#2f6fb5", "#5b6675", "#cfd8e3", "#eaf0f6", "#f6f8fb"
W, H = 1489, 2048
CENT = Decimal("0.01")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), ("arialbd.ttf" if bold else "arial.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def money(v: Decimal) -> str:
    return f"{v:,.2f}"  # 1,250.00 - the sample's style, with a thousands separator when needed


def pct(v: Decimal) -> str:
    return f"{v.normalize():f}%"


def compute(order: dict) -> dict:
    """Line totals, VAT per rate and totals, rounded like an invoice (half-up, 2 decimals)."""
    net, vat_by_rate = Decimal(0), {}
    for it in order["items"]:
        line = (Decimal(it["qty"]) * Decimal(it["unit_net"]) * (1 - Decimal(it["disc"]) / 100)).quantize(CENT, ROUND_HALF_UP)
        it["line_net"] = line
        net += line
        vat_by_rate[Decimal(it["vat"])] = vat_by_rate.get(Decimal(it["vat"]), Decimal(0)) + line
    vat = sum(((base * rate / 100).quantize(CENT, ROUND_HALF_UP) for rate, base in vat_by_rate.items()), Decimal(0))
    order["totals"] = (net, vat, net + vat)
    return order


def render(o: dict) -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    label, value, valueb = font(17, True), font(26), font(26, True)

    d.rectangle((0, 0, W, 112), fill=NAVY)
    d.text((93, 40), "TJM Labs  |  Automation Assessment", fill="white", font=font(25, True))
    d.text((1183, 44), "SYNTHETIC TEST DATA", fill="#c9d6e6", font=font(19, True))
    d.text((92, 160), "SALES ORDER INPUT", fill=NAVY, font=font(56, True))
    d.text((92, 230), "Source document - extract all transaction values from this image", fill=GREY, font=font(22))
    d.rounded_rectangle((1233, 160, 1395, 208), radius=24, fill="#e6f4ea", outline="#9ccfaa", width=2)
    d.text((1314, 184), o["status"], fill="#1e7a3a", font=font(22, True), anchor="mm")

    def section(y: int, title: str, box_h: int, fill: str = PANEL) -> None:
        d.text((92, y), title, fill=BLUE, font=font(23, True))
        d.rounded_rectangle((93, y + 30, 1396, y + 30 + box_h), radius=12, fill=fill, outline=LINE, width=2)

    def field(x: int, y: int, name: str, val: str, bold: bool = False) -> None:
        d.text((x, y), name, fill=GREY, font=label)
        d.text((x, y + 26), val, fill=NAVY, font=valueb if bold else value)

    section(290, "ORDER", 145)
    field(120, 352, "EXTERNAL REFERENCE", o["ref"], bold=True)
    field(484, 352, "ORDER DATE", o["date"])
    field(800, 352, "CUSTOMER ID", o["customer_id"])
    field(1079, 352, "CURRENCY", "EUR", bold=True)

    section(508, "CUSTOMER AND CONTACT", 218, fill="white")
    d.line((745, 565, 745, 745), fill=LINE, width=2)
    field(120, 576, "COMPANY", o["company"], bold=True)
    field(120, 660, "CUSTOMER ALIAS", o["alias"])
    field(781, 566, "CONTACT NAME", o["contact"])
    field(781, 636, "EMAIL", o["email"])
    field(781, 706, "PHONE", o["phone"])

    section(806, "ADDRESSES", 262, fill="white")
    d.line((745, 865, 745, 1090), fill=LINE, width=2)
    for x, name, lines in ((120, "BILLING ADDRESS", o["billing"]), (781, "DELIVERY ADDRESS", o["delivery"])):
        d.text((x, 875), name, fill=GREY, font=label)
        for i, line in enumerate(lines):
            d.text((x, 915 + i * 35), line, fill=NAVY, font=value)

    section(1145, "PAYMENT", 135)
    field(120, 1208, "PAYMENT METHOD", o["method"], bold=True)
    field(664, 1208, "PAID STATUS", o["status"], bold=True)
    field(986, 1208, "PAYMENT DATE", o["paid_on"] or "-")

    # items table: header + max(4, n) rows of 78 px
    d.text((92, 1365), "ITEMS", fill=BLUE, font=font(23, True))
    cols = [(93, 145, "#"), (145, 340, "SKU"), (340, 722, "Description"), (722, 792, "Qty"), (792, 876, "Unit"),
            (876, 1025, "Unit net\n(EUR)"), (1025, 1132, "Disc."), (1132, 1216, "VAT"), (1216, 1396, "Line net\n(EUR)")]
    top, hh, rh = 1402, 60, 70
    rows = max(4, len(o["items"]))
    d.rectangle((93, top, 1396, top + hh), fill=NAVY)
    for x0, x1, name in cols:
        d.multiline_text(((x0 + x1) // 2, top + hh // 2), name, fill="white", font=font(17, True), anchor="mm",
                         align="center", spacing=0)
    for r in range(rows):
        y0 = top + hh + r * rh
        d.rectangle((93, y0, 1396, y0 + rh), fill=ROW if r % 2 else "white")
        if r < len(o["items"]):
            it = o["items"][r]
            cells = [str(r + 1), it["sku"], it["desc"], it["qty"], it["unit"], money(Decimal(it["unit_net"])),
                     pct(Decimal(it["disc"])), pct(Decimal(it["vat"])), money(it["line_net"])]
            for (x0, x1, _), text, i in zip(cols, cells, range(9)):
                f = font(21, bold=i in (1, 8))
                if i == 2:
                    d.text((x0 + 12, y0 + rh // 2), text, fill=NAVY, font=f, anchor="lm")
                else:
                    d.text(((x0 + x1) // 2, y0 + rh // 2), text, fill=NAVY, font=f, anchor="mm")
    bottom = top + hh + rows * rh
    for x0, _, _ in cols[1:]:
        d.line((x0, top + hh, x0, bottom), fill=LINE, width=2)
    d.rectangle((93, top, 1396, bottom), outline=LINE, width=2)

    ty = bottom + 25
    d.rounded_rectangle((93, ty, 1396, ty + 132), radius=12, fill="#f1f5f9", outline=LINE, width=2)
    for i, (name, v) in enumerate(zip(("NET TOTAL", "VAT TOTAL", "GROSS TOTAL"), o["totals"])):
        cx = 310 + i * 434
        d.text((cx, ty + 35), name, fill=BLUE if i == 2 else GREY, font=font(19, True), anchor="mm")
        d.text((cx, ty + 88), f"EUR {money(v)}", fill=NAVY, font=font(30, True), anchor="mm")
        if i:
            d.line((cx - 217, ty + 18, cx - 217, ty + 114), fill=LINE, width=2)

    fy = min(H - 40, ty + 175)
    d.line((93, fy - 25, 1396, fy - 25), fill=LINE, width=2)
    d.text((92, fy), "All data is synthetic  |  Prices are net  |  Dates: YYYY-MM-DD  |  Currency: EUR", fill=GREY, font=font(17))
    d.text((1396, fy), o["ref"], fill=GREY, font=font(17), anchor="ra")
    return img


def photo(img: Image.Image, angle: float = 1.6, blur: float = 1.1) -> Image.Image:
    """A phone photo of the page: rotation, blur, uneven light, noise, JPEG."""
    rnd = random.Random(7)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor="#d9d4c7")
    img = img.filter(ImageFilter.GaussianBlur(blur))
    shade = Image.linear_gradient("L").resize(img.size).point(lambda v: 225 + v // 9)
    img = Image.composite(img, Image.new("RGB", img.size, "#9a958a"), shade)
    img = img.resize((int(img.width * 0.72), int(img.height * 0.72)), Image.BILINEAR)
    px = img.load()
    for _ in range(4000):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        v = rnd.randrange(150, 255)
        px[x, y] = (v, v, v)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=55)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


BASE = dict(
    ref="WEB-2026-0901-C01", date="2026-09-01", customer_id="CUST-2001", company="Northstar Office GmbH",
    alias="NORTHSTAR-BERLIN", contact="Marta Klein", email="marta.klein@example.test", phone="+49 30 5550 1420",
    billing=["Northstar Office GmbH", "Friedrichstrasse 88", "10117 Berlin", "Germany"],
    delivery=["Northstar Office Warehouse", "Beusselstrasse 44", "10553 Berlin", "Germany"],
    method="Bank Transfer", status="PAID", paid_on="2026-09-03",
)

CASES = {
    "s1_four_items_mixed_vat": dict(
        BASE, purpose="4 lines, VAT 19% and 7%, 12.5% discount, thousands separator",
        items=[dict(sku="DSK-STD-140", desc="Standing Desk 140cm", qty="2", unit="pcs", unit_net="1250.00", disc="5", vat="19"),
               dict(sku="BK-ERGO-07", desc="Ergonomics Handbook", qty="10", unit="pcs", unit_net="24.90", disc="0", vat="7"),
               dict(sku="CBL-USB-C2", desc="USB-C Cable 2m", qty="25", unit="pcs", unit_net="8.40", disc="12.5", vat="19"),
               dict(sku="SRV-INST-01", desc="Installation Service", qty="3", unit="h", unit_net="65.00", disc="0", vat="19")]),
    "s2_not_paid_sepa": dict(
        BASE, ref="WEB-2026-0901-C02", method="SEPA Direct Debit", status="NOT PAID", paid_on=None,
        purpose="SEPA Direct Debit, status NOT PAID, no payment date",
        items=[dict(sku="CHR-ERG-01", desc="Ergonomic Desk Chair", qty="1", unit="pcs", unit_net="250.00", disc="0", vat="19")]),
    "s3_umlauts_same_address": dict(
        BASE, ref="WEB-2026-0901-C03", company="Müller & Söhne GmbH", alias="MUELLER-MUC", contact="Anna Maria Schmidt",
        email="a.schmidt@mueller-soehne.example", phone="+49 89 1234 5678", customer_id="CUST-2003",
        billing=["Müller & Söhne GmbH", "Königsallee 12", "80331 München", "Germany"],
        delivery=["Müller & Söhne GmbH", "Königsallee 12", "80331 München", "Germany"],
        method="Credit Card", purpose="umlauts, '&', three-part contact name, billing = delivery, Credit Card",
        items=[dict(sku="LMP-DESK-03", desc="LED Desk Lamp", qty="4", unit="pcs", unit_net="40.00", disc="0", vat="19"),
               dict(sku="MAT-DESK-02", desc="Anti-Fatigue Desk Mat", qty="2", unit="pcs", unit_net="40.00", disc="15", vat="19")]),
    "s4_five_items_7pct": dict(
        BASE, ref="WEB-2026-0901-C04", purpose="5 lines (table grows), all VAT 7%, small amounts",
        items=[dict(sku=f"BK-{i:03d}", desc=f"Office Guide Vol. {i}", qty=str(i), unit="pcs", unit_net=f"{9.95 + i:.2f}",
                    disc=str((i % 3) * 5), vat="7") for i in range(1, 6)]),
}


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    expected = {}
    for name, case in CASES.items():
        o = compute(json.loads(json.dumps(case)))
        img = render(o)
        img.save(OUT / f"{name}.png")
        variants = [(name, f"{name}.png")]
        if name == "s1_four_items_mixed_vat":  # the same order as a phone photo
            photo(img).save(OUT / "s5_photo_of_s1.jpg")
            variants.append(("s5_photo_of_s1", "s5_photo_of_s1.jpg"))
        if name == "s3_umlauts_same_address":  # a worse photo: tilted the other way, blurrier
            photo(img, angle=-3.5, blur=1.4).save(OUT / "s6_tilted_photo_of_s3.jpg")
            variants.append(("s6_tilted_photo_of_s3", "s6_tilted_photo_of_s3.jpg"))
        for key, file in variants:
            first, *_, last = o["contact"].split()
            expected[key] = {
                "image": file, "purpose": o["purpose"] + (" (photo: rotated, blurred, JPEG)" if key != name else ""),
                # too blurry for umlauts: OCR reads 'Müller' and 'Muller' -> must stop, never guess
                "expect_error": "ExtractionError" if key == "s6_tilted_photo_of_s3" else None,
                "expected": {
                    "external_reference": o["ref"], "order_date": o["date"], "company": o["company"],
                    "contact_last": last, "alias": o["alias"],
                    "billing": [o["billing"][1], *o["billing"][2].split(" ", 1)],
                    "delivery": [o["delivery"][1], *o["delivery"][2].split(" ", 1)],
                    "payment": [o["method"], o["status"], o["paid_on"]],
                    "items": [[i["sku"], i["desc"], i["qty"], f"{Decimal(i['unit_net']):.2f}", i["disc"], i["vat"],
                               f"{i['line_net']:.2f}"] for i in o["items"]],
                    "totals": [f"{v:.2f}" for v in o["totals"]],
                },
            }
    (OUT / "expected.json").write_text(json.dumps(expected, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n".join(sorted(expected)))


if __name__ == "__main__":
    main()
