"""Segmented date widgets (Nebula CDateTime in Fakturama).

UIA's ValuePattern only repaints the text - the widget's model is not updated - so the date has
to be typed. Typing replaces the *selected segment* (month/day/year); Left/Right move between
segments with wrap-around, and the widget remembers the last segment used. We therefore:

1. focus arriving from another control selects the first segment - verified with a probe digit,
2. per segment: re-enter the widget, press Right i times, type the value (the widget
   auto-advances after a full segment, so presses are never chained after typing),
3. move focus away (commit) and verify the displayed date.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date

from pywinauto.base_wrapper import BaseWrapper
from pywinauto.keyboard import send_keys

from ..errors import VerificationFailed
from .act import read, scroll_into_view

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


@dataclass(frozen=True)
class DateLayout:
    """Segment order + how to parse/format the widget's display text."""

    order: tuple[str, ...]  # e.g. ("M", "D", "Y")
    regex: str
    month_names: bool = False

    def parse(self, text: str) -> dict[str, int] | None:
        m = re.fullmatch(self.regex, text.strip())
        if not m:
            return None
        out = {}
        for seg, raw in zip(self.order, m.groups()):
            if seg == "M" and self.month_names and not raw.isdigit():  # digits while the month is being edited
                out[seg] = _MONTHS.index(raw[:3].casefold()) + 1
            else:
                out[seg] = int(raw)
        return out

    def format(self, d: date) -> str:
        if self.month_names:
            return f"{_MONTHS[d.month - 1].capitalize()} {d.day}, {d.year}"
        parts = {"D": f"{d.day:02d}", "M": f"{d.month:02d}", "Y": f"{d.year}"}
        sep = "." if self.order[0] == "D" else "/" if self.order[0] == "M" else "-"
        return sep.join(parts[s] for s in self.order)


LAYOUTS = [
    DateLayout(("M", "D", "Y"), r"([A-Za-z]{3,}|\d{1,2})\.? (\d{1,2}), (\d{1,4})", month_names=True),  # Oct 2, 2026
    DateLayout(("D", "M", "Y"), r"(\d{1,2})\.(\d{1,2})\.(\d{1,4})"),  # 02.10.2026
    DateLayout(("Y", "M", "D"), r"(\d{1,4})-(\d{1,2})-(\d{1,2})"),  # 2026-10-02
    DateLayout(("M", "D", "Y"), r"(\d{1,2})/(\d{1,2})/(\d{1,4})"),  # 10/2/2026
]


def detect_layout(text: str) -> DateLayout:
    for layout in LAYOUTS:
        if layout.parse(text):
            return layout
    raise ValueError(f"unknown date format {text!r}")


def _segment_values(d: date) -> dict[str, str]:
    return {"M": f"{d.month:02d}", "D": f"{d.day:02d}", "Y": f"{d.year:04d}"}


def set_date(el: BaseWrapper, d: date, step: str, neutral: BaseWrapper, settle: float = 0.25) -> str:
    """Type ``d`` into a segmented date widget. ``neutral`` is any other focusable control."""
    scroll_into_view(el)
    layout = detect_layout(read(el))

    def enter():
        # Focus arriving from another control resets the widget to its first segment.
        neutral.set_focus()
        time.sleep(settle)
        el.set_focus()
        time.sleep(settle)

    # 1) verify the reset-to-first-segment behaviour instead of assuming it
    enter()
    before = layout.parse(read(el)) or {}
    probe = next(str(x) for x in (1, 2, 3) if all(v != x for v in before.values()))
    send_keys(probe)
    time.sleep(settle)
    after = layout.parse(read(el)) or {}
    changed = [s for s in layout.order if before.get(s) != after.get(s)]
    if changed != [layout.order[0]]:
        raise VerificationFailed(step, "date widget starts at first segment", layout.order[0], f"{before} -> {after}")

    # 2) one segment per focus cycle: the widget auto-advances after a full segment, so
    #    chaining Right presses after typing would skip segments
    values = _segment_values(d)
    for i, seg in enumerate(layout.order):
        enter()
        send_keys("{RIGHT}" * i + values[seg])
        time.sleep(settle)

    # 3) commit + verify against the widget's own format
    neutral.set_focus()
    time.sleep(settle)
    actual = read(el)
    if layout.parse(actual) != layout.parse(layout.format(d)):
        raise VerificationFailed(step, "Date", layout.format(d), actual)
    return actual
