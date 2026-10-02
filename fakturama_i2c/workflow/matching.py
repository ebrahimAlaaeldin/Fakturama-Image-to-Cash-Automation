"""Exact-match rules from the PDF. Pure functions over plain row dicts.

Rows come from UI grids already mapped to canonical keys by the page objects
(e.g. ``{"company": ..., "first_name": ..., "name": ..., "zip": ..., "city": ...}``),
so these rules are unit-testable without Fakturama.

Every resolver returns a ``Match`` with three outcomes, mirroring the PDF wording:
  EXACT     - exactly one row satisfies the rule -> select it
  NONE      - no row satisfies it and nothing conflicts -> create branch
  AMBIGUOUS - several exact rows, or a row that shares the identity key but disagrees on
              another field ("conflicting") -> stop for manual review
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from ..extraction.normalize import key, parse_decimal
from ..models import Address, Customer, LineItem
from .pricing import pct_label

Row = Mapping[str, str]


class MatchKind(Enum):
    EXACT = "exact"
    NONE = "none"
    AMBIGUOUS = "ambiguous"


@dataclass
class Match:
    kind: MatchKind
    row: Row | None = None
    index: int | None = None  # position in the visible list, for selecting it
    reason: str = ""
    candidates: list[Row] = field(default_factory=list)


def _resolve(
    rows: Sequence[Row],
    is_exact: Callable[[Row], bool],
    is_conflict: Callable[[Row], bool],
    what: str,
) -> Match:
    exact = [(i, r) for i, r in enumerate(rows) if is_exact(r)]
    conflicts = [r for r in rows if not is_exact(r) and is_conflict(r)]
    if len(exact) > 1:
        return Match(MatchKind.AMBIGUOUS, reason=f"{len(exact)} exact {what} rows", candidates=[r for _, r in exact])
    if conflicts:
        return Match(
            MatchKind.AMBIGUOUS,
            reason=f"{what} rows share the identity but differ in other fields",
            candidates=conflicts + [r for _, r in exact],
        )
    if exact:
        i, r = exact[0]
        return Match(MatchKind.EXACT, row=r, index=i)
    return Match(MatchKind.NONE, reason=f"no exact {what} row")


_TRUNCATION = re.compile(r"\s*(\u2026|\.{2,3})$")


def _eq(visible: str | None, expected: str | None) -> bool:
    """Exact (case/whitespace-insensitive). A grid cell NatTable cut off with an ellipsis
    ('Ergonomic Des..') matches when its visible prefix matches - the reader tries to auto-fit
    columns first, this only covers a column that could not be widened."""
    v, e = key(visible or ""), key(expected or "")
    if v == e:
        return True
    m = _TRUNCATION.search(v)
    return bool(m) and len(v[: m.start()]) >= 4 and e.startswith(v[: m.start()])


def _pct_eq(text: str | None, pct: Decimal) -> bool:
    try:
        return parse_decimal(text or "") == pct
    except ValueError:
        return False


# --------------------------------------------------------------------------- PDF 2.3 Debtor


def match_debtor(rows: Sequence[Row], customer: Customer, billing: Address) -> Match:
    """Exact = visible Company, First Name, Name, ZIP and City all match (PDF 2.3).

    Conflict = same Company but another field differs (e.g. same firm, other city).
    """

    def exact(r: Row) -> bool:
        return (
            _eq(r.get("company"), customer.company)
            and _eq(r.get("first_name"), customer.first_name)
            and _eq(r.get("name"), customer.last_name)
            and _eq(r.get("zip"), billing.zip)
            and _eq(r.get("city"), billing.city)
        )

    return _resolve(rows, exact, lambda r: _eq(r.get("company"), customer.company), "Debtor")


# --------------------------------------------------------------------------- PDF 3.3 Product


def match_product(rows: Sequence[Row], item: LineItem) -> Match:
    """Exact = Item No. equals the SKU (and the name agrees). Same SKU, other name = conflict."""

    def exact(r: Row) -> bool:
        return _eq(r.get("item_number"), item.sku) and (not r.get("name") or _eq(r.get("name"), item.description))

    return _resolve(rows, exact, lambda r: _eq(r.get("item_number"), item.sku), "Product")


# --------------------------------------------------------------------------- PDF 3.5 VAT


def vat_name(pct: Decimal) -> str:
    return f"VAT {pct_label(pct)}%"


def match_vat(rows: Sequence[Row], pct: Decimal) -> Match:
    """Exact = Name 'VAT n%' and Value n% (and code S when the row exposes it).

    The VAT list does not show the E-Invoice code; the caller verifies it in the editor
    before reusing the row (``vat_code_ok``).
    """
    name = vat_name(pct)

    def exact(r: Row) -> bool:
        code_ok = "code" not in r or vat_code_ok(r["code"])
        return _eq(r.get("name"), name) and _pct_eq(r.get("value"), pct) and code_ok

    return _resolve(rows, exact, lambda r: _eq(r.get("name"), name), "VAT")


def vat_code_ok(code: str) -> bool:
    """PDF 3.5: VAT code (E-Invoice) must be S (Standard rate)."""
    k = key(code)
    return k == "s" or k.startswith("s ") or k.startswith("s (")


# --------------------------------------------------------------------------- PDF 2.10.2 Payment


def match_payment(rows: Sequence[Row], method: str) -> Match:
    """Exact = Name equals the extracted method. Several rows with that name = conflict."""
    return _resolve(rows, lambda r: _eq(r.get("name"), method), lambda r: False, "Payment Method")


def payment_conflicts(definition: Mapping[str, str], method: str, code_map: Mapping[str, str]) -> list[str]:
    """PDF 2.10.2 'conflicting definition': an existing method with the right name but a payment
    code other than the PDF mapping (e.g. 'Bank Transfer' saved as 'In cash')."""
    expected = code_map.get(key(method))
    if expected is None:
        return [f"no payment-code mapping for {method!r}"]
    actual = definition.get("code", "")
    return [] if key(actual) == key(expected) else [f"payment code is {actual!r}, expected {expected!r}"]


def ref_matches(cell: str | None, reference: str, threshold: float = 0.9) -> bool:
    """A Cust.Ref. cell read by OCR from the Documents list. OCR can stutter a character
    ('WVEB-...' for 'WEB-...') or cut a long cell, so near-identical counts. Used for finding a
    document, never for writing; document number and total are still compared exactly."""
    c, r = key(cell or "").rstrip(".\u2026"), key(reference)
    if not c:
        return False
    if c == r or (len(c) >= 10 and r.startswith(c)):
        return True
    return difflib.SequenceMatcher(None, c, r).ratio() >= threshold


def same_document_number(cell: str | None, number: str) -> bool:
    """A document number read by OCR ('P0000004', 'TNV000001') against a real one ('PO000004',
    'INV000001'). The running number must be *equal* - a one-digit difference is another
    document - while the letter prefix may carry OCR noise (0/O, I/T)."""
    def parts(text: str) -> tuple[str, int] | None:
        m = re.match(r"^(.*?)(\d+)$", (text or "").replace(" ", "").upper())
        if not m:
            return None
        prefix = m.group(1).replace("0", "O")
        digits = m.group(2)
        # leading zeros may have been read as the prefix's 'O' or vice versa: compare the value
        return prefix.rstrip("O") or prefix, int(digits)
    a, b = parts(cell or ""), parts(number)
    if not a or not b or a[1] != b[1]:
        return False
    return a[0] == b[0] or difflib.SequenceMatcher(None, a[0], b[0]).ratio() >= 0.6


def state_matches(cell: str | None, state: str) -> bool:
    """The Documents 'State' cell ('V paid', '0unpaid', icon read as noise) against an expected
    state. Compared as a whole word: 'paid' must never match 'unpaid'."""
    words = re.findall(r"[a-z]+", key(cell or ""))
    return bool(words) and words[-1] == key(state)
