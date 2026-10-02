"""Data > terms of payment (PDF 2.10.x), Data > VATs (3.4-3.6), New product (3.7-3.11)."""

from __future__ import annotations

import re
from decimal import Decimal

from ..errors import VerificationFailed
from ..extraction.normalize import parse_decimal
from ..ui import act
from ..ui.locate import Query, find
from ..workflow.matching import vat_name
from . import labels as L
from .document_editor import money_eq
from .grids import PAYMENT_KEYS, VAT_KEYS, SearchableGrid
from .page import Page
from .shell import Fakturama


def number_eq(expected: str, actual: str) -> bool:
    return money_eq(expected, actual)


class ListView:
    """A Data list (lower view stack) with a Search box, a NatTable and a green + button."""

    NAV = ""
    CREATE = ""
    COLUMNS: list[str] = []
    KEYS: dict[str, str] = {}
    ONLY: list[str] | None = None  # columns the checks use (None = all)

    def __init__(self, app: Fakturama):
        self.app = app
        app.nav(self.NAV)
        self.root = app.view(self.NAV)
        self.grid = SearchableGrid(self.root, self.COLUMNS, self.KEYS, self.ONLY)

    def search(self, text: str, step: str) -> list[dict[str, str]]:
        self.grid.search(text, step)
        self.rows = self.grid.stable_rows()
        return self.grid.as_records(self.rows)

    def open_row(self, index: int, title: str | None = None) -> Page:
        """Double-click a row to open its editor (used to inspect fields the list does not show).
        Without ``title`` the editor is identified by the tab that appears."""
        trigger = lambda: act.click_point(self.rows[index].center, double=True)  # noqa: E731
        root = self.app.open_editor(trigger, title) if title else self.app.open_new_editor(trigger)
        return Page(self.app, root)

    def create(self, editor_title: str) -> Page:
        self.app.focus()
        btn = find(self.root, Query(control_type="Button", text=self.CREATE))
        return Page(self.app, self.app.open_editor(lambda: act.click(btn), editor_title))


# --------------------------------------------------------------------------- terms of payment


class PaymentList(ListView):
    NAV = L.NAV_PAYMENTS
    CREATE = L.LIST_CREATE_PAYMENT
    COLUMNS = L.PAYMENT_COLUMNS
    KEYS = PAYMENT_KEYS
    ONLY = ["Name", "Description"]


def fill_payment(editor: Page, method: str, step: str) -> None:
    """PDF 2.10.3-2.10.5. Account, the three texts and 'Set as standard' are left untouched."""
    code = L.PAYMENT_CODE_MAP.get(method.strip().casefold())
    if code is None:
        raise VerificationFailed(step, "payment-code mapping", list(L.PAYMENT_CODE_MAP), method)
    editor.set(L.NAME, method, step)
    editor.set(L.DESCRIPTION, method, step)
    combo = find(editor.root, Query(control_type="ComboBox", pattern=L.PAYMENT_CODE_PATTERN))
    act.select_combo(combo, code, step, "payment code")
    for label in (L.CASH_DISCOUNT, L.DISCOUNT_DAYS, L.NET_DAYS):
        editor.set(label, "0", step, compare=lambda e, a: _num(a) == 0)
    if act.read(editor.edit(L.ACCOUNT)).strip():
        raise VerificationFailed(step, "Account blank", "", act.read(editor.edit(L.ACCOUNT)))


def payment_definition(editor: Page) -> dict[str, str]:
    """Read an existing term of payment (the list does not show its payment code)."""
    combo = find(editor.root, Query(control_type="ComboBox", pattern=L.PAYMENT_CODE_PATTERN))
    return {
        "code": act.selected_text(combo).strip(),
        "description": act.read(editor.edit(L.DESCRIPTION)),
        "cash_discount": act.read(editor.edit(L.CASH_DISCOUNT)),
        "discount_days": act.read(editor.edit(L.DISCOUNT_DAYS)),
        "net_days": act.read(editor.edit(L.NET_DAYS)),
    }


# --------------------------------------------------------------------------- VATs


class VatList(ListView):
    NAV = L.NAV_VATS
    CREATE = L.LIST_CREATE_VAT
    COLUMNS = L.VAT_COLUMNS
    KEYS = VAT_KEYS
    ONLY = ["Name", "Description", "Value"]


def vat_code(editor: Page) -> str:
    return act.selected_text(editor.combo(L.VAT_CODE))


def fill_vat(editor: Page, pct: Decimal, step: str) -> None:
    """PDF 3.6: Name = Description = 'VAT n%', code S (kept), Value n; Standard VAT untouched."""
    name = vat_name(pct)
    editor.set(L.NAME, name, step)
    editor.set(L.DESCRIPTION, name, step)
    code = vat_code(editor)
    if not is_standard_vat_code(code):
        raise VerificationFailed(step, "VAT code (E-Invoice)", "S (Standard rate)", code)
    editor.set(L.VAT_VALUE, act.fmt_number(pct, None), step, compare=lambda e, a: _num(a) == pct)


def is_standard_vat_code(code: str) -> bool:
    return bool(re.match(L.VAT_CODE_STANDARD_PATTERN, code or ""))


# --------------------------------------------------------------------------- products


class ProductEditor(Page):
    @classmethod
    def new(cls, app: Fakturama) -> ProductEditor:
        return cls(app, app.open_editor(lambda: app.nav(L.NAV_NEW_PRODUCT), "New product"))

    def fill(self, sku: str, description: str, gross: Decimal, vat_label: str, step: str) -> None:
        """PDF 3.8-3.10. Category, GTIN, supplier code, allowance, picture, user field 1 untouched."""
        self.set(L.PRODUCT_ITEM_NUMBER, sku, step)
        self.set(L.PRODUCT_NAME, description, step)
        self.set(L.PRODUCT_DESCRIPTION, description, step)
        self.choose(L.PRODUCT_VAT, vat_label, step)  # VAT first: Fakturama recomputes net from gross + VAT
        self.set(L.PRODUCT_PRICE_GROSS, act.fmt_number(gross), step, compare=number_eq)
        self.set(L.PRODUCT_COST_PRICE, act.fmt_number(0), step, compare=number_eq)
        self.set(L.PRODUCT_STOCK, act.fmt_number(0), step, compare=number_eq)


def _num(text: str) -> Decimal:
    try:
        return parse_decimal(text or "0")
    except ValueError:
        return Decimal(-1)
