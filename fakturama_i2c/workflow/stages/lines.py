"""PDF 3.13-3.16: complete the selected item line and verify its price."""

from __future__ import annotations

import re
from decimal import Decimal

from ...errors import VerificationFailed
from ...extraction.normalize import parse_decimal
from ...fakturama import labels as L
from ...fakturama.items_grid import ItemsGrid
from ...models import LineItem
from .. import pricing
from ...ui import act
from ..context import RunContext
from .vat_mode import keep_with_vat


def num_eq(expected: str, actual: str) -> bool:
    try:
        return parse_decimal(expected) == parse_decimal(actual)
    except ValueError:
        return False


def discount_eq(expected: str, actual: str) -> bool:
    """Fakturama shows line discounts as negative percentages ('-10.00 %')."""
    try:
        return abs(parse_decimal(expected)) == abs(parse_decimal(actual))
    except ValueError:
        return False


def vat_cell_pct(cell: str) -> set[Decimal]:
    """'VAT 19% (19.0%)' -> {19}: every percentage shown in the cell."""
    return {Decimal(n) for n in re.findall(r"(\d+(?:[.,]\d+)?)\s*%", cell.replace(",", "."))}


def complete_line(ctx: RunContext, item: LineItem, line_no: int) -> None:
    grid = ItemsGrid(ctx.editor)
    sku = item.sku
    with ctx.step("3.13 Qty", sku=sku, qty=item.quantity):
        grid.set_cell(sku, "Qty.", act.fmt_number(item.quantity, None), "3.13", num_eq)
    with ctx.step("3.14 U.Price and VAT", sku=sku, unit_net=item.unit_net, vat=item.vat_pct):
        row = grid.row_for(sku)
        if not num_eq(f"{item.unit_net}", row.get("U.Price")):
            grid.set_cell(sku, "U.Price", act.fmt_number(item.unit_net), "3.14", num_eq)
        if item.vat_pct not in vat_cell_pct(row.get("VAT")) and ctx.editor.vat_mode().strip() != L.VAT_MODE_WITH_VAT:
            # Fakturama flipped the document to 'Free of Tax' (foreign Debtor) which forces lines to
            # Tax-free; restoring 'With VAT' (PDF 1.7) recalculates the lines with the Product VAT.
            keep_with_vat(ctx, "3.14")
            row = grid.row_for(sku)
        if item.vat_pct not in vat_cell_pct(row.get("VAT")):
            # "Set or confirm": pick the exact rate in the line's VAT cell.
            grid.choose_cell(sku, "VAT", lambda text: item.vat_pct in vat_cell_pct(text), "3.14")
            if not num_eq(f"{item.unit_net}", grid.row_for(sku).get("U.Price")):
                grid.set_cell(sku, "U.Price", act.fmt_number(item.unit_net), "3.14", num_eq)
    with ctx.step("3.15 Discount", sku=sku, discount=item.discount_pct):
        if not discount_eq(f"{item.discount_pct}", grid.row_for(sku).get("Discount")):
            grid.set_cell(sku, "Discount", act.fmt_number(item.discount_pct, None), "3.15", discount_eq)
    with ctx.step("3.16 verify line Price", sku=sku):
        expected = pricing.line_net(item.quantity, item.unit_net, item.discount_pct)
        shown = grid.row_for(sku).get("Price")
        if not num_eq(f"{expected}", shown):
            raise VerificationFailed("3.16", f"line {sku} Price", expected, shown)
        ctx.evidence.record(f"3.16 line {line_no}", "ok", sku=sku, price=shown, expected=expected)
