"""report.html for a run: what happened, step by step, in a form a reviewer reads in 30 seconds.

Written next to report.json at the end of every run; regenerate for an old run with
    python -m fakturama_i2c.ui.report_html runs/<ts>
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

STATUS_STYLE = {
    "ok": ("✔", "ok"), "found": ("✔", "ok"), "missing": ("+", "info"), "conflict": ("!", "warn"),
    "ambiguous": ("!", "warn"), "manual_review": ("⏸", "warn"), "failed": ("✖", "bad"),
}
OUTCOME = {
    "completed": ("Completed - Order and Invoice saved and verified", "ok"),
    "manual_review": ("Stopped for manual review", "warn"),
    "extracted": ("Extraction only", "info"),
    "failed": ("Failed", "bad"),
}
DETAIL_KEYS = ("reason", "error", "note", "method", "sku", "number", "value", "vat", "search", "gross", "qty",
               "discount", "price", "expected", "fakturama_set", "now", "orders", "others", "decimal_separator")

CSS = """
:root{--ok:#1a7f37;--warn:#9a6700;--bad:#cf222e;--info:#0969da;--line:#d0d7de;--muted:#57606a}
body{font:14px/1.45 "Segoe UI",system-ui,sans-serif;margin:0;background:#f6f8fa;color:#1f2328}
header{background:#0f1720;color:#fff;padding:18px 28px}header h1{margin:0;font-size:20px}
header .sub{color:#9fb0c3;margin-top:4px}
main{padding:20px 28px;max-width:1200px}
.badge{display:inline-block;padding:3px 10px;border-radius:12px;font-weight:600;color:#fff}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.info{color:var(--info)}
.badge.ok{background:var(--ok);color:#fff}.badge.warn{background:var(--warn);color:#fff}
.badge.bad{background:var(--bad);color:#fff}.badge.info{background:var(--info);color:#fff}
.cards{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0}
.card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px 16px;min-width:170px}
.card b{display:block;font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid var(--line);border-radius:8px}
th,td{padding:7px 10px;border-bottom:1px solid #eaeef2;text-align:left;vertical-align:top}
th{background:#f6f8fa;font-size:12px;color:var(--muted);text-transform:uppercase}
td.s{width:24px;font-weight:700}td.t{color:var(--muted);white-space:nowrap}
td.d{color:var(--muted);font-size:12.5px}
img.thumb{width:150px;border:1px solid var(--line);border-radius:4px}
h2{font-size:16px;margin:26px 0 10px}
"""


DECISION = {"found": "exact match → select it", "missing": "no exact match → create it",
            "ambiguous": "conflicting rows → stop for manual review", "conflict": "conflicting definition → stop"}


def _detail(step: dict) -> str:
    parts = []
    if ("match" in step.get("step", "") or "definition" in step.get("step", "")) and step.get("status") in DECISION:
        parts.append(DECISION[step["status"]])
    for k in DETAIL_KEYS:
        if k in step and step[k] not in (None, "", []):
            v = step[k]
            parts.append(f"{k}: {v if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False)[:160]}")
    if "rows" in step and isinstance(step["rows"], list):
        parts.append(f"{len(step['rows'])} row(s) read from the list")
    return " · ".join(parts)


def render(run_dir: Path) -> Path:
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    steps = report.get("steps", [])
    e = report.get("extraction") or {}
    title, cls = OUTCOME.get(report.get("status", ""), (report.get("status", "?"), "info"))
    done = next((s for s in steps if s.get("step") == "5.7 done"), {})
    seconds = sum(s.get("seconds", 0) for s in steps)

    rows = []
    for s in steps:
        icon, scls = STATUS_STYLE.get(s.get("status", ""), ("·", "info"))
        shot = s.get("screenshot")
        img = f'<a href="{html.escape(shot)}"><img class="thumb" src="{html.escape(shot)}"></a>' if shot else ""
        t = f'{s["seconds"]}s' if "seconds" in s else ""
        rows.append(f'<tr><td class="s {scls}">{icon}</td><td>{html.escape(s.get("step", ""))}</td>'
                    f'<td class="t">{s.get("ts", "")} {t}</td><td class="d">{html.escape(_detail(s))}</td><td>{img}</td></tr>')

    cards = [("Outcome", f'<span class="badge {cls}">{html.escape(title)}</span>')]
    if e:
        cards += [("Reference", e.get("external_reference", "")), ("Customer", e.get("customer", {}).get("company", "")),
                  ("Gross", f'{e.get("totals", {}).get("gross", "")} {e.get("currency", "")}'),
                  ("Payment", f'{e.get("payment", {}).get("method", "")} · {e.get("payment", {}).get("status", "")}')]
    if done:
        cards += [("Order", done.get("order", "")), ("Invoice", done.get("invoice", "")),
                  ("Created", ", ".join(done.get("created", [])) or "-"), ("Resumed", "yes" if done.get("resumed") else "no")]
    cards.append(("Step time", f"{seconds:.0f} s"))
    card_html = "".join(f'<div class="card"><b>{html.escape(k)}</b>{v if k == "Outcome" else html.escape(str(v))}</div>'
                        for k, v in cards)

    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Run {html.escape(run_dir.name)}</title>
<style>{CSS}</style></head><body>
<header><h1>Fakturama Image-to-Cash · run {html.escape(run_dir.name)}</h1>
<div class="sub">source: {html.escape(str(report.get("source", "")))}</div></header>
<main><div class="cards">{card_html}</div>
<h2>Steps (PDF numbering)</h2>
<table><tr><th></th><th>Step</th><th>Time</th><th>Decision / detail</th><th>Screenshot</th></tr>{"".join(rows)}</table>
<p class="d">Raw data: report.json, steps.jsonl; extraction artefacts: ocr_rows.txt, raw_order.json, extraction.json.</p>
</main></body></html>"""
    out = run_dir / "report.html"
    out.write_text(page, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(render(Path(sys.argv[1])))
