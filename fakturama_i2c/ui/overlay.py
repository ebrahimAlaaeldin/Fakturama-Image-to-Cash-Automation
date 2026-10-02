"""Click-through, never-focused caption window for screen recordings (--narrate).

Runs in its own process (Tk wants the main thread) and reads commands from stdin. The window
is WS_EX_NOACTIVATE | WS_EX_TRANSPARENT, so it can neither steal keyboard focus nor intercept
the automation's clicks. It sits bottom-left; while a grid is screenshotted for OCR it is
hidden (``hidden()``), so a caption can never be read as data.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

_CHILD = r"""
import ctypes, sys, threading, tkinter as tk
u = ctypes.windll.user32
root = tk.Tk(); root.withdraw(); root.overrideredirect(True); root.attributes("-topmost", True)
w, h = 560, 120
root.geometry(f"{w}x{h}+12+{root.winfo_screenheight() - h - 60}")
frame = tk.Frame(root, bg="#10243e", highlightthickness=2, highlightbackground="#3d8bfd"); frame.pack(fill="both", expand=True)
step = tk.Label(frame, text="", fg="#8ab4ff", bg="#10243e", font=("Segoe UI", 13, "bold"), anchor="w")
text = tk.Label(frame, text="", fg="white", bg="#10243e", font=("Segoe UI", 12), anchor="nw", justify="left", wraplength=w - 24)
step.pack(fill="x", padx=12, pady=(8, 0)); text.pack(fill="both", expand=True, padx=12, pady=(2, 8))
root.update_idletasks()
hwnd = u.GetParent(root.winfo_id())
GWL_EXSTYLE, NOACTIVATE, TRANSPARENT, LAYERED, TOOL = -20, 0x08000000, 0x20, 0x80000, 0x80
u.SetWindowLongW(hwnd, GWL_EXSTYLE, u.GetWindowLongW(hwnd, GWL_EXSTYLE) | NOACTIVATE | TRANSPARENT | LAYERED | TOOL)
root.attributes("-alpha", 0.92)
u.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE: visible, focus stays where it is
import queue
inbox = queue.Queue()
def apply(cmd, head, body):
    if cmd == "HIDE":
        u.ShowWindow(hwnd, 0)
    elif cmd == "SHOW":
        u.ShowWindow(hwnd, 4)
    else:
        step.config(text=head); text.config(text=body)
    root.update_idletasks()
    print("ack", flush=True)
PARENT = int(sys.argv[1])
k32 = ctypes.windll.kernel32
parent_handle = k32.OpenProcess(0x00100000, False, PARENT)  # SYNCHRONIZE
def parent_alive():
    return bool(parent_handle) and k32.WaitForSingleObject(parent_handle, 0) != 0
def pump():  # runs on Tk's own thread: Tk is not thread-safe
    if not parent_alive():  # never outlive the automation (e.g. a killed run)
        root.destroy(); return
    try:
        while True:
            item = inbox.get_nowait()
            if item is None:
                root.destroy(); return
            apply(*item)
    except queue.Empty:
        pass
    root.after(30, pump)
def reader():
    for line in sys.stdin:
        head, _, body = line.rstrip("\n").partition("\t")
        inbox.put((head[1:] if head.startswith("!") else "", head, body))
    inbox.put(None)
threading.Thread(target=reader, daemon=True).start()
root.after(30, pump)
root.mainloop()
"""

_active: Overlay | None = None


@contextmanager
def hidden():
    """Hide the caption while pixels are captured for OCR."""
    ov = _active
    if ov is None:
        yield
        return
    ov._send("!HIDE", "")
    try:
        yield
    finally:
        ov._send("!SHOW", "")


class Overlay:
    def __init__(self) -> None:
        global _active
        self._proc = subprocess.Popen(
            [sys.executable, "-c", _CHILD, str(os.getpid())], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )
        self._acks: queue.Queue = queue.Queue()
        threading.Thread(target=self._read_acks, daemon=True).start()
        _active = self

    def _read_acks(self) -> None:
        for line in self._proc.stdout:
            self._acks.put(line)

    def show(self, heading: str, text: str) -> None:
        clean = lambda s: " ".join(str(s).split()).lstrip("!")  # noqa: E731 - one line per caption
        self._send(clean(heading), clean(text))

    def _send(self, head: str, body: str) -> None:
        """Send one command and wait for the child's ack, so a HIDE has taken effect on return."""
        try:
            self._proc.stdin.write(f"{head}\t{body}\n")
            self._proc.stdin.flush()
            self._acks.get(timeout=2)  # never let the caption window block the automation
            time.sleep(0.05)  # let the compositor repaint
        except (OSError, ValueError, queue.Empty):
            pass

    def close(self) -> None:
        global _active
        _active = None
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            self._proc.kill()
