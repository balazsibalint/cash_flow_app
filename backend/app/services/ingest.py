import hashlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import Direction, ExtractionMethod, Invoice, InvoiceStatus, Partner
from app.schemas import ExtractedInvoice, InvoiceOut, Message, UploadResult
from app.services import partners
from app.services.extraction.normalize import normalize_invoice_number
from app.services.extraction.pipeline import LlmExtractor, process
from app.services.extraction.validate import OwnCompany
from app.services.fx import to_huf
from app.services.mnb import MnbNoRate, MnbUnavailable, RateService
from app.services.pdf_text import PdfReadError, load_pdf

log = logging.getLogger(__name__)

PDF_UNREADABLE = "PDF_UNREADABLE"
PROCESSING_ERROR = "PROCESSING_ERROR"
FX_UNAVAILABLE = "FX_UNAVAILABLE"
FX_NO_RATE = "FX_NO_RATE"
FX_PROVISIONAL = "FX_PROVISIONAL"
FX_CODES = {FX_UNAVAILABLE, FX_NO_RATE, FX_PROVISIONAL}

PDF_MAGIC = b"%PDF-"
_FX_FIELDS = ("status", "status_reason", "fx_rate", "fx_unit", "fx_rate_date", "fx_provisional", "gross_huf")
_SAVE_LOCK = threading.Lock()


class InvalidUpload(Exception):
    """A fájl nem PDF vagy túl nagy – nem mentjük (400 / 413)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def check_upload(data: bytes, max_bytes: int) -> None:
    if len(data) > max_bytes:
        raise InvalidUpload(f"A fájl túl nagy (legfeljebb {max_bytes // (1024 * 1024)} MB lehet).", 413)
    if not data:
        raise InvalidUpload("A fájl üres.")
    if PDF_MAGIC not in data[:1024]:
        raise InvalidUpload("A fájl nem PDF (hiányzik a %PDF- fejléc).")


def _fmt(d) -> str:
    return d.strftime("%Y.%m.%d.")


def _msg(code: str, level: str, text: str) -> dict:
    return Message(code=code, level=level, text=text).model_dump()


def to_out(inv: Invoice) -> InvoiceOut:
    return InvoiceOut.model_validate(inv)


@dataclass
class _Processed:
    """A kinyerés eredménye mentés előtt (DB-független), hogy ütközéskor újra lehessen próbálni a mentést."""

    fields: dict
    extracted: ExtractedInvoice | None = None
    messages: list[dict] = field(default_factory=list)

    @property
    def status(self) -> InvoiceStatus:
        return self.fields["status"]


class IngestService:
    def __init__(self, session_factory: Callable[[], Session], pdf_dir: Path, own: OwnCompany, *,
                 llm: LlmExtractor | None, rates: RateService, retry_interval_seconds: float = 60):
        self._session_factory = session_factory
        self.pdf_dir = Path(pdf_dir)
        self.own = own
        self.llm = llm
        self.rates = rates
        self.retry_interval_seconds = retry_interval_seconds
        self._retry_lock = threading.Lock()
        self._last_retry: float | None = None

    # ------------------------------------------------------------------ feltöltés

    def pdf_path(self, sha: str) -> Path:
        return self.pdf_dir / f"{sha}.pdf"

    def ingest(self, filename: str, data: bytes) -> UploadResult:
        """Egy (már ellenőrzött) PDF feldolgozása. Nem dob kivételt: minden hiba a válaszba / a számlához kerül."""
        self.retry_fx()
        sha = hashlib.sha256(data).hexdigest()
        with self._session_factory() as s:
            if (existing := self._by_sha(s, sha)) is not None:
                return UploadResult(result="duplicate", invoice=to_out(existing),
                                    message="Ez a fájl már fel van töltve, nem dolgoztuk fel újra.")

        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_path(sha).write_bytes(data)
        processed = self._process(filename, data, sha)
        try:
            return self._save(processed, sha)
        except Exception:
            log.exception("A számla mentése nem sikerült: %s", filename)
            self._remove_pdf_if_unused(sha)
            return UploadResult(result="error", message="Váratlan hiba történt a számla mentésekor; próbálja újra.")

    def _process(self, filename: str, data: bytes, sha: str) -> _Processed:
        base = {"file_sha256": sha, "filename": (filename or "nevtelen.pdf")[:255]}
        try:
            doc = load_pdf(data)
        except PdfReadError as exc:
            return _Processed({**base, "status": InvoiceStatus.error, "status_reason": str(exc)},
                              messages=[_msg(PDF_UNREADABLE, "error", str(exc))])
        try:
            res = process(doc, self.own, llm=self.llm, file_sha256=sha)
        except Exception as exc:  # hibaizoláció: egy fájl hibája nem állíthatja le a többit
            log.exception("Váratlan hiba a kinyerés során: %s", filename)
            reason = f"Váratlan hiba a feldolgozás során ({type(exc).__name__})."
            return _Processed({**base, "status": InvoiceStatus.error, "status_reason": reason, "raw_text": doc.full_text},
                              messages=[_msg(PROCESSING_ERROR, "error", reason)])

        inv = res.invoice
        seller_key = partners.party_tax_key(inv.seller)
        fields = {
            **base,
            "status": InvoiceStatus(res.status),
            "status_reason": res.status_reason,
            "extraction_method": ExtractionMethod(res.method),
            "doc_type": inv.doc_type,
            "invoice_number": inv.invoice_number,
            "invoice_number_norm": normalize_invoice_number(inv.invoice_number),
            "seller_name": inv.seller.name, "seller_tax": inv.seller.tax_id, "seller_tax_key": seller_key,
            "buyer_name": inv.buyer.name, "buyer_tax": inv.buyer.tax_id,
            "issue_date": inv.issue_date, "supply_date": inv.supply_date, "due_date": inv.due_date,
            "supply_date_inferred": res.supply_inferred, "due_date_inferred": res.due_inferred,
            "currency": inv.currency,
            "net_amount": inv.net_amount, "vat_amount": inv.vat_amount, "gross_amount": inv.gross_amount,
            "direction": Direction(res.direction) if res.direction else None,
            "raw_text": doc.full_text,
        }
        return _Processed(fields, extracted=inv, messages=[m.model_dump() for m in res.messages])

    def _duplicate_result(self, dup: Invoice, sha: str) -> UploadResult:
        self._remove_pdf_if_unused(sha)
        return UploadResult(
            result="duplicate", invoice=to_out(dup),
            message=f"Ez a számla már szerepel (ugyanaz a kiállító és számlaszám: {dup.filename}); kihagytuk.",
        )

    def _save(self, p: _Processed, sha: str) -> UploadResult:
        # 1. Árfolyam a zár előtt (a lassú MNB-hívás ne sorosítsa a feltöltéseket); duplikátumra nem kérdezünk.
        with self._session_factory() as s:
            if (dup := self._duplicate_of(s, p)) is not None:
                return self._duplicate_result(dup, sha)
            if p.status == InvoiceStatus.ok:
                scratch = Invoice(**p.fields, messages=list(p.messages))
                self._apply_fx(s, scratch)
                p.fields.update({k: v for k in _FX_FIELDS if (v := getattr(scratch, k)) is not None})
                p.messages = list(scratch.messages)

        # 2. Dedup-ellenőrzés, partner és beszúrás egy lépésben: párhuzamos feltöltésnél ugyanaz a partner
        #    vagy számla különben kétszer jönne létre (UNIQUE-hiba). Több folyamatnál a UNIQUE-index véd + újrapróba.
        for attempt in range(2):
            with _SAVE_LOCK, self._session_factory() as s:
                try:
                    if (dup := self._duplicate_of(s, p)) is not None:
                        return self._duplicate_result(dup, sha)
                    inv = Invoice(**p.fields, messages=list(p.messages))
                    partner = self._assign_partner(s, inv, p)
                    s.add(inv)
                    s.flush()
                    if partner is not None:
                        partners.refresh(s, partner)
                    s.commit()
                except IntegrityError:
                    s.rollback()
                    if attempt == 0:
                        continue
                    raise
                s.refresh(inv)
                return self._result(inv)
        raise RuntimeError("unreachable")

    def _assign_partner(self, s: Session, inv: Invoice, p: _Processed) -> Partner | None:
        if p.extracted is None or inv.direction is None or inv.status in (InvoiceStatus.rejected, InvoiceStatus.error):
            return None
        cp = partners.counterparty(p.extracted.seller, p.extracted.buyer, inv.direction.value)
        partner = partners.find_or_create(s, partners.party_tax_key(cp, exclude=self.own.tax_keys), cp.name)
        inv.partner = partner
        return partner

    @staticmethod
    def _result(inv: Invoice) -> UploadResult:
        out = to_out(inv)
        if inv.status == InvoiceStatus.ok:
            msg = "Feldolgozva."
            if inv.fx_provisional:
                msg = "Feldolgozva, ideiglenes árfolyammal (a teljesítés napjára még nincs MNB-jegyzés)."
            return UploadResult(result="created", message=msg, invoice=out)
        if inv.status == InvoiceStatus.pending_fx:
            return UploadResult(result="created", invoice=out,
                                message="Feldolgozva, de az MNB-árfolyam nem érhető el; a következő feltöltéskor újra lekérjük.")
        if inv.status == InvoiceStatus.review:
            return UploadResult(result="review", invoice=out, message=f"Ellenőrzendő: {inv.status_reason}")
        if inv.status == InvoiceStatus.rejected:
            return UploadResult(result="rejected", invoice=out, message=inv.status_reason or "Elutasítva.")
        return UploadResult(result="error", invoice=out, message=inv.status_reason or "A fájl nem dolgozható fel.")

    # ------------------------------------------------------------------ dedup

    @staticmethod
    def _by_sha(s: Session, sha: str) -> Invoice | None:
        return s.scalars(select(Invoice).options(selectinload(Invoice.partner)).where(Invoice.file_sha256 == sha)).first()

    def _duplicate_of(self, s: Session, p: _Processed) -> Invoice | None:
        if (by_sha := self._by_sha(s, p.fields["file_sha256"])) is not None:
            return by_sha
        key, number = p.fields.get("seller_tax_key"), p.fields.get("invoice_number_norm")
        if not key or not number:
            return None
        return s.scalars(select(Invoice).options(selectinload(Invoice.partner))
                         .where(Invoice.seller_tax_key == key, Invoice.invoice_number_norm == number)).first()

    def _remove_pdf_if_unused(self, sha: str) -> None:
        with self._session_factory() as s:
            if self._by_sha(s, sha) is None:
                self.pdf_path(sha).unlink(missing_ok=True)

    # ------------------------------------------------------------------ árfolyam

    def _apply_fx(self, s: Session, inv: Invoice) -> bool:
        """Árfolyam és forintösszeg beállítása. Az MNB kiesésekor `pending_fx` (K9), nem jegyzett devizánál `review`.
        Visszatérés: elérhető volt-e az MNB."""
        msgs = [m for m in (inv.messages or []) if m.get("code") not in FX_CODES]
        try:
            choice = self.rates.select_rate(s, inv.currency, inv.supply_date)
        except MnbUnavailable as exc:
            inv.status = InvoiceStatus.pending_fx
            inv.status_reason = f"Az MNB-árfolyam nem kérhető le ({exc}); a következő feltöltéskor újrapróbáljuk."
            inv.messages = msgs + [_msg(FX_UNAVAILABLE, "warning", inv.status_reason)]
            return False
        except MnbNoRate as exc:
            inv.status = InvoiceStatus.review
            inv.status_reason = str(exc)
            inv.messages = msgs + [_msg(FX_NO_RATE, "error", str(exc))]
            return True

        inv.fx_rate, inv.fx_unit, inv.fx_rate_date = choice.rate, choice.unit, choice.rate_date
        inv.fx_provisional = choice.provisional
        inv.gross_huf = to_huf(inv.gross_amount, choice.rate, choice.unit)
        inv.status, inv.status_reason = InvoiceStatus.ok, None
        if choice.provisional:
            msgs.append(_msg(FX_PROVISIONAL, "warning",
                             f"Ideiglenes árfolyam: a teljesítés napjára ({_fmt(inv.supply_date)}) még nincs MNB-jegyzés, "
                             f"ezért a {_fmt(choice.rate_date)} jegyzést használtuk; később frissítjük."))
        inv.messages = msgs
        return True

    def retry_fx(self, *, force: bool = False) -> None:
        """A pending_fx és az ideiglenes árfolyamú számlák újraszámolása (6.5), legfeljebb `retry_interval`-onként."""
        with self._retry_lock:
            now = time.monotonic()
            if not force and self._last_retry is not None and now - self._last_retry < self.retry_interval_seconds:
                return
            self._last_retry = now
        try:
            with self._session_factory() as s:
                ids = s.scalars(select(Invoice.id).where(or_(
                    Invoice.status == InvoiceStatus.pending_fx,
                    (Invoice.status == InvoiceStatus.ok) & Invoice.fx_provisional.is_(True),
                )).order_by(Invoice.id)).all()
                for invoice_id in ids:
                    inv = s.get(Invoice, invoice_id)
                    if inv is None:
                        continue
                    available = self._apply_fx(s, inv)
                    s.commit()
                    if not available:
                        break  # az MNB még mindig nem érhető el – nem terheljük tovább
        except Exception:
            log.exception("Az árfolyamok újrapróbálása nem sikerült")


# ---------------------------------------------------------------------- törlés (K12)


def delete_invoice(s: Session, invoice_id: int, pdf_dir: Path) -> bool:
    inv = s.get(Invoice, invoice_id)
    if inv is None:
        return False
    sha, partner = inv.file_sha256, inv.partner
    s.delete(inv)
    s.flush()
    if partner is not None:
        s.refresh(partner, ["invoices"])
        partners.refresh(s, partner)
    s.commit()
    (Path(pdf_dir) / f"{sha}.pdf").unlink(missing_ok=True)
    return True


def delete_all(s: Session, pdf_dir: Path) -> int:
    """Minden számla és partner törlése; az árfolyam-gyorsítótár és az LLM-napló megmarad."""
    n = s.execute(delete(Invoice)).rowcount
    s.execute(delete(Partner))
    s.commit()
    for f in Path(pdf_dir).glob("*.pdf"):
        f.unlink(missing_ok=True)
    return n
