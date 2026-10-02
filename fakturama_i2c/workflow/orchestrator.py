"""The Order-first flow (PDF sections 1-5) as one continuous run, plus --resume."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import settings
from ..errors import ManualReviewRequired
from ..fakturama.shell import Fakturama
from ..models import OrderExtraction
from ..ui.evidence import Evidence
from .context import RunContext
from .stages.debtor import resolve_debtor
from .stages.invoice import complete_invoice
from .stages.order_complete import complete_order
from .stages.order_open import ensure_not_already_imported, open_order
from .stages.product import resolve_items
from .stages.resume import find_saved_documents, resume_from_order

log = logging.getLogger(__name__)

DRAFT_TITLES = ("New Order", "New Invoice")


@dataclass
class Result:
    order_no: str
    invoice_no: str
    created: list[str]


def discard_drafts(ctx: RunContext, leftovers: list[str]) -> None:
    """--resume only: close the stopped run's own unsaved document drafts. Anything else that
    is unsaved (a master-data editor a person is working in) stops the run instead."""
    others = [t for t in leftovers if t.lstrip("*") not in DRAFT_TITLES]
    if others:
        raise ManualReviewRequired("R", "save or close these editors first", {"editors": others})
    with ctx.step("R discard unsaved drafts", editors=leftovers):
        for title in leftovers:  # a background tab has no pane in UIA: bring it forward, then close it
            ctx.app.close_editor(ctx.app.show_tab(title.lstrip("*")))
        left = ctx.app.open_work()
        if left:  # a draft that is still open would be mistaken for this run's editor later
            raise ManualReviewRequired("R", "could not close the stopped run's drafts", {"editors": left})


class Orchestrator:
    def __init__(self, order: OrderExtraction, evidence: Evidence, confirm: bool = False, resume: bool = False):
        self.order = order
        self.evidence = evidence
        self.confirm = confirm
        self.resume = resume

    def run(self) -> Result:
        app = Fakturama.attach(settings, self.evidence, self.confirm)
        ctx = RunContext(order=self.order, app=app, evidence=self.evidence)
        leftovers = app.open_work()
        if leftovers and self.resume:
            discard_drafts(ctx, leftovers)
        elif leftovers:  # editors are tracked by title; a stale 'New Order' would be ambiguous
            raise ManualReviewRequired("0", "close unsaved Fakturama editors before a run", {"editors": leftovers})

        if self.resume:
            orders, invoices, view = find_saved_documents(ctx)  # row indexes; review cases already raised
            if orders:  # the Order is saved: continue from it, never create a second one
                resume_from_order(ctx, orders[0], invoices[0] if invoices else None, view)
                return self._done(ctx, resumed=True)
            # nothing saved yet: the normal flow; master data from the stopped run is reused
        else:
            ensure_not_already_imported(ctx)  # never create a second Order for the same reference

        open_order(ctx)  # 1.3-1.8
        resolve_debtor(ctx)  # 2.1-2.13 (+ 2.10.x payment method)
        resolve_items(ctx)  # 3.1-3.17 (+ 3.4-3.6 VAT)
        complete_order(ctx)  # 4.1-4.7
        complete_invoice(ctx)  # 5.1-5.6
        return self._done(ctx, resumed=False)

    def _done(self, ctx: RunContext, resumed: bool) -> Result:
        self.evidence.record("5.7 done", "ok", order=ctx.order_no, invoice=ctx.invoice_no,
                             created=ctx.created, resumed=resumed)
        return Result(ctx.order_no, ctx.invoice_no, ctx.created)
