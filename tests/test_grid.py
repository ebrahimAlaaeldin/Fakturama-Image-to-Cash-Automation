"""Grid reading on a synthetic NatTable-like image with a fake recognizer (no OCR, no UI)."""

import numpy as np
from PIL import Image, ImageDraw

from fakturama_i2c.ui.grid import build_grid, detect_lines

COLS = [0, 50, 175, 300]  # row-number column, then 2 data columns + right border at 300
HEADER_BOTTOM, ROW_BOTTOM = 24, 49


def make_grid(cells: dict[tuple[int, int], str]) -> tuple[Image.Image, dict]:
    """Draw grid lines; remember which text sits in which cell for the fake recognizer."""
    img = Image.new("RGB", (600, 200), "white")
    d = ImageDraw.Draw(img)
    for x in COLS[1:]:
        d.line([(x, 0), (x, ROW_BOTTOM)], fill=(120, 120, 120))
    for y in (HEADER_BOTTOM, ROW_BOTTOM):
        d.line([(0, y), (COLS[-1], y)], fill=(120, 120, 120))
    lookup = {}
    for (row, col), text in cells.items():
        y0 = 0 if row == 0 else HEADER_BOTTOM
        x0 = COLS[col]
        d.rectangle([x0 + 10, y0 + 6, x0 + 30, y0 + 16], fill="black")  # "ink" so the cell isn't blank
        lookup[(x0, y0)] = text
    return img, lookup


def test_detect_lines():
    img, _ = make_grid({(0, 1): "Company"})
    xs, ys = detect_lines(np.asarray(img.convert("L")).astype(int))
    assert xs == [50, 175, 300]
    assert ys == [HEADER_BOTTOM, ROW_BOTTOM]


def test_build_grid_keys_cells_by_header_and_locates_rows():
    img, _ = make_grid({(0, 1): "Company", (0, 2): "ZIP", (1, 1): "Northstar", (1, 2): "10117"})
    texts = iter(["Company", "ZIP", "Northstar", "10117"])  # reading order: header row, then data row
    grid = build_grid(img, ["Company", "ZIP"], lambda crops: [(next(texts), 0.97) for _ in crops], origin=(1000, 500))
    assert grid.headers == ["Company", "ZIP"]
    assert len(grid.rows) == 1
    assert grid.rows[0].cells == {"Company": "Northstar", "ZIP": "10117"}
    assert grid.rows[0].center == (1000 + (50 + 175) // 2, 500 + (HEADER_BOTTOM + ROW_BOTTOM) // 2)


def test_empty_list_has_no_rows():
    img = Image.new("RGB", (600, 200), "white")
    d = ImageDraw.Draw(img)
    for x in COLS[1:]:
        d.line([(x, 0), (x, HEADER_BOTTOM)], fill=(120, 120, 120))
    d.line([(0, HEADER_BOTTOM), (COLS[-1], HEADER_BOTTOM)], fill=(120, 120, 120))
    grid = build_grid(img, ["Company"], lambda crops: [("Company", 0.99) for _ in crops])
    assert grid.rows == []


# --------------------------------------------------------------------------- real captures
# Screenshots of live Fakturama grids: three different header styles (light header with dark
# separators, dark header with light separators, near-invisible separators over a selection).
import pytest  # noqa: E402

from tests.conftest import FIXTURES  # noqa: E402

REAL = {
    "address_dialog.png": [48, 174, 298, 424, 642, 768, 892, 1018, 1142, 1268],
    "products_list.png": [124, 249, 473, 598, 723, 848],
    "order_items.png": [49, 89, 187, 246, 406, 496, 621, 686, 759, 824],
    "documents_selected_row.png": [124, 249, 374, 694, 853, 978, 1103, 1228],
}


@pytest.mark.parametrize("name,expected", REAL.items())
def test_detect_lines_on_real_captures(name, expected):
    gray = np.asarray(Image.open(FIXTURES / "grids" / name).convert("L")).astype(int)
    xs, ys = detect_lines(gray)
    assert all(abs(a - b) <= 2 for a, b in zip(xs, expected)) and len(xs) == len(expected)
    assert ys[0] in (23, 24, 25)


def test_merged_rows_are_split():
    from fakturama_i2c.ui.grid import _split_merged

    assert _split_merged([(24, 49), (49, 99)]) == [(24, 49), (49, 74), (74, 99)]
    assert _split_merged([(24, 49), (49, 74)]) == [(24, 49), (49, 74)]


def test_only_two_rows_merged_uses_header_height():
    from fakturama_i2c.ui.grid import _split_merged

    assert _split_merged([(24, 74)], header_height=24) == [(24, 49), (49, 74)]


def test_small_header_does_not_halve_rows():
    from fakturama_i2c.ui.grid import _split_merged

    rows = [(12, 37), (37, 62)]  # header line found at y=12: rows must stay whole
    assert _split_merged(rows, header_height=12) == rows


def test_selected_row_does_not_merge_rows():
    """Blue selection + dark header: row lines come from thin grid lines and the row pitch."""
    gray = np.asarray(Image.open(FIXTURES / "grids" / "documents_selected_row.png").convert("L")).astype(int)
    _, ys = detect_lines(gray)
    assert ys[:3] == [24, 49, 74]


def test_only_requested_columns_are_read():
    img, _ = make_grid({(0, 1): "Company", (0, 2): "ZIP", (1, 1): "Northstar", (1, 2): "10117"})
    calls = []

    def rec(crops):
        calls.append(len(crops))
        return [(t, 0.99) for t in (["Company", "ZIP"] if len(calls) == 1 else ["10117"])]

    grid = build_grid(img, ["Company", "ZIP"], rec, only=["ZIP"])
    assert calls == [2, 1]  # header batch, then only the ZIP cell
    assert grid.rows[0].cells == {"ZIP": "10117"}
