"""Data > Documents (PDF 4.5, 5.5): rows of saved Orders/Invoices, read via OCR."""

from __future__ import annotations

import re
import time

from ..errors import ManualReviewRequired
from ..ui.locate import name_of
from ..ui.wait import wait_until
from . import labels as L
from .grids import DOCUMENT_KEYS
from .master_data import ListView

# A document number as OCR may return it: a letter prefix plus digits ('PO000001', 'TNV000001').
_PLAUSIBLE_NUMBER = re.compile(r"^[A-Z0-9]{2,4}\d{3,}$")


class DocumentsView(ListView):
    NAV = L.NAV_DOCUMENTS
    COLUMNS = L.DOCUMENT_COLUMNS
    KEYS = DOCUMENT_KEYS
    ONLY = ["Document", "Date", "Cust.Ref.", "State", "Total"]  # 'Name' is never compared

    def __init__(self, app):
        super().__init__(app)
        self._clear_category_filter()

    def _filter_title(self) -> str:
        """The caption above the list, e.g. 'Invoices/unpaid' when a tree category is selected."""
        texts = [name_of(t).strip() for t in self.root.descendants(control_type="Text")]
        return next((t for t in texts if t and t != L.SEARCH.rstrip()), "")

    def _clear_category_filter(self) -> None:
        """A category selected in the view's left tree (by a person or an earlier click) hides
        every other document - a saved Order would look 'missing'. The tree's first entry (the
        transaction topic, '---' without a document context) lists all documents again."""
        if not self._filter_title():
            return
        items = self.root.descendants(control_type="TreeItem")
        if items:
            items[0].click_input()
        try:
            wait_until(lambda: not self._filter_title(), "Documents list without category filter", timeout=5)
        except Exception as exc:  # noqa: BLE001
            raise ManualReviewRequired("Documents", f"cannot clear the list filter {self._filter_title()!r}") from exc

    def search(self, text: str, step: str, attempts: int = 3) -> list[dict[str, str]]:
        """Like ListView.search, but re-read while any row has an implausible document number
        (a list captured mid-repaint can look stable and still be garbage), and accept an
        *empty* result only if the grid itself was recognised - a false 'nothing saved' would
        let a run create a duplicate Order."""
        records: list[dict[str, str]] = []
        for _ in range(attempts):
            records = super().search(text, step)
            if not records and not (self.grid._last and self.grid._last.spans):
                time.sleep(1.0)  # no grid recognised at all: an empty answer would not be trustworthy
                continue
            if all(_PLAUSIBLE_NUMBER.match(r.get("number", "").replace(" ", "")) for r in records):
                return records
            time.sleep(1.0)
        raise ManualReviewRequired(step, "Documents list could not be read reliably", {"rows": records})
