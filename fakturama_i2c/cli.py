"""Command line entry point.

    python -m fakturama_i2c run IMAGE                 # full flow
    python -m fakturama_i2c run IMAGE --extract-only  # stop after PDF 1.1-1.2
    python -m fakturama_i2c run --from-json runs/<ts>/extraction.json [--confirm]
    python -m fakturama_i2c run IMAGE --resume        # continue after a manual review
    python -m fakturama_i2c gui                       # desktop front-end
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import settings
from .errors import AutomationError, ManualReviewRequired
from .extraction import pipeline
from .ui.evidence import Evidence


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # captions use symbols; a cp1252 pipe must not crash a run
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="fakturama_i2c")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="image -> verified Order + linked Invoice")
    src = run.add_mutually_exclusive_group(required=True)
    src.add_argument("image", nargs="?", type=Path, help="order image (png/jpg)")
    src.add_argument("--from-json", type=Path, help="skip OCR/LLM: extraction.json or raw_order.json")
    run.add_argument("--extract-only", action="store_true", help="stop after extraction")
    run.add_argument("--confirm", action="store_true", help="pause before every Save (for recordings)")
    run.add_argument("--resume", action="store_true", help="continue after a manual review (never a second Order)")
    run.add_argument("--fast", action="store_true",
                     help="no captions/pacing, screenshots only for failures and milestones (all checks still run)")
    run.add_argument("--narrate", action="store_true", help="on-screen captions + console banners per PDF step")
    run.add_argument("--pace", type=float, default=1.5, help="seconds to pause after each step with --narrate")
    sub.add_parser("gui", help="small desktop front-end (pick image, extract, run, resume)")
    args = ap.parse_args(argv)
    if args.cmd == "gui":
        from .gui import main as gui_main

        gui_main()
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "paddle", "ppocr", "paddlex"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    evidence = Evidence.new_run(settings.runs_dir)
    evidence.fast = args.fast
    if args.fast:
        args.narrate = False
    if args.narrate:
        from .workflow.narration import Narrator, summarize

        evidence.narrator, evidence.summarize = Narrator(pace=args.pace), summarize
    status, order = "failed", None
    try:
        if evidence.narrator:
            evidence.narrator.begin("1.1-1.2")
        order = pipeline.load(args.from_json) if args.from_json else pipeline.extract(args.image, settings, evidence.dir)
        evidence.record("1.1-1.2 extract", "ok", reference=order.external_reference, items=len(order.items))
        if args.extract_only:
            print(order.model_dump_json(indent=2))
            status = "extracted"
            return 0

        from .workflow.orchestrator import Orchestrator  # UIA imports only when needed

        result = Orchestrator(order, evidence, confirm=args.confirm, resume=args.resume).run()
        status = "completed"
        print(f"\nDONE  Order {result.order_no}  ->  Invoice {result.invoice_no}  ({evidence.dir})")
        return 0
    except ManualReviewRequired as exc:
        status = "manual_review"
        evidence.record(exc.step, "manual_review", reason=exc.reason, **exc.evidence)
        print(f"\nSTOPPED FOR MANUAL REVIEW: {exc}", file=sys.stderr)
        return 2
    except AutomationError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        report = evidence.write_report(
            status=status,
            source=str(args.from_json or args.image),
            extraction=order.model_dump(mode="json") if order else None,
        )
        print(f"report: {report}")


if __name__ == "__main__":
    sys.exit(main())
