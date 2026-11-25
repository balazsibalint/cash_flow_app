"""Az LLM-kliens tesztjei – kizárólag mockolt HTTP-vel (httpx.MockTransport), valódi hívás nélkül."""

import json
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.config import LlmConfig
from app.services.extraction.llm import (
    LlmBudgetExceeded,
    LlmClient,
    LlmError,
    grounding_problems,
)
from app.services.extraction.validate import OwnCompany
from app.services.llm_budget import DbLlmBudget

CFG = LlmConfig("openrouter", "https://llm.test/api/v1", "secret-test-key", "google/gemini-3.5-flash-lite")
OWN = OwnCompany("Nordwind Solutions Kft.", frozenset({"HU26481937"}))

GOOD = {
    "document_type": "invoice",
    "invoice_number": "AW-77/2026",
    "seller": {"name": "ACME Widgets GmbH", "tax_id": "DE123456789"},
    "buyer": {"name": "Nordwind Solutions Kft.", "tax_id": "HU26481937"},
    "issue_date": "2026-02-03",
    "supply_date": "2026-02-01",
    "due_date": "2026-02-17",
    "payment_terms_days": None,
    "currency": "CHF",
    "net_total": "1000.00",
    "vat_total": "81.00",
    "gross_total": "1081.00",
}


def _completion(content, status=200, model="google/gemini-3.5-flash-lite"):
    body = {"model": model, "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 120}}
    return httpx.Response(status, json=body)


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request):
        self.requests.append(request)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _client(rec, budget=None) -> LlmClient:
    c = LlmClient(CFG, transport=httpx.MockTransport(rec), budget=budget)
    c.retry_delay = 0
    return c


def test_successful_structured_extraction():
    rec = Recorder(_completion(json.dumps(GOOD)))
    res = _client(rec).extract("invoice text", OWN, file_sha256="a" * 64)
    inv = res.invoice
    assert inv.invoice_number == "AW-77/2026"
    assert inv.seller.tax_keys == ["DE123456789"]
    assert inv.buyer.tax_keys == ["HU26481937"]
    assert inv.issue_date == date(2026, 2, 3)
    assert inv.gross_amount == Decimal("1081.00") and isinstance(inv.gross_amount, Decimal)
    assert inv.currency == "CHF"

    req = rec.requests[0]
    assert req.url.path.endswith("/chat/completions")
    assert req.headers["Authorization"] == "Bearer secret-test-key"
    payload = json.loads(req.content)
    assert payload["temperature"] == 0
    assert payload["model"] == "google/gemini-3.5-flash-lite"
    assert payload["response_format"]["type"] == "json_schema"
    # A kulcs csak a fejlécben utazhat, a kérés törzsében soha.
    assert "secret-test-key" not in req.content.decode()


def test_falls_back_to_json_object_when_schema_unsupported():
    rec = Recorder(httpx.Response(400, json={"error": "response_format not supported"}),
                   _completion("```json\n" + json.dumps(GOOD) + "\n```"))
    res = _client(rec).extract("x", OWN, file_sha256="a" * 64)
    assert res.invoice.invoice_number == "AW-77/2026"
    assert json.loads(rec.requests[1].content)["response_format"] == {"type": "json_object"}


def test_retries_once_on_network_error():
    rec = Recorder(httpx.ConnectError("boom"), _completion(json.dumps(GOOD)))
    assert _client(rec).extract("x", OWN, file_sha256="a" * 64).invoice.currency == "CHF"
    assert len(rec.requests) == 2


def test_gives_up_after_second_failure():
    rec = Recorder(httpx.ConnectError("boom"), httpx.Response(503))
    with pytest.raises(LlmError):
        _client(rec).extract("x", OWN, file_sha256="a" * 64)
    assert len(rec.requests) == 2


@pytest.mark.parametrize("content", ["not json at all", json.dumps({"invoice_number": 5, "seller": "x"})])
def test_invalid_response_raises(content):
    with pytest.raises(LlmError):
        _client(Recorder(_completion(content))).extract("x", OWN, file_sha256="a" * 64)


def test_error_messages_never_contain_the_key():
    rec = Recorder(httpx.Response(401, json={"error": "bad key secret-test-key"}))
    with pytest.raises(LlmError) as exc:
        _client(rec).extract("x", OWN, file_sha256="a" * 64)
    assert "secret-test-key" not in str(exc.value)
    assert "***" in str(exc.value)


def test_error_message_includes_provider_detail():
    # Pl. ismeretlen vagy kivezetett modellnél a szolgáltató üzenete nélkül a 404 nem diagnosztizálható.
    body = [{"error": {"code": 404, "message": "models/gemini-x is not found", "status": "NOT_FOUND"}}]
    with pytest.raises(LlmError) as exc:
        _client(Recorder(httpx.Response(404, json=body))).extract("x", OWN, file_sha256="a" * 64)
    assert "HTTP 404" in str(exc.value) and "is not found" in str(exc.value)


# ----------------------------------------------------------------------------- költségkeret és napló


@pytest.fixture
def budget_factory(db_session):
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    return lambda limit: DbLlmBudget(factory, limit)


def test_budget_records_calls_and_blocks_over_limit(budget_factory):
    budget = budget_factory(2)
    rec = Recorder(_completion(json.dumps(GOOD)), _completion("garbage"))
    client = _client(rec, budget)
    client.extract("x", OWN, file_sha256="a" * 64)
    with pytest.raises(LlmError):
        client.extract("x", OWN, file_sha256="b" * 64)
    assert budget.calls_today() == 2

    with pytest.raises(LlmBudgetExceeded):
        client.extract("x", OWN, file_sha256="c" * 64)
    assert len(rec.requests) == 2  # a keret túllépésekor nincs HTTP-hívás


# ----------------------------------------------------------------------------- horgonyzás


def test_grounding_accepts_values_present_in_text():
    from app.services.extraction.llm import LlmInvoice, to_extracted

    inv = to_extracted(LlmInvoice.model_validate(GOOD))
    text = "Invoice number: AW-77/2026 ... Amount due 1'081.00 CHF"
    assert grounding_problems(inv, text) == []


def test_grounding_rejects_hallucinated_values():
    from app.services.extraction.llm import LlmInvoice, to_extracted

    inv = to_extracted(LlmInvoice.model_validate({**GOOD, "gross_total": "9999.00", "invoice_number": "ZZ-1"}))
    problems = grounding_problems(inv, "Invoice number: AW-77/2026 Amount due 1'081.00 CHF")
    assert len(problems) == 2
