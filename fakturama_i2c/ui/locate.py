"""Control discovery. Grounding order (most to least robust):

1. semantic properties   - control type + Name / AutomationId / HelpText (tooltip)
2. label adjacency       - SWT rarely binds a label to its input, so find the visible label
                           text and take the nearest input to its right (or below) - geometry
                           is computed at runtime from live rectangles, never hardcoded
3. structural order      - icon-only buttons with no name: the n-th button inside a container
                           anchored by a label (e.g. 1st button next to 'Addresses')
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pywinauto.base_wrapper import BaseWrapper

from ..errors import ControlNotFound
from .wait import wait_until

Pred = Callable[[BaseWrapper], bool]


# --------------------------------------------------------------------------- properties


def name_of(el: BaseWrapper) -> str:
    try:
        return el.element_info.name or ""
    except Exception:  # noqa: BLE001
        return ""


def help_text(el: BaseWrapper) -> str:
    """Tooltip text; SWT ToolItems/Buttons expose their tooltip as UIA HelpText."""
    try:
        return el.element_info.element.CurrentHelpText or ""
    except Exception:  # noqa: BLE001
        return ""


def ctype(el: BaseWrapper) -> str:
    return el.element_info.control_type or ""


def visible(el: BaseWrapper) -> bool:
    try:
        r = el.rectangle()
        return el.is_visible() and r.width() > 0 and r.height() > 0
    except Exception:  # noqa: BLE001
        return False


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("&", "")).strip().casefold()


def text_is(expected: str) -> Pred:
    """Name or tooltip equals ``expected`` (whitespace/case/mnemonic-& insensitive)."""
    e = _norm(expected)
    return lambda el: _norm(name_of(el)) == e or _norm(help_text(el)) == e


def text_matches(pattern: str) -> Pred:
    rx = re.compile(pattern, re.I)
    return lambda el: bool(rx.search(name_of(el)) or rx.search(help_text(el)))


# --------------------------------------------------------------------------- search


@dataclass
class Query:
    """Declarative description of a control, readable in page objects and in error messages."""

    control_type: str | Iterable[str] | None = None
    text: str | None = None  # Name or tooltip, exact (normalised)
    pattern: str | None = None  # Name or tooltip, regex
    auto_id: str | None = None
    where: Pred | None = None

    def matches(self, el: BaseWrapper) -> bool:
        if self.control_type:
            types = {self.control_type} if isinstance(self.control_type, str) else set(self.control_type)
            if ctype(el) not in types:
                return False
        if self.auto_id and el.element_info.automation_id != self.auto_id:
            return False
        if self.text is not None and not text_is(self.text)(el):
            return False
        if self.pattern is not None and not text_matches(self.pattern)(el):
            return False
        return self.where is None or self.where(el)

    def __str__(self) -> str:
        parts = [f"{k}={v!r}" for k, v in vars(self).items() if v is not None and k != "where"]
        return f"Query({', '.join(parts)})"


def find_all(root: BaseWrapper, q: Query) -> list[BaseWrapper]:
    ct = q.control_type if isinstance(q.control_type, str) else None
    found = root.descendants(control_type=ct) if ct else root.descendants()
    return [el for el in found if visible(el) and q.matches(el)]


def find(root: BaseWrapper, q: Query, timeout: float | None = None, index: int | None = None) -> BaseWrapper:
    """Exactly one visible match (or the ``index``-th in reading order). Ambiguity is an error."""

    def probe():
        hits = reading_order(find_all(root, q))
        if index is not None:
            return hits[index] if len(hits) > index else None
        if len(hits) > 1:
            raise ControlNotFound(f"{q} is ambiguous: {len(hits)} matches")
        return hits[0] if hits else None

    return wait_until(probe, str(q), timeout)


def reading_order(els: list[BaseWrapper]) -> list[BaseWrapper]:
    return sorted(els, key=lambda e: (e.rectangle().top, e.rectangle().left))


# --------------------------------------------------------------------------- geometry-relative


def label_adjacent(
    root: BaseWrapper,
    label: str,
    control_type: str | Iterable[str] = "Edit",
    timeout: float | None = None,
) -> BaseWrapper:
    """Input belonging to a visible label: nearest candidate right of it on the same line,
    otherwise directly below it. Rectangles are read live, so layout changes are tolerated."""
    lab = find(root, Query(control_type="Text", text=label), timeout)
    lr = lab.rectangle()
    cands = find_all(root, Query(control_type=control_type))

    def right_of(el):
        r = el.rectangle()
        overlap = min(r.bottom, lr.bottom) - max(r.top, lr.top)
        return r.left >= lr.left + lr.width() // 2 and overlap > 0 and r.left - lr.right

    def below(el):
        r = el.rectangle()
        overlap = min(r.right, lr.right) - max(r.left, lr.left)
        return r.top >= lr.bottom - 2 and overlap > 0 and r.top - lr.bottom

    for side in (right_of, below):
        scored = [(d, el) for el in cands if (d := side(el)) is not False]
        if scored:
            return min(scored, key=lambda t: t[0])[1]
    raise ControlNotFound(f"no {control_type} next to label {label!r}")


def icons_with_label(
    root: BaseWrapper, label: str, control_types: Iterable[str] = ("Image", "Button")
) -> list[BaseWrapper]:
    """Icon-only controls that share ``label``'s container, top to bottom.

    For nameless icons (PDF 2.1 / 3.2: 'the upper icon beside Addresses / Items'). SWT puts
    the label and its icons in one composite, so the anchor is structural (same parent),
    not a coordinate.
    """
    lab = find(root, Query(control_type="Text", text=label))
    types = set(control_types)
    icons = [c for c in lab.parent().children() if ctype(c) in types and visible(c)]
    if not icons:
        raise ControlNotFound(f"no icons in the container of label {label!r}")
    return sorted(icons, key=lambda c: c.rectangle().top)
