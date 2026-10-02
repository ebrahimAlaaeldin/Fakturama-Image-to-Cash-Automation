"""Deterministic string -> typed conversion (RawOrder -> OrderExtraction)."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ..errors import ExtractionError
from ..models import (
    Address,
    Customer,
    LineItem,
    OrderExtraction,
    PaidStatus,
    Payment,
    RawAddress,
    RawOrder,
    Totals,
)

_WS = re.compile(r"\s+")
_NUM = re.compile(r"-?[\d.,\s]*\d")


def clean(text: str) -> str:
    """Collapse whitespace and strip."""
    return _WS.sub(" ", text or "").strip()


def key(text: str) -> str:
    """Comparison key: whitespace-collapsed, case-folded."""
    return clean(text).casefold()


def parse_decimal(text: str) -> Decimal:
    """'EUR 1.234,50' / '1,234.50' / '250.00' / '10%' / '-10,00 %' -> Decimal.

    The right-most of ',' / '.' is the decimal separator when followed by 1-2 digits.
    """
    m = _NUM.search(text or "")
    if not m:
        raise ValueError(f"no number in {text!r}")
    s = m.group(0).replace(" ", "")
    last_sep = max(s.rfind(","), s.rfind("."))
    if last_sep != -1 and len(s) - last_sep - 1 in (1, 2):
        int_part, frac = s[:last_sep], s[last_sep + 1 :]
        s = re.sub(r"[.,]", "", int_part) + "." + frac
    else:
        s = re.sub(r"[.,]", "", s)
    try:
        return Decimal(s)
    except InvalidOperation as exc:  # pragma: no cover - regex guarantees digits
        raise ValueError(f"bad number {text!r}") from exc


_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%b %d, %Y", "%d %b %Y")


def parse_date(text: str) -> date:
    t = clean(text)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r}")


def split_name(full: str) -> tuple[str, str]:
    """'Marta Klein' -> ('Marta', 'Klein'). Last token is the family name."""
    parts = clean(full).split(" ")
    if len(parts) < 2:
        return "", parts[0] if parts else ""
    return " ".join(parts[:-1]), parts[-1]


def parse_status(text: str) -> PaidStatus:
    return PaidStatus.PAID if key(text) == "paid" else PaidStatus.UNPAID


_ZIP_CITY = re.compile(r"^(\d{4,5})\s+(.+)$")


def _address(raw: RawAddress) -> Address:
    zip_code, city = clean(raw.zip), clean(raw.city)
    m = _ZIP_CITY.match(city)
    if not zip_code and m:  # "10117 Berlin" left in the city field -> split deterministically
        zip_code, city = m.group(1), m.group(2)
    return Address(name=clean(raw.name), street=clean(raw.street), zip=zip_code, city=city, country=clean(raw.country))


def to_order(raw: RawOrder) -> OrderExtraction:
    """Normalize; every conversion problem is collected and reported together."""
    issues: list[str] = []

    def conv(label: str, fn, value):
        try:
            return fn(value)
        except ValueError as exc:
            issues.append(f"{label}: {exc}")
            return None

    first, last = split_name(raw.contact_name)
    items: list[LineItem] = []
    for i, it in enumerate(raw.items, start=1):
        p = f"item {i} ({it.sku})"
        vals = {
            "quantity": conv(f"{p} quantity", parse_decimal, it.quantity),
            "unit_net": conv(f"{p} unit net", parse_decimal, it.unit_net),
            "discount_pct": conv(f"{p} discount", parse_decimal, it.discount or "0"),
            "vat_pct": conv(f"{p} VAT", parse_decimal, it.vat),
            "line_net": conv(f"{p} line total", parse_decimal, it.line_net),
        }
        position = conv(f"{p} position", lambda s: int(parse_decimal(s)), it.position) or i
        if None not in vals.values():
            items.append(
                LineItem(position=position, sku=clean(it.sku), description=clean(it.description), unit=clean(it.unit), **vals)
            )

    status = parse_status(raw.paid_status)
    pay_date = conv("payment date", parse_date, raw.payment_date) if clean(raw.payment_date) else None
    order_date = conv("order date", parse_date, raw.order_date)
    totals = {k: conv(k, parse_decimal, getattr(raw, k)) for k in ("net_total", "vat_total", "gross_total")}

    if not items:
        issues.append("no line items extracted")
    for label, value in (("company", raw.company), ("contact name", raw.contact_name), ("customer alias", raw.customer_alias),
                         ("payment method", raw.payment_method), ("billing street", raw.billing_address.street),
                         ("billing ZIP", raw.billing_address.zip or _ZIP_CITY.match(clean(raw.billing_address.city)))):
        if not value:
            issues.append(f"{label} is empty")
    if status is PaidStatus.PAID and pay_date is None:
        issues.append("status PAID but no payment date")
    if issues:
        raise ExtractionError("normalization failed", issues)

    return OrderExtraction(
        external_reference=clean(raw.external_reference),
        order_date=order_date,
        currency=clean(raw.currency),
        customer=Customer(
            company=clean(raw.company),
            first_name=first,
            last_name=last,
            alias=clean(raw.customer_alias),
            email=clean(raw.email),
            phone=clean(raw.phone),
            source_customer_id=clean(raw.customer_id),
        ),
        billing_address=_address(raw.billing_address),
        delivery_address=_address(raw.delivery_address),
        payment=Payment(method=clean(raw.payment_method), status=status, date=pay_date),
        items=sorted(items, key=lambda x: x.position),
        totals=Totals(net=totals["net_total"], vat=totals["vat_total"], gross=totals["gross_total"]),
    )
