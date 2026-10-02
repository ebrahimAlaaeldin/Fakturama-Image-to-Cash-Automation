"""NatTable-backed lists (selector dialogs and Data views): search box + OCR'd rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pywinauto.base_wrapper import BaseWrapper

from ..ui import act
from ..ui.grid import Grid, GridRow, grid_container, read_grid
from ..ui.locate import label_adjacent
from ..ui.wait import wait_stable
from . import labels as L


class SearchableGrid:
    """A NatTable with a 'Search:' filter box above it, inside ``root`` (dialog or view)."""

    def __init__(self, root: BaseWrapper, columns: Sequence[str], keys: Mapping[str, str],
                 only: Sequence[str] | None = None):
        self.root = root
        self.columns = list(columns)
        self.only = list(only) if only else None  # columns a check uses; others are not OCR'd
        self.keys = dict(keys)  # header text -> canonical key used by workflow.matching
        self._last: Grid | None = None

    def search(self, text: str, step: str) -> None:
        box = label_adjacent(self.root, L.SEARCH, "Edit")
        act.set_text(box, text, step, "search", commit=None, prefer_typing=True)  # SWT search ignores SetValue

    def read(self) -> Grid:
        self._last = read_grid(grid_container(self.root), self.columns, only=self.only)
        return self._last

    def stable_rows(self) -> list[GridRow]:
        """PDF 2.2: wait until the filtered list stops changing, then return its rows."""
        wait_stable(lambda: self.read().snapshot(), "list", polls=2, timeout=20)
        return self._last.rows if self._last else []

    def as_records(self, rows: Sequence[GridRow]) -> list[dict[str, str]]:
        """Rows keyed canonically (``{'company': ..., 'zip': ...}``) for the pure matchers."""
        return [{self.keys.get(k, k): v for k, v in r.cells.items()} for r in rows]

    def select(self, row: GridRow) -> None:
        act.click_point(row.center)


ADDRESS_KEYS = {"No.": "number", "First Name": "first_name", "Name": "name", "Company": "company", "ZIP": "zip", "City": "city"}
PRODUCT_KEYS = {"Item No.": "item_number", "Name": "name", "Description": "description", "Price": "price", "VAT": "vat"}
VAT_KEYS = {"Name": "name", "Description": "description", "Value": "value", "Standard": "standard"}
PAYMENT_KEYS = {"Name": "name", "Description": "description", "Standard": "standard"}
DOCUMENT_KEYS = {"Document": "number", "Date": "date", "Name": "name", "Cust.Ref.": "cust_ref", "State": "state", "Total": "total"}
