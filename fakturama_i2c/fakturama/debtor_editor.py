"""New Debtor editor (PDF 2.5-2.11)."""

from __future__ import annotations

import time

from pywinauto.keyboard import send_keys

from ..errors import VerificationFailed
from ..extraction.normalize import parse_decimal
from ..models import Address
from ..ui import act
from ..ui.locate import Query, find, find_all, label_adjacent, name_of
from ..ui.wait import wait_until
from . import labels as L
from .page import Page
from .shell import Fakturama


class DebtorEditor(Page):
    @classmethod
    def new(cls, app: Fakturama) -> DebtorEditor:
        """PDF 2.5: left panel 'New Contact' (the Order tab stays open)."""
        return cls(app, app.open_editor(lambda: app.nav(L.NAV_NEW_CONTACT), L.EDITOR_NEW_DEBTOR))

    def customer_id(self) -> str:
        return self.value(L.CUSTOMER_ID)

    # ---------------------------------------------------------------- PDF 2.6

    def fill_identity(self, company: str, first: str, last: str, step: str) -> None:
        self.set(L.COMPANY, company, step)
        salutation = label_adjacent(self.root, L.SALUTATION, "ComboBox")
        if act.selected_text(salutation).strip() != L.SALUTATION_NONE:
            act.select_combo(salutation, L.SALUTATION_NONE, step, L.SALUTATION)
        first_box, last_box = self.edits_in_row(L.FIRST_LAST_NAME)[:2]
        act.set_text(first_box, first, step, "First Name")
        act.set_text(last_box, last, step, "Last Name")

    # ---------------------------------------------------------------- PDF 2.7-2.8

    def fill_address(self, addr: Address, step: str, email: str = "", phone: str = "", additional_name: str = "") -> None:
        """Fill the address tab that is currently visible (Main address or an additional one)."""
        if additional_name:
            self.set(L.ADDITIONAL_NAME, additional_name, step)
        self.set(L.STREET, addr.street, step)
        zip_box, city_box = self.edits_in_row(L.ZIP_CITY)[:2]
        act.set_text(zip_box, addr.zip, step, "ZIP")
        act.set_text(city_box, addr.city, step, "City")
        self.choose(L.COUNTRY, addr.country, step)
        if email:
            self.set(L.EMAIL, email, step)
        if phone:
            self.set(L.TELEPHONE, phone, step)

    def set_roles(self, invoice: bool, delivery: bool, step: str) -> str:
        """'address type' opens a popup of role checkboxes; tick exactly the requested ones."""
        pane = label_adjacent(self.root, L.ADDRESS_TYPE, "Pane")
        act.scroll_into_view(pane)
        self.app.focus()
        find(pane, Query(control_type="Button")).click_input()
        wanted = {L.ROLE_INVOICE: invoice, L.ROLE_DELIVERY: delivery}
        for role, on in wanted.items():
            box = find(self.app.main, Query(control_type="CheckBox", text=role), timeout=5)
            act.set_checked(box, on, step, f"role {role}")
        send_keys("{ESC}")
        time.sleep(0.3)
        shown = act.read(find(pane, Query(control_type="Edit")))
        for role, on in wanted.items():
            if (role.casefold() in shown.casefold()) != on:
                raise VerificationFailed(step, "address type", wanted, shown)
        return shown

    def add_address_tab(self, step: str) -> None:
        """The '+' beside 'Main address' adds 'additional address #n' and shows it."""
        before = {name_of(t) for t in find_all(self.root, Query(control_type="TabItem"))}
        act.click(self.button(L.ADD_ADDRESS))
        wait_until(
            lambda: {name_of(t) for t in find_all(self.root, Query(control_type="TabItem"))} - before,
            "new address tab",
        )

    # ---------------------------------------------------------------- PDF 2.9-2.10

    def fill_misc(self, alias: str, step: str) -> None:
        self.open_tab(L.TAB_MISC)
        self.set(L.ALIAS, alias, step)
        self.set(L.DEBTOR_DISCOUNT, "0", step, compare=lambda e, a: parse_decimal(a or "0") == 0)
        self.choose(L.NET_OR_GROSS, L.NET, step)

    def payment_options(self) -> list[str]:
        return act.combo_options(self.combo(L.DEBTOR_PAYMENT))

    def select_payment(self, method: str, step: str) -> str:
        return self.choose(L.DEBTOR_PAYMENT, method, step)
