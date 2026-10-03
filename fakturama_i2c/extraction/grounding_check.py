"""Anti-hallucination check: every value the LLM returned must be present in the OCR text.

Because the LLM is instructed to copy strings verbatim, a value that cannot be found in the
OCR output was invented (or mis-copied) and the run must stop. Values found only in
low-confidence tokens are reported too - a 0.6-confidence '250.00' is not trustworthy.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

from ..models import RawOrder
from ..vision.ocr import OcrToken

_WS = re.compile(r"\s+")


def _compact(text: str) -> str:
    return _WS.sub("", text).casefold()


def iter_values(raw: RawOrder) -> Iterator[tuple[str, str]]:
    """(field path, value) for every leaf string of the raw model."""

    def walk(prefix: str, obj) -> Iterator[tuple[str, str]]:
        if isinstance(obj, str):
            yield prefix, obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                yield from walk(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from walk(f"{prefix}[{i}]", v)

    yield from walk("", raw.model_dump())


def check_grounding(raw: RawOrder, tokens: list[OcrToken], min_conf: float) -> list[str]:
    """Return issues; empty list == every value is backed by confident OCR text."""
    haystack = "".join(_compact(t.text) for t in tokens)
    compact_tokens = [(_compact(t.text), t.conf) for t in tokens]
    issues: list[str] = []
    for path, value in iter_values(raw):
        needle = _compact(value)
        if not needle:
            continue
        if needle not in haystack:
            issues.append(f"{path}={value!r} not found in OCR text")
            continue
        sources = [conf for text, conf in compact_tokens if text and (text in needle or needle in text)]
        if sources and max(sources) < min_conf:
            issues.append(f"{path}={value!r} only backed by low-confidence OCR ({max(sources):.2f})")
    return issues


def _strip_accents(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c))


def accent_conflicts(tokens: list[OcrToken]) -> list[str]:
    """Words OCR read both with and without accents ('Müller' and 'Muller') in the same image.

    On blurry photos the recogniser drops umlaut dots with high confidence, and not consistently.
    A name written two ways can't be trusted either way: creating 'Muller & Sohne GmbH' would
    duplicate an existing Debtor, so the run stops for a person to check the image."""
    seen: dict[str, set[str]] = {}
    for t in tokens:
        for word in re.findall(r"[^\W\d_]{3,}", t.text):
            seen.setdefault(_strip_accents(word).casefold(), set()).add(word.casefold())
    return [f"OCR read {' / '.join(sorted(forms))!s} - accents are unreliable in this image"
            for plain, forms in sorted(seen.items())
            if len(forms) > 1 and plain in forms and any(f != plain for f in forms)]
