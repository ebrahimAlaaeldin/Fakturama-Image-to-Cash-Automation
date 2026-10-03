"""Read NatTable grids, which are custom-drawn and expose no rows/cells to UI Automation.

Grounding stays UIA-first: the grid's *container* is located through UIA (live screen
rectangle), then its pixels are analysed:

1. grid lines -> column borders (from the header band) and row bands (horizontal lines)
2. every non-blank cell is cropped, padded and OCR'd on its own - cells can never merge,
   and header alignment (left/centred) does not matter
3. a cell ending in an ellipsis is truncated: double-click that column's right border
   (NatTable auto-fit) and read again

Each row carries the screen point of its centre so it can be clicked; nothing is hardcoded.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import difflib
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps
from pywinauto.base_wrapper import BaseWrapper

from ..errors import ControlNotFound, ScreenObstructed
from ..vision.ocr import ocr_images
from . import act, overlay

Recognizer = Callable[[list[Image.Image]], list[tuple[str, float]]]  # batch: crops -> (text, conf)

SCREEN_OCR_SCALE = 2.0
_ELLIPSIS = ("…", "..")  # OCR often reads the ellipsis glyph as two or three dots


@dataclass
class GridRow:
    cells: dict[str, str]
    center: tuple[int, int]  # screen coordinates, computed at runtime
    confidence: float = 1.0

    def get(self, column: str, default: str = "") -> str:
        return self.cells.get(column, default)


@dataclass
class Grid:
    headers: list[str]
    rows: list[GridRow]
    spans: dict[str, tuple[int, int]]  # column -> (left, right) x, container-relative
    header_y: int  # header band centre, container-relative

    def snapshot(self) -> tuple:
        """Hashable view for wait_stable()."""
        return tuple(tuple(sorted(r.cells.items())) for r in self.rows)


# --------------------------------------------------------------------------- pure image analysis


def _runs(mask: np.ndarray) -> list[int]:
    """Centre index of every run of true values in ``mask``."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    groups = np.split(idx, np.flatnonzero(np.diff(idx) > 2) + 1)
    return [int(round(g.mean())) for g in groups]


def _thin_lines(band: np.ndarray, contrast: int, share: float) -> np.ndarray:
    """Columns that are a 1-2px line in at least ``share`` of the band's rows: the pixel differs
    from its neighbours 2px left and right (works for dark-on-light and light-on-dark)."""
    mask = np.zeros(band.shape[1], dtype=bool)
    if band.shape[0] == 0 or band.shape[1] < 5:
        return mask
    diff = np.abs(band[:, 2:-2] - (band[:, :-4] + band[:, 4:]) / 2)
    mask[2:-2] = (diff > contrast).mean(axis=0) >= share
    return mask


def _thin_rows(gray: np.ndarray, contrast: int = 10, share: float = 0.6) -> list[int]:
    """y of horizontal 1-2px lines: pixels darker (or lighter) than BOTH the rows 2px above and
    below, across most of the width. Solid blocks (a dark header, a blue selected row) and plain
    colour edges do not qualify - only real grid lines."""
    if gray.shape[0] < 5:
        return []
    up, mid, down = gray[:-4], gray[2:-2], gray[4:]
    # differs from BOTH neighbours, in any direction: a grey line between a white row and the
    # blue selected row is lighter than one side and darker than the other (seen live).
    line = (np.abs(mid - up) > contrast) & (np.abs(mid - down) > contrast)
    mask = np.zeros(gray.shape[0], dtype=bool)
    mask[2:-2] = line.mean(axis=1) >= share
    return _runs(mask)


def _row_lines(lines: list[int]) -> list[int]:
    """NatTable rows have one fixed height: take the most common gap as the pitch and rebuild the
    boundaries a selection or the header may hide (first boundary = header bottom)."""
    gaps = [b - a for a, b in zip(lines, lines[1:]) if 12 <= b - a <= 60]
    if not gaps:
        return lines
    pitch = max(set(gaps), key=gaps.count)
    start = lines[0]
    while start - pitch >= 12:  # walk up to the header bottom
        start -= pitch
    rebuilt = list(range(start, lines[-1] + 1, pitch))
    snap = lambda y: min(lines, key=lambda l: abs(l - y)) if min(abs(l - y) for l in lines) <= 2 else y  # noqa: E731
    return [snap(y) for y in rebuilt]


def detect_lines(gray: np.ndarray, dark: int = 200, contrast: int = 12) -> tuple[list[int], list[int]]:
    """(vertical borders x, horizontal lines y) of a grid image (0=black..255=white).

    Horizontal: thin lines only, completed from the row pitch (see _row_lines). Vertical: thin
    lines in the header band *or* the body band (some header styles draw near-invisible
    separators, some bodies are partly covered by the blue selection) - either is enough.
    """
    cols = np.flatnonzero((gray < dark).any(axis=0))
    table_right = int(cols.max()) + 1 if cols.size else gray.shape[1]
    ys = _row_lines(_thin_rows(gray[:, :table_right]))
    header_bottom = next((y for y in ys if y > 4), None)
    if header_bottom is None:
        return [], ys
    header = gray[1 : max(2, header_bottom - 1), :]
    body_bottom = ys[-1] if ys[-1] > header_bottom + 8 else header_bottom
    body = gray[header_bottom + 2 : body_bottom - 1, :]
    xs = _runs(_thin_lines(header, 20, 0.8) | _thin_lines(body, contrast, 0.6))
    return xs, ys


def _split_merged(bands: list[tuple[int, int]], header_height: int | None = None) -> list[tuple[int, int]]:
    """A selected (blue) row can hide the grid line to its neighbour, so two rows arrive as one
    band of double height. Split only clear multiples (>= 1.8x) of the typical row height: the
    median band, or - with a single band - a header of plausible row height."""
    if not bands:
        return bands
    heights = sorted(b - t for t, b in bands)
    if len(bands) > 1:
        unit = heights[(len(heights) - 1) // 2]  # lower median
    elif header_height and header_height >= 18:
        unit = header_height
    else:
        return bands
    out = []
    for t, b in bands:
        n = round((b - t) / unit) if (b - t) >= 1.8 * unit else 1
        step = (b - t) / n
        out += [(round(t + i * step), round(t + (i + 1) * step)) for i in range(n)]
    return out


def build_grid(
    img: Image.Image,
    headers: Sequence[str],
    recognize: Recognizer,
    origin: tuple[int, int] = (0, 0),
    only: Sequence[str] | None = None,
) -> Grid:
    """Pure (given ``recognize``): grid image -> header-keyed rows.

    Two OCR batches: the header row, then - for the columns in ``only`` (default: all) - every
    data cell. Columns nobody checks (e.g. Picture, Description) are not OCR'd at all.
    """
    gray = np.asarray(img.convert("L")).astype(int)
    xs, ys = detect_lines(gray)
    if len(xs) < 2 or not ys:
        return Grid(list(headers), [], {}, 0)
    header_bottom = next(y for y in ys if y > 4)
    columns = list(zip([0, *xs], xs))  # leading segment = row-number column
    row_bands = _split_merged([(t, b) for t, b in zip([header_bottom, *ys], ys) if b - t > 8 and t >= header_bottom], header_bottom)

    def box(x0, x1, y0, y1):
        cell = gray[y0 + 2 : y1 - 1, x0 + 2 : x1 - 1]
        return None if cell.size == 0 or cell.std() < 4 else (x0 + 2, y0 + 2, x1 - 1, y1 - 1)  # None = blank

    def read(boxes):
        todo = [bx for bx in boxes if bx]
        texts = iter(recognize([img.crop(bx) for bx in todo]))
        return [next(texts) if bx else ("", 1.0) for bx in boxes]

    names = [_header_name(t, headers) for t, _ in read([box(x0, x1, 0, header_bottom) for x0, x1 in columns])]
    wanted = [i for i, n in enumerate(names) if n and (only is None or n in only)]
    cells_read = read([box(*columns[i], top, bottom) for top, bottom in row_bands for i in wanted])

    rows = []
    for r, (top, bottom) in enumerate(row_bands):
        chunk = cells_read[r * len(wanted) : (r + 1) * len(wanted)]
        cells = {names[i]: text for i, (text, _) in zip(wanted, chunk)}
        if not any(cells.values()):
            continue
        confs = [conf for text, conf in chunk if text]
        first = columns[1]
        center = (origin[0] + (first[0] + first[1]) // 2, origin[1] + (top + bottom) // 2)
        rows.append(GridRow(cells, center, min(confs, default=0.0)))
    spans = {n: c for n, c in zip(names, columns) if n}
    return Grid([n for n in names if n], rows, spans, header_bottom // 2)


def _norm(s: str) -> str:
    return "".join(s.split()).casefold().rstrip(".:")


def _header_name(text: str, headers: Sequence[str]) -> str:
    """Map an OCR'd header to the expected caption; headers are a closed vocabulary, so a
    near miss ('Oty.' for 'Qty.') is safe to snap. Unknown headers keep their OCR text."""
    if not text:
        return ""
    wanted = {_norm(h): h for h in headers}
    close = difflib.get_close_matches(_norm(text), list(wanted), n=1, cutoff=0.6)
    return wanted[close[0]] if close else text


def ocr_cells(crops: list[Image.Image]) -> list[tuple[str, float]]:
    """Batch OCR of single-cell crops: pad (the detector needs margin), upscale (UI fonts ~12px)."""
    padded = [ImageOps.expand(c.convert("RGB"), border=12, fill="white") for c in crops]
    out = []
    for tokens in ocr_images(padded, scale=SCREEN_OCR_SCALE, fast=True):
        tokens = sorted(tokens, key=lambda t: t.x0)
        out.append((" ".join(t.text for t in tokens), min((t.conf for t in tokens), default=0.0)))
    return out


# --------------------------------------------------------------------------- live grids


def grid_container(root: BaseWrapper) -> BaseWrapper:
    """The NatTable canvas: to UIA it is the largest visible Pane without children."""
    panes = [p for p in root.descendants(control_type="Pane") if p.is_visible() and not p.children()]
    if not panes:
        raise ControlNotFound("no grid canvas found")
    return max(panes, key=lambda p: p.rectangle().width() * p.rectangle().height())


def _ensure_unobstructed(container: BaseWrapper, rect) -> None:
    """The grid is read from screen pixels, so any other application's window on top of it (a
    browser's 'is sharing your screen' bar, a chat popup) would be OCR'd as rows. Ask Windows
    which window is topmost at points across the grid and stop with its title if it isn't ours."""
    user32 = ctypes.windll.user32
    own = {container.process_id(), os.getpid()}
    if overlay._active is not None and getattr(overlay._active, "_proc", None):
        own.add(overlay._active._proc.pid)
    for fx in (0.1, 0.35, 0.65, 0.9):
        for fy in (0.15, 0.5, 0.85):
            point = ctypes.wintypes.POINT(int(rect.left + fx * rect.width()), int(rect.top + fy * rect.height()))
            hwnd = user32.GetAncestor(user32.WindowFromPoint(point), 2)  # GA_ROOT: the top-level window
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if hwnd and pid.value not in own:
                title = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title, 256)
                raise ScreenObstructed(title.value or f"a window of process {pid.value}")


def read_grid(container: BaseWrapper, headers: Sequence[str], autofit: bool = True,
              only: Sequence[str] | None = None) -> Grid:
    """Screenshot + read the grid; auto-fit truncated columns once and re-read."""
    act.scroll_into_view(container)  # editors clip the grid inside their scrolled area
    act.park_mouse(container)  # a hover tooltip over the grid would be OCR'd as a row
    rect = container.rectangle()
    with overlay.hidden():  # a recording caption on top of the grid would be OCR'd as rows
        _ensure_unobstructed(container, rect)
        image = container.capture_as_image()
    grid = build_grid(image, headers, ocr_cells, origin=(rect.left, rect.top), only=only)
    truncated = {n for r in grid.rows for n, t in r.cells.items() if t.rstrip().endswith(_ELLIPSIS)}
    if not autofit or not truncated:
        return grid
    for name in truncated:
        right = grid.spans[name][1]
        act.click_point((rect.left + right, rect.top + grid.header_y), double=True)
        time.sleep(0.3)
    return read_grid(container, headers, autofit=False, only=only)
