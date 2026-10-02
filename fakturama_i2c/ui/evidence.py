"""Per-step evidence: screenshots + a JSONL log + a final report.json in runs/<timestamp>/."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from PIL import ImageGrab

log = logging.getLogger(__name__)


class Evidence:
    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self.shots = run_dir / "screenshots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self._log = (run_dir / "steps.jsonl").open("a", encoding="utf-8")
        self._n = 0
        self.steps: list[dict] = []
        self.fast = False  # --fast: screenshots only for failures and milestones
        self.narrator = None  # optional: begin(step) / result(step, status, summary), see --narrate
        self.summarize = lambda step, status, details: ""

    @staticmethod
    def new_run(base: Path) -> Evidence:
        return Evidence(base / datetime.now().strftime("%Y%m%d-%H%M%S"))

    def screenshot(self, label: str, window=None) -> str:
        self._n += 1
        path = self.shots / f"{self._n:03d}-{_slug(label)}.png"
        try:
            img = window.capture_as_image() if window is not None else ImageGrab.grab(all_screens=True)
            img.save(path)
        except Exception as exc:  # noqa: BLE001 - evidence must never break the run
            log.warning("screenshot failed: %s", exc)
            return ""
        return str(path.relative_to(self.dir))

    def record(self, step: str, status: str, **details) -> None:
        entry = {"ts": time.strftime("%H:%M:%S"), "step": step, "status": status, **details}
        self.steps.append(entry)
        self._log.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
        self._log.flush()
        log.info("%-8s %s %s", status.upper(), step, {k: v for k, v in details.items() if k != "screenshot"})
        if self.narrator:
            self.narrator.result(step, status, self.summarize(step, status, details))

    @contextmanager
    def step(self, step: str, window=None, **details):
        """Wrap one PDF step: screenshot after it, record ok/failed with the exception text."""
        started = time.monotonic()
        if self.narrator:
            self.narrator.begin(step)
        try:
            yield
        except Exception as exc:
            shot = self.screenshot(f"{step}-FAILED", window)
            self.record(step, "failed", error=str(exc), screenshot=shot, **details)
            raise
        shot = self.screenshot(step, window) if self._worth_a_screenshot(step) else ""
        self.record(step, "ok", seconds=round(time.monotonic() - started, 1), screenshot=shot, **details)

    def _worth_a_screenshot(self, step: str) -> bool:
        """In fast mode keep the milestones: saves, the Documents checks and the final payment check."""
        return not self.fast or any(k in step.lower() for k in ("save", "documents", "persisted", "done", "addresses"))

    def write_report(self, **summary) -> Path:
        path = self.dir / "report.json"
        path.write_text(json.dumps({**summary, "steps": self.steps}, indent=2, default=str), encoding="utf-8")
        self._log.close()
        try:
            from .report_html import render

            render(self.dir)  # report.html next to report.json
        except Exception as exc:  # noqa: BLE001 - a report problem must never fail the run
            log.warning("report.html not written: %s", exc)
        if self.narrator:
            self.narrator.close()
        return path


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-." else "-" for c in text)[:60].strip("-")
