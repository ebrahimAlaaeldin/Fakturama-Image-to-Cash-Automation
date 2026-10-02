"""Turn OCR tokens back into visual rows so table columns survive the trip to the LLM.

Plain OCR output is a bag of lines; '2 / pcs / 250.00 / 10% / 19%' loses which column each
number belongs to. We group tokens whose vertical centres are close into one row, sort each
row left->right and print the x position, so header and value columns line up by x.
"""

from __future__ import annotations

from statistics import median

from .ocr import OcrToken


def group_rows(tokens: list[OcrToken], tolerance: float = 0.5) -> list[list[OcrToken]]:
    """Cluster tokens into rows; ``tolerance`` is a fraction of the median token height."""
    if not tokens:
        return []
    limit = median(t.h for t in tokens) * tolerance
    rows: list[list[OcrToken]] = []
    for tok in sorted(tokens, key=lambda t: t.cy):
        if rows and abs(tok.cy - _row_cy(rows[-1])) <= limit:
            rows[-1].append(tok)
        else:
            rows.append([tok])
    return [sorted(r, key=lambda t: t.x0) for r in rows]


def _row_cy(row: list[OcrToken]) -> float:
    return sum(t.cy for t in row) / len(row)


def render(rows: list[list[OcrToken]]) -> str:
    """One line per visual row: ``y=412 | x=40 "SKU" | x=180 "Description" ...``."""
    lines = []
    for row in rows:
        cells = " | ".join(f'x={t.x0:.0f} "{t.text}"' for t in row)
        lines.append(f"y={_row_cy(row):.0f} | {cells}")
    return "\n".join(lines)
