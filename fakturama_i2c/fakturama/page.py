"""Base class for page objects: field access by visible label, scoped to one editor/dialog root."""

from __future__ import annotations

from pywinauto.base_wrapper import BaseWrapper

from ..errors import ControlNotFound
from ..ui import act
from ..ui.locate import Query, find, find_all, label_adjacent, name_of
from .shell import Fakturama


class Page:
    def __init__(self, app: Fakturama, root: BaseWrapper):
        self.app = app
        self.root = root

    # --------------------------------------------------------------- locating

    def _by_label(self, label: str, control_type: str) -> BaseWrapper:
        """SWT often names an input after its label; otherwise fall back to label adjacency."""
        hits = find_all(self.root, Query(control_type=control_type, text=label))
        if len(hits) == 1:
            return hits[0]
        return label_adjacent(self.root, label, control_type)

    def edit(self, label: str) -> BaseWrapper:
        return self._by_label(label, "Edit")

    def combo(self, label: str) -> BaseWrapper:
        return self._by_label(label, "ComboBox")

    def edits_in_row(self, label: str) -> list[BaseWrapper]:
        """Unnamed inputs grouped with one label, left to right ('First Name Last Name', 'ZIP - City')."""
        container = label_adjacent(self.root, label, ("Pane", "Edit"))
        edits = [container] if container.element_info.control_type == "Edit" else []
        edits += find_all(container, Query(control_type="Edit"))
        if not edits:
            raise ControlNotFound(f"no inputs next to {label!r}")
        return sorted(edits, key=lambda e: e.rectangle().left)

    def button(self, text: str) -> BaseWrapper:
        return find(self.root, Query(control_type=("Button", "SplitButton"), text=text))

    # --------------------------------------------------------------- acting (all verified)

    def set(self, label: str, value: str, step: str, **kw) -> str:
        return act.set_text(self.edit(label), value, step, label, **kw)

    def choose(self, label: str, option: str, step: str) -> str:
        el = self.combo(label)
        act.scroll_into_view(el)
        return act.select_combo(el, option, step, label)

    def value(self, label: str) -> str:
        return act.read(self.edit(label))

    def open_tab(self, name: str) -> None:
        self.app.focus()
        ti = find(self.root, Query(control_type="TabItem", text=name))
        act.scroll_into_view(ti)
        ti.click_input()

    @property
    def title(self) -> str:
        return name_of(self.root)
