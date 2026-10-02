"""The Fakturama application shell: window, toolbar, navigation panel, editor tabs, dialogs, Save.

Editors are tracked by their root Pane (UIA keeps the element alive while the tab is open),
so the flow can leave the Order to create master data and come back to *the same* Order tab
(PDF 1.8 / 2.12 / 3.12).
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time

from pywinauto import Application, mouse
from pywinauto.base_wrapper import BaseWrapper
from pywinauto.keyboard import send_keys

from ..config import Settings
from ..errors import ControlNotFound, VerificationFailed
from ..ui import act
from ..ui.evidence import Evidence
from ..ui.locate import Query, find, find_all, help_text, name_of
from ..ui.wait import wait_until
from . import labels as L

log = logging.getLogger(__name__)


def _rid(el: BaseWrapper) -> tuple:
    return tuple(el.element_info.runtime_id or ())


class Fakturama:
    def __init__(self, app: Application, settings: Settings, evidence: Evidence, confirm: bool = False):
        self.app = app
        self.settings = settings
        self.evidence = evidence
        self.confirm = confirm
        # not top_window(): an open combo drop-down would be returned instead of the frame
        self.main = app.window(title_re=settings.main_window_title_re, class_name="SWT_Window0").wrapper_object()

    # ------------------------------------------------------------------ lifecycle

    @classmethod
    def attach(cls, settings: Settings, evidence: Evidence, confirm: bool = False) -> Fakturama:
        """Attach to a running Fakturama, or start it from FAKTURAMA_EXE."""
        try:
            app = Application(backend="uia").connect(path="Fakturama.exe", timeout=3)
        except Exception:  # noqa: BLE001
            if not settings.fakturama_exe:
                raise ControlNotFound("Fakturama is not running and FAKTURAMA_EXE is not set") from None
            log.info("starting %s", settings.fakturama_exe)
            subprocess.Popen([settings.fakturama_exe])
            app = wait_until(
                lambda: Application(backend="uia").connect(path="Fakturama.exe", timeout=1),
                "Fakturama to start",
                timeout=120,
            )
            wait_until(lambda: app.top_window().exists() and "Fakturama" in app.top_window().window_text(),
                       "Fakturama main window", timeout=120)
        shell = cls(app, settings, evidence, confirm)
        shell.focus()
        if not shell.main.is_maximized():
            shell.main.maximize()
        return shell

    def focus(self) -> None:
        """Real clicks go to whatever window is on top, so bring Fakturama forward first."""
        self.main.set_focus()

    # ------------------------------------------------------------------ toolbar / navigation

    def toolbar(self, tooltip: str) -> None:
        self.focus()
        act.click(find(self.main, Query(control_type=("Button", "SplitButton"), text=tooltip)))

    def nav(self, entry: str) -> None:
        """Left 'Data' / 'New' panel entries are SWT labels: only a real click works."""
        self.focus()
        item = find(self.main, Query(control_type="Text", text=entry, where=lambda e: bool(help_text(e))))
        item.click_input()

    # ------------------------------------------------------------------ editors (top tab folder)

    def tab_items(self) -> list[BaseWrapper]:
        return find_all(self.main, Query(control_type="TabItem"))

    def open_editor(self, trigger, title: str, timeout: float | None = None) -> BaseWrapper:
        """Run ``trigger`` and return the root Pane of the editor tab titled ``title``."""
        before = {_rid(e) for e in self._editor_panes(title)}
        trigger()

        def probe():  # the pane that was not there before (UIA RuntimeIds are stable)
            fresh = [p for p in self._editor_panes(title) if _rid(p) not in before]
            return fresh[0] if fresh else None

        root = wait_until(probe, f"editor {title!r}", timeout)
        self.activate(root)
        return root

    def open_new_editor(self, trigger, timeout: float | None = None) -> BaseWrapper:
        """Run ``trigger`` (e.g. double-click a Documents row) and return the editor it shows: the
        tab that appears, or - if the document was already open - the tab it brought forward.
        Titles come from UIA, so an OCR-misread document number in a list does not matter."""
        before = {name_of(t).lstrip("*") for t in self.tab_items()}
        trigger()
        try:
            title = wait_until(
                lambda: next((n for n in (name_of(t).lstrip("*") for t in self.tab_items()) if n not in before), None),
                "new editor tab", timeout=5,
            )
        except ControlNotFound:
            title = self.active_editor_title()
        return self.show_tab(title, timeout)

    def editor_folder(self) -> BaseWrapper | None:
        """The upper tab folder (it holds the 'Fakturama' start tab); its Name is the active tab."""
        for tab in find_all(self.main, Query(control_type="Tab")):
            if any(name_of(i) == "Fakturama" for i in tab.children() if i.element_info.control_type == "TabItem"):
                return tab
        return None

    def active_editor_title(self) -> str:
        folder = self.editor_folder()
        if folder is None:
            raise ControlNotFound("editor tab folder")
        return name_of(folder).lstrip("*")

    def show_tab(self, title: str, timeout: float | None = None) -> BaseWrapper:
        """Bring the editor tab ``title`` forward and return its root (the editor pane, or the
        folder while it shows that tab - saved editors do not always carry their title)."""
        self.focus()
        item = next((t for t in self.tab_items() if name_of(t).lstrip("*") == title), None)
        if item is None:
            raise ControlNotFound(f"no editor tab {title!r}")
        item.click_input()

        def root():
            panes = [p for p in self._editor_panes(title) if p.is_visible()]
            if panes:
                return panes[0]
            folder = self.editor_folder()
            return folder if folder is not None and name_of(folder).lstrip("*") == title else None

        return wait_until(root, f"editor {title!r}", timeout)

    def _editor_panes(self, title: str) -> list[BaseWrapper]:
        """All editor panes with this title (dirty ones carry a leading '*'), including background tabs."""
        return [p for p in self.main.descendants(control_type="Pane") if name_of(p).lstrip("*") == title]

    def open_work(self) -> list[str]:
        """Editor tabs a run must not start with: unsaved ('*') or never-saved ('New ...')."""
        return [n for n in (name_of(t) for t in self.tab_items()) if n.startswith("*") or n.startswith("New ")]

    def tab_item_for(self, root: BaseWrapper) -> BaseWrapper:
        title = name_of(root)
        for ti in self.tab_items():
            if name_of(ti).lstrip("*").strip() == title:
                return ti
        raise ControlNotFound(f"no tab for editor {title!r}")

    def activate(self, root: BaseWrapper) -> None:
        """Bring an editor tab to the front (CTabItem has no SelectionItem pattern -> click)."""
        self.focus()
        ti = self.tab_item_for(root)
        ti.click_input()
        wait_until(lambda: root.is_visible() or None, f"editor {name_of(root)!r} visible", timeout=5)

    def is_dirty(self, root: BaseWrapper) -> bool:
        return name_of(self.tab_item_for(root)).startswith("*")

    def save(self, root: BaseWrapper, step: str) -> None:
        """Toolbar Save, exactly once (PDF '... Save once'). Success = tab no longer dirty.

        Never retried: if the save does not verify, the run stops for inspection.
        """
        self.activate(root)
        if self.confirm:
            self.evidence.screenshot(f"{step}-before-save", self.main)
            # print + readline (not input()): the prompt must reach a GUI reading our stdout pipe
            print(f"\n[{step}] about to Save {name_of(root)!r} - press Enter to continue", flush=True)
            sys.stdin.readline()
            self.activate(root)
        self.toolbar(L.TOOLBAR_SAVE)
        self.fail_on_dialog(step)
        try:
            wait_until(lambda: not self.is_dirty(root), f"{name_of(root)!r} saved", timeout=10)
        except ControlNotFound:
            raise VerificationFailed(step, "editor saved (no '*')", "clean", name_of(self.tab_item_for(root))) from None

    def close_editor(self, root: BaseWrapper, discard: bool = True) -> None:
        """Close an editor tab without saving (cleanup only - never part of the verified flow).

        Eclipse answers Ctrl+W with either a Yes/No prompt or a 'Save Parts' checklist whose
        items start ticked; unticking them and pressing OK closes without saving.
        """
        title = name_of(root).lstrip("*")
        self.activate(root)
        send_keys("^w")
        time.sleep(0.8)
        for dlg in self.dialogs():
            for item in dlg.descendants(control_type="ListItem"):
                r = item.rectangle()  # the check box is drawn at the item's left edge
                mouse.click(coords=(r.left + 9, (r.top + r.bottom) // 2))
            buttons = {name_of(b): b for b in find_all(dlg, Query(control_type="Button"))}
            for caption in (*L.NO_BUTTONS, L.OK):
                if caption in buttons:
                    act.click(buttons[caption])
                    break
        gone = _rid(root)
        wait_until(lambda: all(_rid(p) != gone for p in self._editor_panes(title)), f"editor {title!r} closed", timeout=5)

    # ------------------------------------------------------------------ views (lower tab folder)

    def view(self, tab_title: str) -> BaseWrapper:
        """The lower view stack Tab that currently shows ``tab_title`` (e.g. 'VATs')."""

        def probe():
            for tab in find_all(self.main, Query(control_type="Tab")):
                items = [c for c in tab.children() if c.element_info.control_type == "TabItem"]
                if any(name_of(i) == tab_title for i in items) and name_of(tab) == tab_title:
                    return tab
            return None

        return wait_until(probe, f"view {tab_title!r}")

    # ------------------------------------------------------------------ dialogs

    def dialogs(self) -> list[BaseWrapper]:
        return [c for c in self.main.children() if c.element_info.control_type == "Window"]

    def dialog(self, title: str, timeout: float | None = None) -> BaseWrapper:
        return wait_until(
            lambda: next((d for d in self.dialogs() if name_of(d) == title), None), f"dialog {title!r}", timeout
        )

    def wait_dialog_closed(self, dlg: BaseWrapper, timeout: float = 10) -> None:
        wait_until(lambda: not any(name_of(d) == name_of(dlg) for d in self.dialogs()), "dialog to close", timeout)

    def fail_on_dialog(self, step: str, settle: float = 0.8) -> None:
        """An unexpected modal after an action (validation error, 'already exists') must stop the run."""
        time.sleep(settle)
        for d in self.dialogs():
            texts = [name_of(t) for t in d.descendants(control_type="Text") if name_of(t)]
            raise VerificationFailed(step, "no error dialog", None, f"{name_of(d)}: {' | '.join(texts)}")
