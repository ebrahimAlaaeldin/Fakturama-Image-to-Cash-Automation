"""PDF 3.1-3.17: for every source item select the Product (creating VAT + Product if needed),
then complete the item line."""

from __future__ import annotations

from ...errors import ManualReviewRequired
from ...fakturama import labels as L
from ...fakturama.master_data import ProductEditor, VatList, fill_vat, is_standard_vat_code, vat_code
from ...extraction.normalize import key
from ...fakturama.items_grid import ItemsGrid
from ...models import LineItem
from .. import pricing
from ..context import RunContext, outcome
from ..matching import Match, MatchKind, match_product, match_vat, vat_name
from .lines import complete_line


def resolve_items(ctx: RunContext) -> None:
    """3.1: every extracted row, in source order."""
    for line_no, item in enumerate(ctx.order.items, start=1):
        resolve_product(ctx, item)
        complete_line(ctx, item, line_no)


def resolve_product(ctx: RunContext, item: LineItem) -> None:
    m = _search_and_select(ctx, item, "3.2-3.3")
    if m.kind is MatchKind.NONE:
        ensure_vat(ctx, item)
        create_product(ctx, item)
        m = _search_and_select(ctx, item, "3.12")
        if m.kind is not MatchKind.EXACT:
            raise ManualReviewRequired("3.12", f"new Product {item.sku} not selectable from the Order", {"reason": m.reason})


def _search_and_select(ctx: RunContext, item: LineItem, step: str) -> Match:
    with ctx.step(f"{step} select Product", sku=item.sku):
        lines = ItemsGrid(ctx.editor)
        before = [r.get("Item No.") for r in lines.rows()]
        dlg = ctx.editor.open_product_selector()
        records = dlg.search(item.sku, step)
        if dlg.closed:
            return _verify_auto_selected(ctx, lines, before, item, step)
        m = match_product(records, item)
        ctx.evidence.record(f"{step} product match", outcome(m), sku=item.sku, rows=records, reason=m.reason)
        if m.kind is MatchKind.EXACT:
            dlg.choose(m.index)
        else:
            dlg.cancel()
        if m.kind is MatchKind.AMBIGUOUS:
            raise ManualReviewRequired(step, m.reason, {"candidates": m.candidates})
        if m.kind is MatchKind.NONE and any(r.confidence < 0.8 for r in dlg.rows):
            raise ManualReviewRequired(step, "low-confidence OCR rows; cannot rule out a match", {"rows": records})
    return m


def _verify_auto_selected(ctx: RunContext, lines: ItemsGrid, before: list[str], item: LineItem, step: str) -> Match:
    """The selector closed itself (single search hit). Accept only if exactly one new line was
    added and its Item No. is exactly the SKU - otherwise the wrong product may be on the Order."""
    after = [r.get("Item No.") for r in lines.rows()]
    added = list(after)
    for sku in before:
        if sku in added:
            added.remove(sku)
    ctx.evidence.record(f"{step} product auto-selected", "found" if added else "missing", sku=item.sku, added=added)
    if len(added) == 1 and key(added[0]) == key(item.sku):
        return Match(MatchKind.EXACT, row={"item_number": added[0]}, index=None)
    raise ManualReviewRequired(step, f"selector closed itself; lines added: {added}", {"expected": item.sku})


def ensure_vat(ctx: RunContext, item: LineItem) -> None:
    """3.4-3.6: Data > VATs. Reuse one exact row (Name, Value and code S), stop on conflict,
    create when missing."""
    name = vat_name(item.vat_pct)
    with ctx.step("3.4 VAT lookup", vat=name):
        vats = VatList(ctx.app)
        records = vats.search(name, "3.4")
        m = match_vat(records, item.vat_pct)
        ctx.evidence.record("3.5 VAT match", outcome(m), rows=records, reason=m.reason)
    if m.kind is MatchKind.AMBIGUOUS:
        raise ManualReviewRequired("3.5", m.reason, {"candidates": m.candidates})
    if m.kind is MatchKind.EXACT:
        with ctx.step("3.5 VAT code check", vat=name):
            editor = vats.open_row(m.index, name)  # the list does not show the E-Invoice code
            code = vat_code(editor)
            ctx.app.close_editor(editor.root)
            if not is_standard_vat_code(code):
                raise ManualReviewRequired("3.5", f"{name} exists with VAT code {code!r}, expected S", {"code": code})
        return
    with ctx.step("3.6 create VAT", vat=name):
        editor = vats.create(L.EDITOR_NEW_VAT)
        fill_vat(editor, item.vat_pct, "3.6")
        ctx.app.save(editor.root, "3.6")
        ctx.created.append(f"vat:{name}")


def create_product(ctx: RunContext, item: LineItem) -> None:
    """3.7-3.11 (the Order tab stays open)."""
    gross = pricing.gross_price(item.unit_net, item.vat_pct)
    with ctx.step("3.7 New product", sku=item.sku):
        ed = ProductEditor.new(ctx.app)
    with ctx.step("3.8-3.10 product fields", sku=item.sku, gross=gross):
        ed.fill(item.sku, item.description, gross, vat_name(item.vat_pct), "3.8")
    with ctx.step("3.11 save Product", sku=item.sku):
        ctx.app.save(ed.root, "3.11")
        ctx.created.append(f"product:{item.sku}")
    ctx.app.activate(ctx.editor.root)
