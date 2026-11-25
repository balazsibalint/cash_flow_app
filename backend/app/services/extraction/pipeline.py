"""Egy PDF teljes kinyerési folyamata (DB nélkül):

doctype → saját cég szerepel-e → szabályalapú kinyerés → K6-következtetés → validáció
→ (hiba esetén) LLM-tartalék → horgonyzás → validáció → státusz (ok / review / rejected).
"""

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

from app.config import Settings
from app.schemas import ExtractedInvoice, Message, Party
from app.services.extraction.doctype import DOC_TYPE_LABELS_HU, INVOICE
from app.services.extraction.llm import LlmError, LlmResult, grounding_problems
from app.services.extraction.normalize import (
    find_tax_ids,
    fold,
    normalize_company_name,
    normalize_invoice_number,
    normalize_tax_id,
)
from app.services.extraction.rules import extract
from app.services.extraction.validate import (
    INFERRED_DUE,
    INFERRED_SUPPLY,
    REJECT_CODES,
    OwnCompany,
    apply_inference,
    direction_of,
    has_errors,
    validate,
)
from app.services.pdf_text import PdfDocument

LLM_DISABLED = "LLM_DISABLED"
LLM_FAILED = "LLM_FAILED"
LLM_UNGROUNDED = "LLM_UNGROUNDED"
LLM_USED = "LLM_USED"
LLM_DISAGREES = "LLM_DISAGREES"

Status = Literal["ok", "review", "rejected"]


class LlmExtractor(Protocol):
    def extract(self, text: str, own: OwnCompany, *, file_sha256: str,
                partial: ExtractedInvoice | None = None, issues: list[Message] | None = None) -> LlmResult: ...


@dataclass
class PipelineResult:
    status: Status
    invoice: ExtractedInvoice
    method: Literal["rule", "llm"] = "rule"
    direction: str | None = None
    messages: list[Message] = field(default_factory=list)
    status_reason: str | None = None
    llm_called: bool = False

    @property
    def supply_inferred(self) -> bool:
        return any(m.code == INFERRED_SUPPLY for m in self.messages)

    @property
    def due_inferred(self) -> bool:
        return any(m.code == INFERRED_DUE for m in self.messages)


def own_company(settings: Settings) -> OwnCompany:
    keys = {normalize_tax_id(settings.own_tax_number), normalize_tax_id(settings.own_eu_vat)}
    return OwnCompany(settings.own_company_name, frozenset(k for k in keys if k))


def mentions_own_company(doc: PdfDocument, own: OwnCompany) -> bool:
    text = doc.full_text + "\n" + doc.layout_text
    if own.tax_keys & {t.key for t in find_tax_ids(text)}:
        return True
    name = normalize_company_name(own.name)
    return bool(name) and name in re.sub(r"[^a-z0-9]+", " ", fold(text))


def _info(code: str, text: str) -> Message:
    return Message(code=code, level="info", text=text)


def _error_summary(msgs: list[Message]) -> str:
    return " ".join(m.text for m in msgs if m.level == "error")


def _rejected(inv: ExtractedInvoice, reason: str, msgs: list[Message] | None = None) -> PipelineResult:
    return PipelineResult(status="rejected", invoice=inv, status_reason=reason,
                          messages=(msgs or []) + [Message(code="REJECTED", level="error", text=reason)])


def _merge_party(primary: Party, fallback: Party) -> Party:
    return Party(
        name=primary.name or fallback.name,
        tax_id=primary.tax_id or fallback.tax_id,
        tax_keys=primary.tax_keys or fallback.tax_keys,
    )


def _merge(llm: ExtractedInvoice, rule: ExtractedInvoice) -> ExtractedInvoice:
    """Az LLM-eredmény, a hiányzó mezőket a szabályalapú eredményből pótolva."""
    data = llm.model_dump()
    for key, value in rule.model_dump().items():
        if key in ("seller", "buyer"):
            continue
        if data.get(key) is None and value is not None:
            data[key] = value
    merged = ExtractedInvoice.model_validate(data)
    merged.seller = _merge_party(llm.seller, rule.seller)
    merged.buyer = _merge_party(llm.buyer, rule.buyer)
    return merged


_COMPARED = {
    "invoice_number": "számlaszám", "issue_date": "kiállítás dátuma", "supply_date": "teljesítés dátuma",
    "due_date": "fizetési határidő", "currency": "pénznem", "gross_amount": "bruttó végösszeg",
}


def _disagreements(llm: ExtractedInvoice, rule: ExtractedInvoice) -> list[str]:
    out = []
    for f, label in _COMPARED.items():
        a, b = getattr(llm, f), getattr(rule, f)
        if f == "invoice_number":
            a, b = normalize_invoice_number(a), normalize_invoice_number(b)
        if a is not None and b is not None and a != b:
            out.append(label)
    return out


def _finish_ok(inv: ExtractedInvoice, own: OwnCompany, msgs: list[Message], method, llm_called: bool) -> PipelineResult:
    return PipelineResult(status="ok", invoice=inv, method=method, direction=direction_of(inv, own),
                          messages=msgs, llm_called=llm_called)


def process(doc: PdfDocument, own: OwnCompany, *, llm: LlmExtractor | None, file_sha256: str) -> PipelineResult:
    rule = extract(doc)

    # K7: különleges bizonylat és idegen számla – LLM nélkül, azonnal elutasítva.
    if rule.doc_type and rule.doc_type != INVOICE:
        return _rejected(rule, f"A dokumentum {DOC_TYPE_LABELS_HU.get(rule.doc_type, rule.doc_type)}, nem dolgozzuk fel.")
    if not mentions_own_company(doc, own):
        return _rejected(rule, "A cégünk (adószám vagy név) nem szerepel a dokumentumon, ezért nem dolgozzuk fel.")

    rule_inv, rule_notes = apply_inference(rule)
    rule_issues = validate(rule_inv, own)
    if any(m.code in REJECT_CODES for m in rule_issues):
        return _rejected(rule_inv, _error_summary([m for m in rule_issues if m.code in REJECT_CODES]))
    if not has_errors(rule_issues):
        return _finish_ok(rule_inv, own, rule_notes + rule_issues, "rule", False)

    review = PipelineResult(status="review", invoice=rule_inv, direction=direction_of(rule_inv, own),
                            messages=rule_notes + rule_issues, status_reason=_error_summary(rule_issues))

    # LLM-tartalék
    if llm is None:
        review.messages.append(_info(LLM_DISABLED, "Az LLM-tartalék nincs bekapcsolva, a számlát kézzel kell ellenőrizni."))
        return review
    try:
        result = llm.extract(doc.layout_text, own, file_sha256=file_sha256, partial=rule, issues=rule_issues)
    except LlmError as exc:
        review.llm_called = True
        review.messages.append(Message(code=LLM_FAILED, level="warning", text=f"Az LLM-tartalék sikertelen: {exc}."))
        return review
    review.llm_called = True

    llm_inv = _merge(result.invoice, rule)
    if llm_inv.doc_type and llm_inv.doc_type != INVOICE:
        return _rejected(llm_inv, f"A dokumentum az LLM szerint {DOC_TYPE_LABELS_HU.get(llm_inv.doc_type, llm_inv.doc_type)}, nem dolgozzuk fel.")

    grounding = grounding_problems(llm_inv, doc.full_text + "\n" + doc.layout_text)
    if grounding:
        review.messages.append(Message(
            code=LLM_UNGROUNDED, level="error",
            text="Az LLM válasza nem támasztható alá a számla szövegével: " + "; ".join(grounding) + ".",
        ))
        return review

    llm_inv, llm_notes = apply_inference(llm_inv)
    llm_issues = validate(llm_inv, own)
    if any(m.code in REJECT_CODES for m in llm_issues):
        return _rejected(llm_inv, _error_summary([m for m in llm_issues if m.code in REJECT_CODES]))
    if has_errors(llm_issues):
        better = sum(m.level == "error" for m in llm_issues) < sum(m.level == "error" for m in rule_issues)
        inv, issues, notes = (llm_inv, llm_issues, llm_notes) if better else (rule_inv, rule_issues, rule_notes)
        return PipelineResult(
            status="review", invoice=inv, method="llm" if better else "rule", direction=direction_of(inv, own),
            messages=notes + issues + [Message(
                code=LLM_FAILED, level="warning",
                text="Az LLM-tartalék eredménye sem ment át a validáción: " + _error_summary(llm_issues),
            )],
            status_reason=_error_summary(issues), llm_called=True,
        )

    msgs = llm_notes + llm_issues + [_info(LLM_USED, "A számlát az LLM-tartalék dolgozta fel, mert a szabályalapú "
                                                      "kinyerés hibás volt: " + _error_summary(rule_issues))]
    if diff := _disagreements(llm_inv, rule):
        msgs.append(Message(code=LLM_DISAGREES, level="warning",
                            text="Az LLM és a szabályalapú kinyerés eltér: " + ", ".join(diff) + "."))
    return _finish_ok(llm_inv, own, msgs, "llm", True)
