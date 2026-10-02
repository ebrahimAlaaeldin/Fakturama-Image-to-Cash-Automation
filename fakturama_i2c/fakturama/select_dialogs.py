"""'Select the address' (PDF 2.1-2.3, 2.12) and 'Select a product' (PDF 3.2-3.3, 3.12)."""

from __future__ import annotations

import time
from collections.abc import Callable

from ..ui import act
from ..ui.locate import Query, find, name_of
from . import labels as L
from .grids import ADDRESS_KEYS, PRODUCT_KEYS, SearchableGrid
from .shell import Fakturama


class SelectDialog:
    TITLE = ""
    COLUMNS: list[str] = []
    KEYS: dict[str, str] = {}
    ONLY: list[str] | None = None  # columns the matcher uses (None = all)

    def __init__(self, app: Fakturama, opener: Callable[[], None]):
        self.app = app
        opener()
        self.root = app.dialog(self.TITLE)
        try:  # wider dialog = wider NatTable columns = no '...' truncation for OCR
            self.root.maximize()
        except Exception:  # noqa: BLE001
            pass
        self.grid = SearchableGrid(self.root, self.COLUMNS, self.KEYS, self.ONLY)

    def search(self, text: str, step: str) -> list[dict[str, str]]:
        """Type the search term, wait for the list to settle, return canonical records.

        Fakturama's product selector picks the product and closes itself when the term leaves
        exactly one match. ``self.closed`` reports that; the caller verifies what was added.
        """
        self.closed = False
        self.rows = []
        try:
            self.grid.search(text, step)
        except Exception:  # noqa: BLE001
            if self.is_open():
                raise
        time.sleep(0.5)
        if not self.is_open():
            self.closed = True
            return []
        self.rows = self.grid.stable_rows()
        return self.grid.as_records(self.rows)

    def is_open(self) -> bool:
        return any(name_of(d) == self.TITLE for d in self.app.dialogs())

    def choose(self, index: int) -> None:
        """Select the row the matcher picked and confirm with OK."""
        self.grid.select(self.rows[index])
        self._press(L.OK)

    def cancel(self) -> None:
        self._press(L.CANCEL)

    def _press(self, caption: str) -> None:
        act.click(find(self.root, Query(control_type="Button", text=caption)))
        self.app.wait_dialog_closed(self.root)


class AddressDialog(SelectDialog):
    TITLE = L.DLG_SELECT_ADDRESS
    COLUMNS = L.ADDRESS_COLUMNS
    KEYS = ADDRESS_KEYS


class ProductDialog(SelectDialog):
    TITLE = L.DLG_SELECT_PRODUCT
    COLUMNS = L.PRODUCT_COLUMNS
    KEYS = PRODUCT_KEYS
    ONLY = ["Item No.", "Name"]  # PDF 3.3 matches on the SKU (+ name for conflicts)
