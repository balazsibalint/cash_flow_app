import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.config import LlmConfig
from app.schemas import ExtractedInvoice, Message, Party
from app.services.extraction.normalize import (
    find_amounts,
    normalize_currency,
    normalize_invoice_number,
    normalize_tax_id,
    parse_amount,
    parse_date,
)
from app.services.extraction.validate import OwnCompany

MAX_TEXT_CHARS = 20_000
MAX_ATTEMPTS = 2  # legfeljebb 1 újrapróba hálózati / átmeneti hibánál


class LlmError(Exception):
    """Az LLM-hívás vagy a válasz feldolgozása sikertelen (az üzenet a felhasználónak szól, magyarul)."""


class LlmBudgetExceeded(LlmError):
    pass


class LlmBudget(Protocol):
    """Költségvédelem és naplózás (a DB-s megvalósítás: llm_budget.py)."""

    def try_acquire(self) -> bool: ...

    def record(self, *, file_sha256: str, model: str, duration_ms: int, success: bool,
               prompt_tokens: int | None, completion_tokens: int | None, error: str | None) -> None: ...


# --------------------------------------------------------------------------- válaszséma


class _LlmParty(BaseModel):
    name: str | None = None
    tax_id: str | None = None


class LlmInvoice(BaseModel):
    document_type: Literal["invoice", "credit_note", "proforma", "advance_invoice", "other"] = "invoice"
    invoice_number: str | None = None
    seller: _LlmParty = _LlmParty()
    buyer: _LlmParty = _LlmParty()
    issue_date: str | None = None
    supply_date: str | None = None
    due_date: str | None = None
    payment_terms_days: int | None = None
    currency: str | None = None
    net_total: str | None = None
    vat_total: str | None = None
    gross_total: str | None = None


_PARTY_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": ["string", "null"]}, "tax_id": {"type": ["string", "null"]}},
    "required": ["name", "tax_id"],
    "additionalProperties": False,
}
_NULLABLE_STR = {"type": ["string", "null"]}
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": ["invoice", "credit_note", "proforma", "advance_invoice", "other"]},
        "invoice_number": _NULLABLE_STR,
        "seller": _PARTY_SCHEMA,
        "buyer": _PARTY_SCHEMA,
        "issue_date": {**_NULLABLE_STR, "description": "YYYY-MM-DD"},
        "supply_date": {**_NULLABLE_STR, "description": "YYYY-MM-DD (teljesítés / date of supply)"},
        "due_date": {**_NULLABLE_STR, "description": "YYYY-MM-DD (fizetési határidő)"},
        "payment_terms_days": {"type": ["integer", "null"]},
        "currency": {**_NULLABLE_STR, "description": "ISO 4217"},
        "net_total": {**_NULLABLE_STR, "description": "decimal, dot separator, no grouping, e.g. 1234.56"},
        "vat_total": {**_NULLABLE_STR, "description": "decimal, dot separator, no grouping"},
        "gross_total": {**_NULLABLE_STR, "description": "total amount payable (gross), dot separator, no grouping"},
    },
    "required": ["document_type", "invoice_number", "seller", "buyer", "issue_date", "supply_date", "due_date",
                 "payment_terms_days", "currency", "net_total", "vat_total", "gross_total"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You extract structured data from the text of ONE invoice (any language).
Rules:
- Return ONLY values that literally appear in the text. Use null when a value is not present. Never guess.
- seller = the issuer of the invoice; buyer = the customer (bill to / Vevő / Rechnungsempfänger / client ...).
- issue_date = invoice date; supply_date = date of supply / performance / delivery (teljesítés);
  due_date = payment due date. Do not mix them up. Output dates as YYYY-MM-DD.
- gross_total = the total amount payable INCLUDING VAT, in the invoice currency. Not the net total, not the VAT.
  Ignore any informative amounts converted to another currency (e.g. "VAT in HUF", exchange-rate notes).
- Amounts: plain decimal with a dot, no thousands separators (e.g. "1234.56").
- currency: ISO 4217 code of the invoice amounts.
- document_type: "credit_note" for credit notes / storno / corrections, "proforma" for pro-forma or payment requests,
  "advance_invoice" for advance/deposit invoices, otherwise "invoice"."""


def _user_prompt(text: str, own: OwnCompany, partial: ExtractedInvoice | None, issues: list[Message]) -> str:
    parts = [
        f"Our company (one of the two parties): {own.name}, tax ids: {', '.join(sorted(own.tax_keys))}.",
    ]
    if issues:
        parts.append("A rule-based extractor had these problems, check these fields carefully:\n"
                     + "\n".join(f"- {m.code}: {m.text}" for m in issues if m.level == "error"))
    if partial is not None:
        parts.append("Rule-based partial result (may be wrong):\n" + partial.model_dump_json(exclude_none=True))
    parts.append("INVOICE TEXT:\n" + text[:MAX_TEXT_CHARS])
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- konverzió és horgonyzás


def _decimal(s: str | None) -> Decimal | None:
    if s is None or str(s).strip() == "":
        return None
    try:
        return Decimal(str(s).strip())
    except InvalidOperation:
        return parse_amount(str(s))


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError:
        return parse_date(s)


def _party(p: _LlmParty) -> Party:
    key = normalize_tax_id(p.tax_id) if p.tax_id else None
    return Party(name=(p.name or None), tax_id=p.tax_id or None, tax_keys=[key] if key else [])


def to_extracted(r: LlmInvoice) -> ExtractedInvoice:
    doc_type = {"other": "invoice"}.get(r.document_type, r.document_type)
    return ExtractedInvoice(
        doc_type=doc_type,
        invoice_number=(r.invoice_number or None),
        seller=_party(r.seller),
        buyer=_party(r.buyer),
        issue_date=_date(r.issue_date),
        supply_date=_date(r.supply_date),
        due_date=_date(r.due_date),
        payment_terms_days=r.payment_terms_days,
        currency=normalize_currency(r.currency) if r.currency else None,
        net_amount=_decimal(r.net_total),
        vat_amount=_decimal(r.vat_total),
        gross_amount=_decimal(r.gross_total),
    )


def grounding_problems(inv: ExtractedInvoice, source_text: str) -> list[str]:
    """A számlaszámnak és a bruttó összegnek szó szerint (normalizálva) szerepelnie kell a forrásszövegben."""
    problems = []
    if inv.invoice_number:
        compact = re.sub(r"[^A-Z0-9]", "", source_text.upper())
        if normalize_invoice_number(inv.invoice_number) not in compact:
            problems.append(f"a számlaszám ({inv.invoice_number}) nem szerepel a szövegben")
    if inv.gross_amount is not None:
        amounts = {abs(a.value) for a in find_amounts(source_text)}
        if abs(inv.gross_amount) not in amounts:
            problems.append(f"a végösszeg ({inv.gross_amount}) nem szerepel a szövegben")
    return problems


# --------------------------------------------------------------------------- kliens


@dataclass
class LlmResult:
    invoice: ExtractedInvoice
    model: str


_SEMAPHORES: dict[int, threading.BoundedSemaphore] = {}
_SEM_LOCK = threading.Lock()


def _semaphore(n: int) -> threading.BoundedSemaphore:
    with _SEM_LOCK:
        if n not in _SEMAPHORES:
            _SEMAPHORES[n] = threading.BoundedSemaphore(max(1, n))
        return _SEMAPHORES[n]


def _error_detail(resp: httpx.Response, api_key: str) -> str:
    """A szolgáltató hibaüzenete röviden, a kulcsot kitakarva (diagnosztikához, pl. ismeretlen modell)."""
    try:
        body = resp.json()
        err = body[0] if isinstance(body, list) and body else body
        detail = err.get("error", err) if isinstance(err, dict) else err
        if isinstance(detail, dict):
            detail = detail.get("message") or detail
        text = str(detail)
    except ValueError:
        text = resp.text
    text = re.sub(r"\s+", " ", text).strip()[:200]
    return text.replace(api_key, "***") if api_key else text


def _strip_fences(content: str) -> str:
    m = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    return m.group(1) if m else content


class LlmClient:
    retry_delay = 1.0

    def __init__(self, config: LlmConfig, *, timeout: float = 60, max_concurrency: int = 2,
                 budget: LlmBudget | None = None, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.timeout = timeout
        self.budget = budget
        self._sem = _semaphore(max_concurrency)
        self._transport = transport

    def _post(self, client: httpx.Client, payload: dict) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                resp = client.post("/chat/completions", json=payload)
            except httpx.TransportError as exc:
                last_exc = exc
            else:
                if resp.status_code < 500 and resp.status_code != 429:
                    return resp
                last_exc = LlmError(f"az LLM-szolgáltatás átmeneti hibát adott (HTTP {resp.status_code})")
            if attempt + 1 < MAX_ATTEMPTS:
                time.sleep(self.retry_delay)
        if isinstance(last_exc, LlmError):
            raise last_exc
        raise LlmError(f"az LLM-szolgáltatás nem érhető el ({type(last_exc).__name__})")

    def _payload(self, messages: list[dict], structured: bool) -> dict:
        fmt = ({"type": "json_schema", "json_schema": {"name": "invoice", "strict": True, "schema": RESPONSE_SCHEMA}}
               if structured else {"type": "json_object"})
        return {"model": self.config.model, "temperature": 0, "max_tokens": 2000,
                "messages": messages, "response_format": fmt}

    def extract(self, text: str, own: OwnCompany, *, file_sha256: str,
                partial: ExtractedInvoice | None = None, issues: list[Message] | None = None) -> LlmResult:
        if self.budget is not None and not self.budget.try_acquire():
            raise LlmBudgetExceeded("elérte a napi LLM-hívási keretet")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(text, own, partial, issues or [])},
        ]
        headers = {"Authorization": f"Bearer {self.config.api_key}", "X-Title": "Cash-flow invoice processor"}
        started = time.monotonic()
        usage: dict = {}
        error: str | None = None
        try:
            with self._sem, httpx.Client(base_url=self.config.base_url.rstrip("/"), headers=headers,
                                         timeout=self.timeout, transport=self._transport) as client:
                resp = self._post(client, self._payload(messages, structured=True))
                if resp.status_code == 400:
                    # Nem minden modell támogatja a json_schema formátumot → json_object.
                    resp = self._post(client, self._payload(messages, structured=False))
                if resp.status_code != 200:
                    raise LlmError(f"az LLM-szolgáltatás hibát adott (HTTP {resp.status_code}: "
                                   f"{_error_detail(resp, self.config.api_key)})")
                body = resp.json()
                usage = body.get("usage") or {}
                try:
                    content = body["choices"][0]["message"]["content"]
                    data = json.loads(_strip_fences(content))
                    parsed = LlmInvoice.model_validate(data)
                except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
                    raise LlmError(f"az LLM válasza nem felel meg a sémának ({type(exc).__name__})") from exc
            return LlmResult(invoice=to_extracted(parsed), model=body.get("model") or self.config.model)
        except LlmError as exc:
            error = str(exc)
            raise
        except Exception as exc:  # váratlan hiba se állítsa le a feldolgozást
            error = f"váratlan hiba az LLM-hívásban ({type(exc).__name__})"
            raise LlmError(error) from exc
        finally:
            if self.budget is not None:
                self.budget.record(
                    file_sha256=file_sha256, model=self.config.model,
                    duration_ms=int((time.monotonic() - started) * 1000), success=error is None,
                    prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
                    error=error,
                )
