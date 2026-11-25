from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from app.schemas import ExtractedInvoice, Message
from app.services.extraction.normalize import KNOWN_CURRENCIES, normalize_company_name

MISSING_FIELD = "MISSING_FIELD"
MISSING_DUE = "MISSING_DUE"
INFERRED_SUPPLY = "INFERRED_SUPPLY"
INFERRED_DUE = "INFERRED_DUE"
UNKNOWN_CURRENCY = "UNKNOWN_CURRENCY"
SUM_MISMATCH = "SUM_MISMATCH"
DATE_ORDER = "DATE_ORDER"
OWN_COMPANY_SIDE = "OWN_COMPANY_SIDE"
NEGATIVE_TOTAL = "NEGATIVE_TOTAL"

REJECT_CODES = {NEGATIVE_TOTAL}

MAX_SUPPLY_ISSUE_GAP = timedelta(days=366)


@dataclass(frozen=True)
class OwnCompany:
    name: str
    tax_keys: frozenset[str]


def _err(code: str, text: str) -> Message:
    return Message(code=code, level="error", text=text)


def _warn(code: str, text: str) -> Message:
    return Message(code=code, level="warning", text=text)


def apply_inference(inv: ExtractedInvoice) -> tuple[ExtractedInvoice, list[Message]]:
    """hiányzó teljesítés → kiállítás dátuma; hiányzó határidő → kiállítás + fizetési feltétel."""
    inv = inv.model_copy(deep=True)
    notes: list[Message] = []
    if inv.supply_date is None and inv.issue_date is not None:
        inv.supply_date = inv.issue_date
        notes.append(_warn(INFERRED_SUPPLY, "A teljesítés dátuma nem szerepel a számlán; a kiállítás dátumát használtuk."))
    if inv.due_date is None and inv.issue_date is not None and inv.payment_terms_days is not None:
        inv.due_date = inv.issue_date + timedelta(days=inv.payment_terms_days)
        notes.append(_warn(
            INFERRED_DUE,
            f"A fizetési határidő nem szerepel a számlán; a kiállítás + {inv.payment_terms_days} nap fizetési feltételből számoltuk.",
        ))
    return inv, notes


def direction_of(inv: ExtractedInvoice, own: OwnCompany) -> str | None:
    """`outgoing`, ha a mi cégünk a kiállító; `incoming`, ha a vevő; különben None.
    Elsődlegesen az adószám dönt; a név csak akkor, ha egyik oldalon sincs saját adószám."""
    seller_own = bool(own.tax_keys & set(inv.seller.tax_keys))
    buyer_own = bool(own.tax_keys & set(inv.buyer.tax_keys))
    if seller_own != buyer_own:
        return "outgoing" if seller_own else "incoming"
    if not seller_own and not buyer_own:
        own_name = normalize_company_name(own.name)
        s = bool(inv.seller.name) and normalize_company_name(inv.seller.name) == own_name
        b = bool(inv.buyer.name) and normalize_company_name(inv.buyer.name) == own_name
        if s != b:
            return "outgoing" if s else "incoming"
    return None


def _sum_tolerance(currency: str | None) -> Decimal:
    # Forintos számlán az ÁFA egész forintra kerekített, ezért 1 Ft eltérés megengedett.
    return Decimal("1") if currency == "HUF" else Decimal("0.01")


def validate(inv: ExtractedInvoice, own: OwnCompany) -> list[Message]:
    msgs: list[Message] = []

    missing = []
    if not inv.invoice_number:
        missing.append("számlaszám")
    if inv.issue_date is None:
        missing.append("kiállítás dátuma")
    if inv.supply_date is None:
        missing.append("teljesítés dátuma")
    if not inv.currency:
        missing.append("pénznem")
    if inv.gross_amount is None:
        missing.append("bruttó végösszeg")
    if not (inv.seller.name or inv.seller.tax_keys):
        missing.append("kiállító")
    if not (inv.buyer.name or inv.buyer.tax_keys):
        missing.append("vevő")
    if missing:
        msgs.append(_err(MISSING_FIELD, "Hiányzó mezők: " + ", ".join(missing) + "."))

    if inv.due_date is None:
        msgs.append(_err(MISSING_DUE, "A fizetési határidő nem található, és fizetési feltételből sem számítható."))

    if inv.currency and inv.currency not in KNOWN_CURRENCIES:
        msgs.append(_err(UNKNOWN_CURRENCY, f"Ismeretlen pénznem: {inv.currency}."))

    if None not in (inv.net_amount, inv.vat_amount, inv.gross_amount):
        diff = abs(inv.net_amount + inv.vat_amount - inv.gross_amount)
        if diff > _sum_tolerance(inv.currency):
            msgs.append(_err(
                SUM_MISMATCH,
                f"A nettó ({inv.net_amount}) + ÁFA ({inv.vat_amount}) nem egyezik a bruttó végösszeggel ({inv.gross_amount}).",
            ))

    if inv.issue_date and inv.due_date and inv.due_date < inv.issue_date:
        msgs.append(_err(DATE_ORDER, "A fizetési határidő korábbi, mint a kiállítás dátuma."))
    if inv.issue_date and inv.supply_date and abs(inv.supply_date - inv.issue_date) > MAX_SUPPLY_ISSUE_GAP:
        msgs.append(_err(DATE_ORDER, "A teljesítés és a kiállítás dátuma több mint egy évvel eltér."))

    if direction_of(inv, own) is None:
        msgs.append(_err(
            OWN_COMPANY_SIDE,
            "Nem állapítható meg egyértelműen, hogy a cégünk a kiállító vagy a vevő.",
        ))

    if inv.gross_amount is not None and inv.gross_amount < 0:
        msgs.append(_err(NEGATIVE_TOTAL, "Negatív végösszegű bizonylat (jóváíró jellegű) – nem dolgozzuk fel."))

    return msgs


def has_errors(msgs: list[Message]) -> bool:
    return any(m.level == "error" for m in msgs)
