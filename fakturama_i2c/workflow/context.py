"""State shared by the stages of one run."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..fakturama.document_editor import DocumentEditor
from ..fakturama.shell import Fakturama
from ..models import OrderExtraction
from ..ui.evidence import Evidence
from .matching import Match, MatchKind


@dataclass
class RunContext:
    order: OrderExtraction
    app: Fakturama
    evidence: Evidence
    editor: DocumentEditor | None = None  # the one open Order (PDF 1.8)
    invoice: DocumentEditor | None = None
    order_no: str = ""
    invoice_no: str = ""
    created: list[str] = field(default_factory=list)  # master data created in this run

    def step(self, name: str, **details):
        return self.evidence.step(name, self.app.main, **details)


def outcome(match: Match) -> str:
    return {MatchKind.EXACT: "found", MatchKind.NONE: "missing", MatchKind.AMBIGUOUS: "ambiguous"}[match.kind]
