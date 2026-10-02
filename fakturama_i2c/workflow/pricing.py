"""Money arithmetic used by the PDF rules. Pure functions, Decimal only, commercial rounding."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
HUNDRED = Decimal(100)


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def gross_price(unit_net: Decimal, vat_pct: Decimal) -> Decimal:
    """PDF 3.9: Price (gross) = unit net x (1 + VAT/100), 2 dp. Line discount is NOT applied."""
    return money(unit_net * (1 + vat_pct / HUNDRED))


def line_net(quantity: Decimal, unit_net: Decimal, discount_pct: Decimal) -> Decimal:
    """PDF 3.16: line Price = qty x unit net x (1 - discount/100)."""
    return money(quantity * unit_net * (1 - discount_pct / HUNDRED))


def line_vat(net: Decimal, vat_pct: Decimal) -> Decimal:
    return money(net * vat_pct / HUNDRED)


def document_totals(lines: Iterable[tuple[Decimal, Decimal]]) -> tuple[Decimal, Decimal, Decimal]:
    """(net, vat, gross) for ``(line_net, vat_pct)`` pairs. VAT is grouped per rate, like an invoice."""
    net_by_rate: dict[Decimal, Decimal] = {}
    for net, rate in lines:
        net_by_rate[rate] = net_by_rate.get(rate, Decimal(0)) + net
    net = money(sum(net_by_rate.values(), Decimal(0)))
    vat = money(sum((line_vat(n, r) for r, n in net_by_rate.items()), Decimal(0)))
    return net, vat, money(net + vat)


def pct_label(pct: Decimal) -> str:
    """19 -> '19', 7.50 -> '7.5' (used for 'VAT 19%')."""
    return format(pct.normalize(), "f")
