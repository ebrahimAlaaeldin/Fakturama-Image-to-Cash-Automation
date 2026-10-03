"""Groq (gpt-oss-120b) maps layout-aware OCR text onto the RawOrder schema.

Text-only: the model never sees pixels, so it can only reorganise what OCR read. It must
copy values verbatim; normalisation and arithmetic happen in Python afterwards.
"""

from __future__ import annotations

import json
import re
import logging

from openai import (APIConnectionError, APITimeoutError, AuthenticationError, BadRequestError, OpenAI,
                    PermissionDeniedError, RateLimitError)

from ..config import Settings
from ..errors import ExtractionError
from ..models import RawOrder

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You convert OCR output of a single sales order document into JSON.

The OCR text is grouped into visual rows. Each row starts with its vertical position (y=...),
followed by the text fragments of that row with their horizontal position (x=...).
Labels usually sit directly above their value (same x, smaller y). Table cells belong to the
column whose header has the closest x position.

Rules:
- Copy every value EXACTLY as it appears in the OCR text (same characters, same formatting).
  Do not translate, reformat, compute, round, or add currency symbols.
- Never invent a value. If a field is genuinely absent, return an empty string.
- Include every item row of the items table, in source order; skip empty table rows.
- Labels/headers themselves are never values.
- An address block has separate lines: copy the postal code into "zip" and the town into "city"
  (the line "10117 Berlin" gives zip "10117" and city "Berlin").
- Every labelled field in the document has a value (e.g. CUSTOMER ALIAS) - do not leave it empty.
- OCR sometimes drops the space between two words ("BankTransfer", "Vol.2"). In names, descriptions,
  street lines and the payment method, write such words with a normal single space ("Bank Transfer",
  "Vol. 2"). Never add or remove spaces in SKUs, references, numbers, dates or e-mail addresses.
- Copy every item row, however many there are.
"""


def _client(settings: Settings) -> OpenAI:
    if not settings.groq_api_key:
        raise ExtractionError("GROQ_API_KEY is not set (see .env.example)")
    return OpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)


REQUIRED = (
    "external_reference", "order_date", "company", "contact_name", "customer_alias",
    "payment_method", "paid_status", "net_total", "vat_total", "gross_total",
)
REQUIRED_ADDRESS = ("street", "zip", "city", "country")
REQUIRED_ITEM = ("sku", "description", "quantity", "unit_net", "vat", "line_net")


def missing_fields(raw: RawOrder) -> list[str]:
    """Required fields that came back empty."""
    out = [f for f in REQUIRED if not getattr(raw, f).strip()]
    for block in ("billing_address", "delivery_address"):
        out += [f"{block}.{f}" for f in REQUIRED_ADDRESS if not getattr(getattr(raw, block), f).strip()]
    for i, item in enumerate(raw.items):
        out += [f"items[{i}].{f}" for f in REQUIRED_ITEM if not getattr(item, f).strip()]
    return out


def structure(layout_text: str, settings: Settings, check=None) -> RawOrder:
    """One LLM call, then at most one targeted retry if required fields came back empty or
    ``check(raw)`` reports problems (e.g. a value that is not the one printed under its label).

    Groq failures (quota, key, network) become a clear ExtractionError instead of a traceback."""
    try:
        return _structure(layout_text, settings, check)
    except RateLimitError as exc:
        wait = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", str(exc))
        minutes = (int(wait.group(1) or 0) * 60 + int(wait.group(2) or 0) + (1 if wait.group(3) else 0)) if wait else 0
        when = f" Try again in about {minutes} minute{'s' if minutes != 1 else ''}." if minutes else ""
        daily = "per day" in str(exc) or "TPD" in str(exc)
        raise ExtractionError(("Groq daily token limit reached for this API key." if daily
                               else "Groq rate limit reached.") + when + " (Or put another GROQ_API_KEY in .env.)",
                              [str(exc)[:300]]) from exc
    except (AuthenticationError, PermissionDeniedError) as exc:
        raise ExtractionError("Groq rejected the API key - check GROQ_API_KEY in .env", [str(exc)[:200]]) from exc
    except (APIConnectionError, APITimeoutError) as exc:
        raise ExtractionError("cannot reach Groq - check the internet connection", [str(exc)[:200]]) from exc


def _structure(layout_text: str, settings: Settings, check=None) -> RawOrder:
    raw = _call(layout_text, settings)
    problems = [f"{f} is empty although the document has it" for f in missing_fields(raw)]
    problems += list(check(raw)) if check else []
    if problems:
        hint = ("Your previous answer had these problems: " + "; ".join(problems)
                + ". Correct them, copying values verbatim from the OCR rows.")
        raw = _call(layout_text, settings, hint)
    return raw


def _call(layout_text: str, settings: Settings, hint: str = "") -> RawOrder:
    client = _client(settings)
    schema = RawOrder.model_json_schema()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"OCR rows:\n{layout_text}" + (f"\n\n{hint}" if hint else "")},
    ]
    # gpt-oss reasons before it answers: give it room (a 5-line order hit the default limit with
    # "max completion tokens reached before generating a valid document") and keep reasoning short.
    common = dict(model=settings.groq_model, messages=messages, temperature=0, max_completion_tokens=8192)
    if "gpt-oss" in settings.groq_model:
        common["reasoning_effort"] = "low"
    strict = {"type": "json_schema", "json_schema": {"name": "raw_order", "schema": schema, "strict": True}}
    try:
        resp = client.chat.completions.create(**common, response_format=strict)
    except BadRequestError as exc:  # ran out of tokens or broke the schema: retry once, then JSON mode
        log.warning("LLM structured output failed, retrying: %s", str(exc)[:200])
        try:
            resp = client.chat.completions.create(**common, response_format=strict)
        except BadRequestError:
            # Strict schema not accepted -> JSON mode with the schema in the prompt; Pydantic validates.
            messages[0]["content"] += f"\nReturn one JSON object matching this JSON schema:\n{json.dumps(schema)}"
            try:
                resp = client.chat.completions.create(**common, response_format={"type": "json_object"})
            except BadRequestError as exc2:
                raise ExtractionError("the LLM did not return a valid order JSON", [str(exc2)[:300]]) from exc2

    content = resp.choices[0].message.content or ""
    try:
        return RawOrder.model_validate_json(content)
    except ValueError as exc:
        raise ExtractionError("LLM output does not match the RawOrder schema", [str(exc)]) from exc
