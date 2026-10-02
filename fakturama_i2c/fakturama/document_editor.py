"""Order / Invoice editor (they share one SWT editor class in Fakturama).

Header (PDF 1.4-1.7), address box (2.1, 2.4, 2.13), Items selector icon (3.2), totals (4.2-4.3),
follow-up actions (4.6). Item-line editing lives in ``items_grid.py``.
"""

from __future__ import annotations

import re
from datetime import date

from ..errors import ControlNotFound, FollowUpExists, VerificationFailed
from ..extraction.normalize import parse_decimal
from ..ui import act, datefield
from ..ui.locate import Query, find, find_all, icons_with_label, label_adjacent, name_of
from ..ui.wait import wait_until
from . import labels as L
from .page import Page
from .select_dialogs import AddressDialog, ProductDialog
from .shell import Fakturama

def money_eq(expected: str, actual: str) -> bool:
    try:
        return parse_decimal(expected) == parse_decimal(actual)
    except ValueError:
        return False


class DocumentEditor(Page):
    # ------------------------------------------------------------------ open

    @classmethod
    def new_order(cls, app: Fakturama) -> DocumentEditor:
        """PDF 1.3: toolbar Order -> wait for the New Order editor."""
        return cls(app, app.open_editor(lambda: app.toolbar(L.TOOLBAR_NEW_ORDER), L.EDITOR_NEW_ORDER))

    # ------------------------------------------------------------------ header

    def number(self) -> str:
        return act.read(label_adjacent(self.root, L.DOC_NO, "Edit"))

    def date_edit(self):
        return label_adjacent(self.root, L.DOC_DATE, "Edit")

    def cust_ref_edit(self):
        return find(self.root, Query(control_type="Edit", text=L.CUST_REF))

    def set_date(self, d: date, step: str) -> str:
        return datefield.set_date(self.date_edit(), d, step, neutral=self.cust_ref_edit())

    def date_text(self) -> str:
        return act.read(self.date_edit())

    def cust_ref_text(self) -> str:
        return act.read(self.cust_ref_edit())

    def set_cust_ref(self, ref: str, step: str) -> str:
        return act.set_text(self.cust_ref_edit(), ref, step, L.CUST_REF)

    def price_mode_combo(self):
        """The unnamed Net/Gross combo sits right of the Date field."""
        date_box = self.date_edit()
        combos = [c for c in find_all(self.root, Query(control_type="ComboBox"))
                  if c.rectangle().left > date_box.rectangle().right
                  and abs(c.rectangle().top - date_box.rectangle().top) < 15]
        if not combos:
            raise ControlNotFound("price mode combo right of Date")
        return min(combos, key=lambda c: c.rectangle().left)

    def set_price_mode_net(self, step: str) -> str:
        return act.select_combo(self.price_mode_combo(), L.PRICE_MODE_NET, step, "price mode")

    def ensure_with_vat(self, step: str) -> str:
        combo = find(self.root, Query(control_type="ComboBox", text=L.VAT_MODE))
        if act.selected_text(combo).strip() != L.VAT_MODE_WITH_VAT:
            act.select_combo(combo, L.VAT_MODE_WITH_VAT, step, "VAT mode")
        return act.selected_text(combo)

    # ------------------------------------------------------------------ addresses

    def open_address_selector(self) -> AddressDialog:
        """PDF 2.1: the *upper* icon beside 'Addresses' (the lower green + would create a Debtor)."""
        self.app.activate(self.root)
        return AddressDialog(self.app, lambda: icons_with_label(self.root, L.ADDRESSES)[0].click_input())

    def addresses(self, switch_tabs: bool = False) -> dict[str, str]:
        """Address box text per tab (PDF 2.4 / 2.13 / 5.1).

        The box is one Edit whose content follows the selected tab. Selecting the other tab of
        an *unsaved* document breaks Fakturama's save (NullPointerException in SaveHandler,
        reproducible), so by default only the visible tab is read and the other tab is listed
        with ``None``; ``switch_tabs=True`` is for documents that will not be saved again.
        """
        self.app.activate(self.root)
        tabs = {name_of(t): t for t in find_all(self.root, Query(control_type="TabItem"))
                if name_of(t) in (L.TAB_INVOICE_ADDRESS, L.TAB_DELIVERY_ADDRESS)}
        if not tabs:
            return {}
        folder = next(iter(tabs.values())).parent()

        def box_text() -> str:
            boxes = find_all(folder, Query(control_type="Edit"))
            return act.read(boxes[0]) if boxes else ""

        out: dict[str, str | None] = {name: None for name in tabs}
        out[name_of(folder)] = box_text()  # the folder is named after its selected tab
        if switch_tabs:
            for name, tab in tabs.items():
                if out[name] is None:
                    shown = box_text()
                    tab.click_input()
                    try:  # the box repaints a moment after the tab switch
                        wait_until(lambda: box_text() != shown or None, f"{name} content", timeout=2)
                    except ControlNotFound:
                        pass  # identical content is possible (billing == delivery)
                    out[name] = box_text()
        return out

    # ------------------------------------------------------------------ items

    def open_product_selector(self) -> ProductDialog:
        """PDF 3.2: the *upper* Product-selection icon beside 'Items' (not the green +)."""
        self.app.activate(self.root)
        return ProductDialog(self.app, lambda: icons_with_label(self.root, L.ITEMS)[0].click_input())

    # ------------------------------------------------------------------ totals

    def totals(self) -> dict[str, str]:
        """Read-only total fields (PDF 4.3). Keys: net, discount, vat, total, shipping."""
        def edit_named(*names):
            for n in names:
                hits = find_all(self.root, Query(control_type="Edit", text=n))
                if hits:
                    return act.read(hits[-1])
            return ""

        shipping = find_all(self.root, Query(control_type="ComboBox", text=L.SHIPPING))
        return {
            "net": edit_named(*L.TOTAL_NET),
            "discount": edit_named(L.DOC_DISCOUNT),
            "vat": edit_named(L.DOC_VAT),
            "total": edit_named(L.DOC_TOTAL),
            "shipping": act.selected_text(shipping[0]) if shipping else "",
        }

    def ensure_no_discount_free_shipping(self, step: str) -> None:
        """PDF 4.2: overall Discount 0% and 'Free of shipping costs' unless the image says otherwise."""
        t = self.totals()
        if parse_decimal(t["discount"] or "0") != 0:
            act.set_text(find(self.root, Query(control_type="Edit", text=L.DOC_DISCOUNT)), "0", step, "Discount",
                         compare=money_eq)
        if L.SHIPPING_FREE.casefold() not in t["shipping"].casefold():
            combo = find(self.root, Query(control_type="ComboBox", text=L.SHIPPING))
            act.select_combo(combo, L.SHIPPING_FREE, step, "Shipping")

    # ------------------------------------------------------------------ follow-up

    def create_followup_invoice(self) -> DocumentEditor:
        """PDF 4.6: 'Create a follow-up document' > Invoice (keeps the Order link), not the toolbar."""
        group = find(self.root, Query(control_type="Group", pattern=r"follow-up"))
        btn = find(group, Query(control_type="Button", text=L.FOLLOWUP_INVOICE))
        if not btn.is_enabled():
            raise VerificationFailed("4.6", "follow-up Invoice enabled", True, False)
        self.app.focus()
        act.click(btn)

        def outcome():
            for dlg in self.app.dialogs():
                text = " ".join(name_of(t) for t in dlg.descendants(control_type="Text"))
                if re.search(L.FOLLOWUP_EXISTS_PATTERN, text, re.I):
                    return ("exists", dlg, text)
            panes = self.app._editor_panes(L.EDITOR_NEW_INVOICE)
            return ("new", panes[0], "") if panes else None

        kind, obj, text = wait_until(outcome, "new Invoice editor or Fakturama's follow-up warning")
        if kind == "exists":  # never create a second Invoice for the same Order
            act.click(find(obj, Query(control_type="Button", text="No")))
            number = (re.search(r"\(([^)]+)\)", text) or [None, ""])[1]
            raise FollowUpExists(number, text)
        self.app.activate(obj)
        return DocumentEditor(self.app, obj)

    # ------------------------------------------------------------------ invoice-only fields

    def labelled_date(self, label: str) -> str:
        """Read-only date fields of an Invoice ('Service date', 'Order Date')."""
        return act.read(label_adjacent(self.root, label, "Edit"))

    def vat_mode(self) -> str:
        return act.selected_text(find(self.root, Query(control_type="ComboBox", text=L.VAT_MODE)))

    def paid_box(self):
        return find(self.root, Query(control_type="CheckBox", text=L.PAID_CHECKBOX))

    def payment_combo(self):
        """Unnamed combo on the 'paid' row, right of the check box (PDF 5.2)."""
        box = self.paid_box().rectangle()
        combos = [c for c in find_all(self.root, Query(control_type="ComboBox"))
                  if not name_of(c) and c.rectangle().left > box.right - 2 and abs(c.rectangle().top - box.top) < 15]
        if not combos:
            raise ControlNotFound("payment method combo next to 'paid'")
        return min(combos, key=lambda c: c.rectangle().left)

    def payment_method(self) -> str:
        return act.selected_text(self.payment_combo()).strip()

    def payment_options(self) -> list[str]:
        return act.combo_options(self.payment_combo())

    def set_payment_method(self, method: str, step: str) -> str:
        return act.select_combo(self.payment_combo(), method, step, "payment method")

    def mark_paid(self, paid_on: date, value, step: str) -> None:
        """PDF 5.3: tick 'paid', then the 'at' date and the 'Value' that appear next to it."""
        act.set_checked(self.paid_box(), True, step, "paid")
        at = wait_until(lambda: label_adjacent(self.root, L.PAID_AT, "Edit"), "paid date field", timeout=5)
        datefield.set_date(at, paid_on, step, neutral=self.cust_ref_edit())
        value_box = find(self.root, Query(control_type="Edit", text=L.PAID_VALUE))
        act.set_text(value_box, act.fmt_number(value), step, "Value", compare=money_eq)

    def paid_state(self) -> dict[str, str | bool]:
        out: dict[str, str | bool] = {"paid": act.is_checked(self.paid_box()), "method": self.payment_method()}
        if out["paid"]:
            out["date"] = act.read(label_adjacent(self.root, L.PAID_AT, "Edit"))
            out["value"] = act.read(find(self.root, Query(control_type="Edit", text=L.PAID_VALUE)))
        return out

    def check(self, step: str, what: str, expected, actual, eq=None) -> None:
        ok = eq(expected, actual) if eq else expected == actual
        if not ok:
            raise VerificationFailed(step, what, expected, actual)

    def __repr__(self) -> str:
        return f"<DocumentEditor {name_of(self.root)!r}>"
