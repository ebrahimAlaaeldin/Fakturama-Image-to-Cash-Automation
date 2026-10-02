"""Actions that verify themselves: every setter reads the control back and raises if it differs."""

from __future__ import annotations

import logging
import re
import time

from pywinauto.base_wrapper import BaseWrapper
from pywinauto import mouse
from pywinauto.keyboard import send_keys

from ..errors import ControlNotFound, VerificationFailed
from .locate import ctype, name_of
from .wait import wait_until

log = logging.getLogger(__name__)

_SEND_KEYS_SPECIAL = re.compile(r"([+^%~(){}\[\]])")


DECIMAL_SEP = "."  # learned from the application's own display (see learn_decimal_separator)


def learn_decimal_separator(sample: str) -> str:
    """'0,00 EUR' -> ','; '$0.00' -> '.'. Typed numbers must match the UI locale, otherwise a
    de-DE field reads '297.50' as 29.750,00."""
    global DECIMAL_SEP
    if re.search(r"\d,\d{2}(?!\d)", sample) and not re.search(r"\d\.\d{2}(?!\d)", sample):
        DECIMAL_SEP = ","
    elif re.search(r"\d\.\d{2}(?!\d)", sample):
        DECIMAL_SEP = "."
    return DECIMAL_SEP


def fmt_number(value, places: int | None = 2) -> str:
    """A number typed the way the UI expects it (no thousands separator)."""
    from decimal import Decimal

    d = Decimal(str(value))
    text = f"{d:.{places}f}" if places is not None else format(d.normalize(), "f")
    return text.replace(".", DECIMAL_SEP)


def escape_keys(text: str) -> str:
    """Escape pywinauto send_keys metacharacters so text is typed literally."""
    return _SEND_KEYS_SPECIAL.sub(r"{\1}", text).replace(" ", "{SPACE}")


def read(el: BaseWrapper) -> str:
    """Current text of an input. With a ValuePattern its value is authoritative even when empty
    (falling back to Name would report an empty field as its own label)."""
    try:
        return str(el.iface_value.CurrentValue or "")
    except Exception:  # noqa: BLE001 - no ValuePattern
        pass
    for getter in (lambda: el.legacy_properties().get("Value"), lambda: el.window_text()):
        try:
            v = getter()
            if v not in (None, ""):
                return str(v)
        except Exception:  # noqa: BLE001
            continue
    return name_of(el)


def click(el: BaseWrapper) -> None:
    """Invoke pattern (no mouse) when available, else a real click on the control's centre."""
    try:
        el.invoke()
    except Exception:  # noqa: BLE001
        scroll_into_view(el)
        el.click_input()


def park_mouse(el: BaseWrapper) -> None:
    """Move the pointer onto the window title bar so no hover tooltip covers what we OCR."""
    r = el.top_level_parent().rectangle()
    mouse.move(coords=((r.left + r.right) // 2, r.top + 8))
    time.sleep(0.15)


def click_point(point: tuple[int, int], double: bool = False) -> None:
    """Click a screen point that was computed at runtime (e.g. an OCR'd grid row centre)."""
    (mouse.double_click if double else mouse.click)(coords=point)


def _scroll_viewport(el: BaseWrapper) -> tuple[BaseWrapper, BaseWrapper] | None:
    """Nearest ancestor that owns a vertical scrollbar (SWT ScrolledComposite) + that scrollbar."""
    anc = el.parent()
    while anc is not None:
        try:
            bars = [c for c in anc.children() if ctype(c) == "ScrollBar" and name_of(c) == "Vertical"]
            if bars:
                return anc, bars[0]
            anc = anc.parent()
        except Exception:  # noqa: BLE001
            return None
    return None


def scroll_into_view(el: BaseWrapper, max_steps: int = 40) -> None:
    """SWT scrolled editors clip fields; scroll the owning viewport until ``el`` fits.

    The wheel is turned only with the pointer *on the viewport's own scrollbar*: a wheel event
    goes to whatever is under the pointer, and on Windows the wheel changes the value of a combo
    box (over the form it silently switched an Order to 'Free of Tax' and a Product's VAT).
    Positions are compared against the viewport's live rectangle, so this is layout-agnostic.
    """
    found = _scroll_viewport(el)
    if found is None:
        return
    vp, bar = found
    for _ in range(max_steps):
        r, v, b = el.rectangle(), vp.rectangle(), bar.rectangle()
        if r.bottom > v.bottom - 2:
            dist = -1
        elif r.top < v.top + 2:
            dist = 1
        else:
            return
        mouse.scroll(coords=((b.left + b.right) // 2, (b.top + b.bottom) // 2), wheel_dist=dist)
        time.sleep(0.12)


def type_text(el: BaseWrapper, text: str) -> None:
    """Focus, select all, type. Fires the key events SWT listeners expect.

    Keystrokes go to whatever has focus, so we refuse to type unless ``el`` really has it -
    otherwise a closed dialog could send our text (or Enter) to another window.
    """
    scroll_into_view(el)
    el.set_focus()
    el.click_input()
    ensure_focus(el)
    send_keys("^a{BACKSPACE}", pause=0.02)
    if text:
        send_keys(escape_keys(text), pause=0.01, with_spaces=True)


def ensure_focus(el: BaseWrapper) -> None:
    try:
        focused = el.has_keyboard_focus()
    except Exception:  # noqa: BLE001 - element gone
        focused = False
    if not focused:
        raise ControlNotFound(f"refusing to type: {name_of(el) or ctype(el)!r} does not have keyboard focus")


def set_text(el: BaseWrapper, text: str, step: str, what: str, *, compare=None, commit: str | None = "{TAB}",
             prefer_typing: bool = False) -> str:
    """Set and verify an input. ``compare(expected, actual)`` customises equality (e.g. numbers).

    UIA SetValue first (fast, no keystrokes). SWT applies it synchronously, so if the value is
    not there after a short moment it never will be (some SWT fields ignore SetValue) - then the
    text is typed. ``prefer_typing`` skips SetValue for fields known to ignore it (search boxes).
    """
    compare = compare or (lambda exp, act: exp.strip() == act.strip())
    if prefer_typing:
        type_text(el, text)
    else:
        try:
            el.iface_value.SetValue(text)
        except Exception:  # noqa: BLE001 - no ValuePattern / read-only to UIA -> type it
            type_text(el, text)
    if commit:
        el.set_focus()
        send_keys(commit)
    try:
        return wait_until(lambda: (lambda v: (v,) if compare(text, v) else None)(read(el)),
                          f"{what} = {text!r}", timeout=0.6)[0]
    except Exception:  # noqa: BLE001
        # One fallback: SetValue did not reach SWT -> retype with keystrokes.
        type_text(el, text)
        if commit:
            send_keys(commit)
        actual = read(el)
        if not compare(text, actual):
            raise VerificationFailed(step, what, text, actual) from None
        return actual


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def select_combo(el: BaseWrapper, option: str, step: str, what: str) -> str:
    """Select a combo entry by visible text and verify it (case/whitespace-insensitive -
    Fakturama pads some entries with trailing spaces).

    Keyboard first: keys on the focused combo fire the selection events SWT listens to.
    (UIA SelectionItem.Select() and even clicks in the drop-down list can change only what is
    *displayed* for some Fakturama combos - the document would keep its old value.)
      1. first-letter cycling: each press of the first letter jumps to the next entry with it
      2. arrow walk from the top, re-reading the selection after every press
      3. click the entry in the opened list
    Every attempt is verified by reading the selection back.
    """
    target = _norm(option)
    if _norm(selected_text(el)) != target:
        scroll_into_view(el)
        el.set_focus()
        ensure_focus(el)
        _first_letter_cycle(el, option)
    if _norm(selected_text(el)) != target:
        _arrow_walk(el, option)
    if _norm(selected_text(el)) != target:
        _select_by_click(el, option)
    send_keys("{TAB}")  # leave the combo so SWT commits/validates
    actual = selected_text(el)
    if _norm(actual) != target:
        raise VerificationFailed(step, what, option, actual)
    return actual


def _first_letter_cycle(el: BaseWrapper, option: str, limit: int = 60) -> None:
    letter = option.strip()[:1]
    if not letter.isalnum():
        return
    seen: set[str] = set()
    for _ in range(limit):
        send_keys(escape_keys(letter))
        time.sleep(0.05)
        now = _norm(selected_text(el))
        if now == _norm(option) or now in seen:  # found, or cycled through all entries
            return
        seen.add(now)


def _arrow_walk(el: BaseWrapper, option: str, limit: int = 400) -> None:
    el.set_focus()
    send_keys("{HOME}")
    previous = None
    for _ in range(limit):
        now = _norm(selected_text(el))
        if now == _norm(option) or now == previous:  # found, or end of list
            return
        previous = now
        send_keys("{DOWN}")
        time.sleep(0.03)


def _select_by_click(el: BaseWrapper, option: str) -> None:
    """Fallback: open the list and click the entry (scrolled into view first)."""
    el.expand()
    try:
        item = wait_until(
            lambda: next((i for i in el.descendants(control_type="ListItem") if _norm(name_of(i)) == _norm(option)), None),
            f"combo item {option!r}",
            timeout=5,
        )
        try:
            item.iface_scroll_item.ScrollIntoView()
            time.sleep(0.2)
        except Exception:  # noqa: BLE001 - short lists have no ScrollItem support
            pass
        item.click_input()
    finally:
        try:
            el.collapse()
        except Exception:  # noqa: BLE001
            pass


def combo_options(el: BaseWrapper) -> list[str]:
    el.expand()
    try:
        return [name_of(i).strip() for i in el.descendants(control_type="ListItem")]
    finally:
        el.collapse()


def selected_text(el: BaseWrapper) -> str:
    try:
        return el.selected_text()
    except Exception:  # noqa: BLE001
        return read(el)


def set_checked(el: BaseWrapper, checked: bool, step: str, what: str) -> None:
    if is_checked(el) != checked:
        scroll_into_view(el)
        try:
            el.toggle()
        except Exception:  # noqa: BLE001
            el.click_input()
    try:
        wait_until(lambda: is_checked(el) == checked, what, timeout=3)
    except Exception:  # noqa: BLE001
        raise VerificationFailed(step, what, checked, is_checked(el)) from None


def is_checked(el: BaseWrapper) -> bool:
    try:
        return el.get_toggle_state() == 1
    except Exception:  # noqa: BLE001
        return el.is_selected() if ctype(el) == "RadioButton" else False


def press(keys: str) -> None:
    send_keys(keys)
