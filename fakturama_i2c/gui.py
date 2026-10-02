"""Small desktop front-end: pick an order image, check the extraction, run or resume.

    python -m fakturama_i2c gui

It drives the same CLI in a subprocess (so the window stays responsive and a run behaves
exactly like the command line). While a run is active the window minimises itself: the
automation needs the screen, and grids are read from screen pixels.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageGrab, ImageTk

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
CASES = ROOT / "samples" / "cases"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
NOISE = re.compile(r"ccache|warnings.warn|UserWarning|Creating model|Using official|Fetching \d|INFO: Could|return PaddleOCR")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Fakturama Image-to-Cash")
        self.geometry("1120x720")
        self.minsize(960, 600)
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 15))
        style.configure("Hint.TLabel", foreground="#666")
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10))

        self.image_path: Path | None = None
        self.extraction_json: Path | None = None
        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.last_run_dir: Path | None = None
        self.kind = ""
        self._thumb = None

        self._build()
        self.after(100, self._drain)

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        top = ttk.Frame(self, padding=(14, 10))
        top.pack(fill="x")
        ttk.Label(top, text="Fakturama Image-to-Cash", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text="order image  →  Order  →  paid Invoice", style="Hint.TLabel").pack(side="left", padx=12)

        body = ttk.Frame(self, padding=(14, 0, 14, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # left: image source + preview
        left = ttk.LabelFrame(body, text=" 1  Order image ", padding=10)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        src = ttk.Frame(left)
        src.pack(fill="x")
        ttk.Button(src, text="Open image…", command=self.open_image).pack(side="left")
        ttk.Button(src, text="Paste screenshot", command=self.paste_clipboard).pack(side="left", padx=6)
        ttk.Button(src, text="Snip screen…", command=self.snip).pack(side="left")
        cases = ttk.Frame(left)
        cases.pack(fill="x", pady=(8, 0))
        ttk.Label(cases, text="Test case:").pack(side="left")
        self.case_var = tk.StringVar()
        names = ["sample (original)"] + sorted(p.name for p in CASES.glob("*.png"))
        self.case_box = ttk.Combobox(cases, textvariable=self.case_var, values=names, state="readonly", width=30)
        self.case_box.pack(side="left", padx=6)
        self.case_box.bind("<<ComboboxSelected>>", self.pick_case)
        self.preview = ttk.Label(left, text="No image yet", anchor="center", width=46)
        self.preview.pack(fill="both", expand=True, pady=10)
        self.image_label = ttk.Label(left, text="", style="Hint.TLabel", wraplength=330)
        self.image_label.pack(fill="x")

        # right: actions, extracted data, log
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        actions = ttk.LabelFrame(right, text=" 2  Actions ", padding=10)
        actions.grid(row=0, column=0, sticky="ew")
        self.btn_extract = ttk.Button(actions, text="Extract & check", command=self.extract)
        self.btn_run = ttk.Button(actions, text="▶  Run", style="Accent.TButton", command=lambda: self.start(resume=False))
        self.btn_resume = ttk.Button(actions, text="⟳  Resume", command=lambda: self.start(resume=True))
        self.btn_continue = ttk.Button(actions, text="Continue (Save)", command=self.continue_save, state="disabled")
        self.btn_stop = ttk.Button(actions, text="■  Stop", command=self.stop, state="disabled")
        for i, b in enumerate((self.btn_extract, self.btn_run, self.btn_resume, self.btn_continue, self.btn_stop)):
            b.grid(row=0, column=i, padx=(0, 8))
        opts = ttk.Frame(actions)
        opts.grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 0))
        self.fast = tk.BooleanVar(value=False)
        self.narrate = tk.BooleanVar(value=True)
        self.confirm = tk.BooleanVar(value=False)
        self.hide = tk.BooleanVar(value=True)
        self.pace = tk.DoubleVar(value=1.5)
        ttk.Checkbutton(opts, text="⚡ Fast mode", variable=self.fast, command=self._fast_toggled).pack(side="left", padx=(0, 10))
        self.cb_narrate = ttk.Checkbutton(opts, text="On-screen captions", variable=self.narrate)
        self.cb_narrate.pack(side="left")
        ttk.Checkbutton(opts, text="Pause before each Save", variable=self.confirm).pack(side="left", padx=10)
        ttk.Checkbutton(opts, text="Minimise while running", variable=self.hide).pack(side="left")
        ttk.Label(opts, text="   Pace (s):").pack(side="left")
        self.sp_pace = ttk.Spinbox(opts, from_=0, to=5, increment=0.5, textvariable=self.pace, width=4)
        self.sp_pace.pack(side="left")

        data = ttk.LabelFrame(right, text=" 3  Extracted data (what will be entered) ", padding=6)
        data.grid(row=1, column=0, sticky="nsew", pady=8)
        self.tree = ttk.Treeview(data, columns=("value",), show="tree headings", height=8)
        self.tree.heading("#0", text="Field")
        self.tree.heading("value", text="Value")
        self.tree.column("#0", width=200, stretch=False)
        self.tree.pack(fill="both", expand=True)

        logf = ttk.LabelFrame(right, text=" 4  Progress ", padding=6)
        logf.grid(row=2, column=0, sticky="nsew")
        self.log = tk.Text(logf, height=10, wrap="word", font=("Consolas", 9), bg="#0f1720", fg="#d6deeb",
                           insertbackground="#d6deeb", relief="flat")
        scroll = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        for tag, colour in {"step": "#82aaff", "ok": "#7fdb8a", "found": "#7fdb8a", "missing": "#ffcb6b",
                            "warn": "#f78c6c", "bad": "#ff5370", "done": "#c3e88d"}.items():
            self.log.tag_configure(tag, foreground=colour)

        bottom = ttk.Frame(self, padding=(14, 0, 14, 10))
        bottom.pack(fill="x")
        self.status = ttk.Label(bottom, text="Ready.", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="Open last run folder", command=self.open_run_folder).pack(side="right")

    # ------------------------------------------------------------------ image sources

    def set_image(self, path: Path) -> None:
        self.image_path = path
        self.extraction_json = None
        self.tree.delete(*self.tree.get_children())
        img = Image.open(path)
        img.thumbnail((330, 430))
        self._thumb = ImageTk.PhotoImage(img)
        self.preview.configure(image=self._thumb, text="")
        self.image_label.configure(text=str(path))
        self.set_status("Image loaded - click 'Extract & check' to see what will be entered.")

    def open_image(self) -> None:
        f = filedialog.askopenfilename(title="Order image", initialdir=ROOT / "samples",
                                       filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"), ("All", "*.*")])
        if f:
            self.set_image(Path(f))

    def pick_case(self, _event=None) -> None:
        name = self.case_var.get()
        path = ROOT / "samples" / "order_WEB-2026-0714-A17.png" if name.startswith("sample") else CASES / name
        self.set_image(path)
        expected = CASES / "expected.json"
        if expected.exists() and name in {p.name for p in CASES.glob("*.png")}:
            purpose = next((c["purpose"] for c in json.loads(expected.read_text(encoding="utf-8")).values()
                            if c["image"] == name), "")
            self.image_label.configure(text=f"{name}: {purpose}")

    def _save_clipboard_image(self, img: Image.Image) -> Path:
        folder = RUNS / "gui"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"pasted-{datetime.now():%Y%m%d-%H%M%S}.png"
        img.convert("RGB").save(path)
        return path

    def paste_clipboard(self) -> None:
        clip = ImageGrab.grabclipboard()
        if isinstance(clip, Image.Image):
            self.set_image(self._save_clipboard_image(clip))
        elif isinstance(clip, list) and clip:
            self.set_image(Path(clip[0]))
        else:
            messagebox.showinfo("Paste screenshot", "The clipboard holds no image. Copy a screenshot first "
                                                    "(e.g. Win+Shift+S), or use 'Snip screen…'.")

    def snip(self) -> None:
        """Start the Windows snipping overlay and pick up the snip from the clipboard."""
        before = self._clip_hash()
        self.iconify()
        os.startfile("ms-screenclip:")
        self.set_status("Select an area of the screen…")

        def wait(deadline=time.time() + 60):
            h = self._clip_hash()
            if h and h != before:
                self.deiconify()
                self.set_image(self._save_clipboard_image(ImageGrab.grabclipboard()))
            elif time.time() < deadline:
                self.after(400, wait)
            else:
                self.deiconify()
                self.set_status("No snip received.")

        self.after(800, wait)

    @staticmethod
    def _clip_hash() -> str | None:
        clip = ImageGrab.grabclipboard()
        return hashlib.md5(clip.tobytes()).hexdigest() if isinstance(clip, Image.Image) else None

    # ------------------------------------------------------------------ actions

    def extract(self) -> None:
        if not self._need_image():
            return
        self._launch(["run", str(self.image_path), "--extract-only"], kind="extract")

    def start(self, resume: bool) -> None:
        if not self._need_image():
            return
        source = ["--from-json", str(self.extraction_json)] if self.extraction_json else [str(self.image_path)]
        args = ["run", *source]
        if resume:
            args.append("--resume")
        if self.fast.get():
            args.append("--fast")
        elif self.narrate.get():
            args += ["--narrate", "--pace", str(self.pace.get())]
        if self.confirm.get():
            args.append("--confirm")
        if not resume and not messagebox.askokcancel(
            "Run", "Fakturama must be open. The run uses mouse and keyboard - don't touch them until it finishes."):
            return
        self._launch(args, kind="resume" if resume else "run")

    def _fast_toggled(self) -> None:
        """Fast mode = no captions/pacing and fewer screenshots; every check still runs."""
        fast = self.fast.get()
        self.cb_narrate.configure(state="disabled" if fast else "normal")
        self.sp_pace.configure(state="disabled" if fast else "normal")
        if fast:
            self.narrate.set(False)
            self.set_status("Fast mode: no captions or pacing, screenshots only for milestones - all checks still run.")

    def continue_save(self) -> None:
        if self.proc and self.proc.stdin:
            self.proc.stdin.write("\n")
            self.proc.stdin.flush()
        self.btn_continue.configure(state="disabled")
        if self.hide.get():
            self.iconify()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            self.write("Stopped by user.\n", "bad")

    def open_run_folder(self) -> None:
        os.startfile(self.last_run_dir or RUNS)

    # ------------------------------------------------------------------ subprocess plumbing

    def _launch(self, args: list[str], kind: str) -> None:
        if self.proc and self.proc.poll() is None:
            return
        self.kind = kind
        self.log.delete("1.0", "end")
        self.write(f"$ fakturama_i2c {' '.join(args)}\n", "step")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "fakturama_i2c", *args], cwd=ROOT, env=env, text=True, encoding="utf-8",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()
        self._busy(True)
        self.set_status({"extract": "Extracting (OCR + LLM)…", "run": "Running…", "resume": "Resuming…"}[kind])
        if kind != "extract" and self.hide.get():
            self.after(600, self.iconify)

    def _pump(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            self.lines.put(line)
        proc.wait()
        self.lines.put(None)

    def _drain(self) -> None:
        try:
            while True:
                line = self.lines.get_nowait()
                if line is None:
                    self._finished()
                    break
                self._handle(ANSI.sub("", line))
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _handle(self, line: str) -> None:
        if NOISE.search(line):
            return
        if self.kind == "extract" and re.match(r'^\s*([{}\[\]]|"[a-z_]+":)', line):
            return  # the extraction JSON is shown as a table above
        m = re.search(r"report: (.+report\.json)", line)
        if m:
            self.last_run_dir = (ROOT / m.group(1).strip()).parent
        if "about to Save" in line:
            self.deiconify()
            self.lift()
            self.btn_continue.configure(state="normal")
            self.set_status("Paused before Save - click 'Continue (Save)'.")
        tag = ("step" if line.lstrip().startswith("▶") else
               "bad" if re.search(r"FAILED|Traceback|Error", line) else
               "warn" if re.search(r"MANUAL|STOPPED", line) else
               "done" if line.startswith("DONE") else
               "missing" if "MISSING" in line else
               "ok" if re.search(r"\bOK\b|FOUND", line) else None)
        if " INFO " in line and not tag:
            return  # keep the log readable: logger chatter is in runs/<ts>/steps.jsonl anyway
        self.write(line if line.endswith("\n") else line + "\n", tag)

    def _finished(self) -> None:
        code = self.proc.returncode if self.proc else None
        self._busy(False)
        self.deiconify()
        self.lift()
        if self.kind == "extract":
            self._show_extraction()
            return
        msg = {0: "Done - Order and Invoice saved and verified.",
               2: "Stopped for manual review - fix the issue in Fakturama, then click 'Resume'.",
               1: "Failed - see the log and the run folder."}.get(code, f"Exited with code {code}.")
        self.set_status(msg)
        (messagebox.showinfo if code == 0 else messagebox.showwarning)("Fakturama Image-to-Cash", msg)

    def _show_extraction(self) -> None:
        if not self.last_run_dir or not (self.last_run_dir / "extraction.json").exists():
            self.set_status("Extraction failed - see the log (the order image could not be read reliably).")
            return
        self.extraction_json = self.last_run_dir / "extraction.json"
        e = json.loads(self.extraction_json.read_text(encoding="utf-8"))
        self.tree.delete(*self.tree.get_children())

        def add(parent, label, value=""):
            return self.tree.insert(parent, "end", text=label, values=(value,), open=True)

        add("", "External reference", e["external_reference"])
        add("", "Order date", e["order_date"])
        c = e["customer"]
        cust = add("", "Customer", c["company"])
        for k, v in (("Contact", f"{c['first_name']} {c['last_name']}"), ("Alias", c["alias"]),
                     ("E-mail", c["email"]), ("Phone", c["phone"])):
            add(cust, k, v)
        for key, label in (("billing_address", "Billing address"), ("delivery_address", "Delivery address")):
            a = e[key]
            add("", label, f"{a['street']}, {a['zip']} {a['city']}, {a['country']}")
        p = e["payment"]
        add("", "Payment", f"{p['method']} - {p['status']}" + (f" on {p['date']}" if p.get("date") else ""))
        items = add("", "Items", f"{len(e['items'])} line(s)")
        for i in e["items"]:
            add(items, i["sku"], f"{i['description']}   {i['quantity']} x {i['unit_net']}  -{i['discount_pct']}%"
                                  f"  VAT {i['vat_pct']}%  = {i['line_net']}")
        t = e["totals"]
        add("", "Totals", f"Net {t['net']}   VAT {t['vat']}   Gross {t['gross']} {e['currency']}")
        self.set_status("Extraction checked (grounded in the image, totals reconcile). Click 'Run' to enter it in Fakturama.")

    # ------------------------------------------------------------------ helpers

    def _busy(self, busy: bool) -> None:
        for b in (self.btn_extract, self.btn_run, self.btn_resume):
            b.configure(state="disabled" if busy else "normal")
        self.btn_stop.configure(state="normal" if busy else "disabled")
        if not busy:
            self.btn_continue.configure(state="disabled")

    def _need_image(self) -> bool:
        if self.image_path is None:
            messagebox.showinfo("Order image", "Choose an order image first (open, paste or snip).")
            return False
        return True

    def write(self, text: str, tag: str | None = None) -> None:
        self.log.insert("end", text, tag or ())
        self.log.see("end")

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)


def main() -> None:
    try:  # crisp text on scaled (HiDPI) displays
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    App().mainloop()


if __name__ == "__main__":
    main()
