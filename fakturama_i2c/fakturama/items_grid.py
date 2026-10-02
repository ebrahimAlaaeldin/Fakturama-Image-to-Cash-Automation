"""The Items table of an Order/Invoice editor (NatTable): read lines, edit cells (PDF 3.13-3.16)."""

from __future__ import annotations

import time
from collections.abc import Callable

from pywinauto.keyboard import send_keys

from ..errors import ControlNotFound, VerificationFailed
from ..extraction.normalize import key
from ..ui import act
from ..ui.grid import GridRow, grid_container, read_grid
from ..ui.locate import Query, find, name_of
from ..ui.wait import wait_until
from . import labels as L
from .page import Page


# Columns the line checks use (3.13-3.16, 4.1, 5.1); Picture/Name/Description are not OCR'd.
ITEM_CHECKED = ["Item No.", "Qty.", "VAT", "U.Price", "Discount", "Price"]


class ItemsGrid:
    def __init__(self, editor: Page):
        self.editor = editor

    def container(self):
        """The grid composite right of the 'Items' label's icon column."""
        label = find(self.editor.root, Query(control_type="Text", text=L.ITEMS))
        icons = label.parent()
        for sibling in icons.parent().children():
            r, ir = sibling.rectangle(), icons.rectangle()
            if sibling.element_info.control_type == "Pane" and r.left >= ir.right - 2 and abs(r.top - ir.top) < 10:
                return grid_container(sibling)
        raise ControlNotFound("Items grid")

    def rows(self) -> list[GridRow]:
        self.editor.app.activate(self.editor.root)
        return read_grid(self.container(), L.ITEM_COLUMNS, only=ITEM_CHECKED).rows

    def row_for(self, sku: str) -> GridRow:
        hits = [r for r in self.rows() if key(r.get("Item No.")) == key(sku)]
        if len(hits) != 1:
            raise VerificationFailed("3.x", f"exactly one item line for {sku}", 1, len(hits))
        return hits[0]

    def _cell_point(self, sku: str, column: str) -> tuple[int, int]:
        self.editor.app.activate(self.editor.root)
        container = self.container()
        grid = read_grid(container, L.ITEM_COLUMNS, only=ITEM_CHECKED)  # auto-fits truncated cells
        row = next((r for r in grid.rows if key(r.get("Item No.")) == key(sku)), None)
        if row is None or column not in grid.spans:
            raise ControlNotFound(f"cell {column!r} of line {sku}")
        x0, x1 = grid.spans[column]
        return container.rectangle().left + (x0 + x1) // 2, row.center[1]

    def choose_cell(self, sku: str, column: str, accept: Callable[[str], bool], step: str) -> str:
        """Combo cells (e.g. VAT): clicking opens a UIA List; pick the first entry ``accept`` likes."""
        point = self._cell_point(sku, column)
        self.editor.app.focus()
        act.click_point(point)
        options = wait_until(
            lambda: [i for i in self.editor.app.main.descendants(control_type="ListItem")
                     if i.is_visible() and i.parent().element_info.control_type == "List"],
            f"{column} options",
            timeout=5,
        )
        chosen = next((o for o in options if accept(name_of(o))), None)
        if chosen is None:
            send_keys("{ESC}")
            raise VerificationFailed(step, f"line {sku} {column} option", "matching entry", [name_of(o) for o in options])
        label = name_of(chosen)
        chosen.click_input()  # real click so NatTable commits the edit
        try:
            return wait_until(lambda: self.row_for(sku).get(column) if accept(self.row_for(sku).get(column)) else None,
                              f"{column} = {label}", timeout=4)
        except ControlNotFound:
            raise VerificationFailed(step, f"line {sku} {column}", label, self.row_for(sku).get(column)) from None

    def set_cell(self, sku: str, column: str, value: str, step: str, eq: Callable[[str, str], bool]) -> str:
        """Click the cell (row found by SKU, column by header), type, Enter, read back."""
        point = self._cell_point(sku, column)
        self.editor.app.focus()
        act.click_point(point)
        time.sleep(0.3)
        send_keys(act.escape_keys(value) + "{ENTER}")

        def committed():
            cell = self.row_for(sku).get(column)
            return cell if eq(value, cell) else None

        try:
            return wait_until(committed, f"{column} = {value}", timeout=4)
        except ControlNotFound:
            raise VerificationFailed(step, f"line {sku} {column}", value, self.row_for(sku).get(column)) from None
