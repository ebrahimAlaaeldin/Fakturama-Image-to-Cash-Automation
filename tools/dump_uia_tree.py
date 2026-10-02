"""Dump the live UIA tree of Fakturama (or any window) to authoring page objects.

    python tools/dump_uia_tree.py                       # main Fakturama window
    python tools/dump_uia_tree.py --title "Select the address" --depth 12
    python tools/dump_uia_tree.py --all-windows         # every top-level window of the process

Output: indented text (stdout + runs/uia/<name>.txt) with control type, Name, AutomationId,
class, HelpText (tooltip), supported patterns and rectangle.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import psutil
from pywinauto import Desktop

PATTERNS = ("Invoke", "Value", "Toggle", "SelectionItem", "ExpandCollapse", "Grid", "Table", "Text", "LegacyIAccessible")


def patterns(el) -> str:
    out = []
    raw = el.element_info.element
    for p in PATTERNS:
        try:
            if raw.GetCurrentPattern(_pattern_id(p)):
                out.append(p)
        except Exception:  # noqa: BLE001
            pass
    return ",".join(out)


def _pattern_id(name: str) -> int:
    from pywinauto.uia_defines import IUIA

    return getattr(IUIA().UIA_dll, f"UIA_{name}PatternId")


def describe(el) -> str:
    info = el.element_info
    try:
        help_text = info.element.CurrentHelpText or ""
    except Exception:  # noqa: BLE001
        help_text = ""
    r = info.rectangle
    bits = [
        info.control_type or "?",
        f'name="{info.name}"' if info.name else "",
        f'id="{info.automation_id}"' if info.automation_id else "",
        f'class="{info.class_name}"' if info.class_name else "",
        f'help="{help_text}"' if help_text else "",
        f"[{patterns(el)}]",
        f"({r.left},{r.top},{r.right},{r.bottom})",
    ]
    return " ".join(b for b in bits if b)


def walk(el, depth: int, max_depth: int, out: list[str]) -> None:
    out.append("  " * depth + describe(el))
    if depth >= max_depth:
        return
    try:
        children = el.children()
    except Exception:  # noqa: BLE001
        return
    for c in children:
        walk(c, depth + 1, max_depth, out)


def _process(w) -> str:
    try:
        return psutil.Process(w.process_id()).name().lower()
    except psutil.Error:
        return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="", help="regex for the window title (default: any)")
    ap.add_argument("--process", default="Fakturama.exe", help="only windows of this process")
    ap.add_argument("--depth", type=int, default=25)
    ap.add_argument("--all-windows", action="store_true")
    args = ap.parse_args()

    desk = Desktop(backend="uia")
    rx = re.compile(args.title, re.I)
    wins = [w for w in desk.windows() if _process(w) == args.process.lower() and rx.search(w.window_text() or "")]
    if not args.all_windows:
        wins = wins[:1]
    if not wins:
        raise SystemExit(f"no window matching {args.title!r}; open: {[w.window_text() for w in desk.windows()]}")

    out_dir = Path("runs/uia")
    out_dir.mkdir(parents=True, exist_ok=True)
    for w in wins:
        lines: list[str] = []
        walk(w, 0, args.depth, lines)
        text = "\n".join(lines)
        name = re.sub(r"[^A-Za-z0-9]+", "_", w.window_text())[:50] or "window"
        (out_dir / f"{name}.txt").write_text(text, encoding="utf-8")
        print(text)
        print(f"\n--> {out_dir / (name + '.txt')}  ({len(lines)} elements)\n")


if __name__ == "__main__":
    main()
