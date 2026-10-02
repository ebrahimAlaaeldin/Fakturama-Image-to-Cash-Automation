"""Polling helpers. Everything waits on an observable condition, never on a fixed sleep."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from ..config import settings
from ..errors import ControlNotFound

T = TypeVar("T")


def wait_until(
    probe: Callable[[], T | None],
    what: str,
    timeout: float | None = None,
    interval: float | None = None,
) -> T:
    """Call ``probe`` until it returns something truthy; exceptions count as 'not yet'."""
    timeout = settings.default_timeout if timeout is None else timeout
    interval = interval or settings.poll_interval
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while True:
        try:
            value = probe()
            if value:
                return value
        except Exception as exc:  # noqa: BLE001 - UIA throws many COM error types while UI settles
            last_exc = exc
        if time.monotonic() >= deadline:
            hint = f" (last error: {last_exc})" if last_exc else ""
            raise ControlNotFound(f"timed out after {timeout:.0f}s waiting for {what}{hint}")
        time.sleep(interval)


def wait_stable(
    snapshot: Callable[[], T],
    what: str,
    polls: int | None = None,
    timeout: float | None = None,
) -> T:
    """Return ``snapshot()`` once it gives the same value ``polls`` times in a row.

    Used after typing into a search box (PDF 2.2: 'wait for the list to stabilize').
    """
    polls = polls or settings.stable_polls
    history: list[T] = []

    def probe():
        history.append(snapshot())
        tail = history[-polls:]
        return len(tail) == polls and all(v == tail[0] for v in tail) and (tail[0],)

    return wait_until(probe, f"{what} to stabilise", timeout)[0]
