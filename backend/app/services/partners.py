from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Direction, Invoice, Partner
from app.schemas import Party
from app.services.extraction.normalize import normalize_company_name, normalize_tax_id

NAME_PREFIX = "NAME:"
UNKNOWN_KEY = "UNKNOWN"
UNKNOWN_NAME = "Ismeretlen partner"


def party_tax_key(party: Party, exclude: frozenset[str] = frozenset()) -> str | None:
    """A fél adószám-kulcsa: elsődlegesen a fél adószámaként kinyert érték, különben az első talált (nem saját) kulcs."""
    primary = normalize_tax_id(party.tax_id)
    if primary and primary not in exclude:
        return primary
    return next((k for k in party.tax_keys if k not in exclude), None)


def name_key(name: str | None) -> str | None:
    norm = normalize_company_name(name)
    return f"{NAME_PREFIX}{norm}" if norm else None


def counterparty(seller: Party, buyer: Party, direction: str) -> Party:
    return buyer if direction == Direction.outgoing.value else seller


def counterparty_name(inv: Invoice) -> str | None:
    if inv.direction == Direction.outgoing:
        return inv.buyer_name
    if inv.direction == Direction.incoming:
        return inv.seller_name
    return None


def _by_key(session: Session, key: str) -> Partner | None:
    return session.scalars(select(Partner).where(Partner.tax_key == key)).first()


def _find_by_alias(session: Session, norm_name: str) -> Partner | None:
    """Adószám nélküli számlához: az a (adószámos) partner, amelynek valamelyik névváltozata ugyanerre normalizálódik."""
    for p in session.scalars(select(Partner).where(Partner.tax_key.not_like(f"{NAME_PREFIX}%"))):
        if any(normalize_company_name(a) == norm_name for a in (p.aliases or {})):
            return p
    return None


def find_or_create(session: Session, tax_key: str | None, name: str | None) -> Partner:
    """A partner megkeresése vagy létrehozása. Ha adószámos változat érkezik egy korábban csak név alapján
    felvett partnerhez, a kettőt összevonjuk (5.7)."""
    nkey = name_key(name)
    if tax_key:
        partner = _by_key(session, tax_key)
        if partner is None:
            partner = Partner(tax_key=tax_key, display_name=name or tax_key, aliases={})
            session.add(partner)
            session.flush()
        if nkey and (orphan := _by_key(session, nkey)) is not None:
            for inv in list(orphan.invoices):
                inv.partner = partner
            session.flush()
            session.delete(orphan)
            session.flush()
        return partner

    if nkey:
        partner = _by_key(session, nkey) or _find_by_alias(session, nkey[len(NAME_PREFIX):])
        if partner is None:
            partner = Partner(tax_key=nkey, display_name=name or "", aliases={})
            session.add(partner)
            session.flush()
        return partner

    partner = _by_key(session, UNKNOWN_KEY)
    if partner is None:
        partner = Partner(tax_key=UNKNOWN_KEY, display_name=UNKNOWN_NAME, aliases={})
        session.add(partner)
        session.flush()
    return partner


def refresh(session: Session, partner: Partner) -> None:
    """Névváltozatok és megjelenített név újraszámolása a partner számláiból; az árva partnert töröljük.
    A megjelenített név a leggyakoribb írásmód, holtversenynél a legkorábban rögzített (K13)."""
    session.flush()
    invoices = sorted(partner.invoices, key=lambda i: i.id)
    if not invoices:
        session.delete(partner)
        return
    counts: Counter[str] = Counter()
    for inv in invoices:
        if name := counterparty_name(inv):
            counts[name.strip()] += 1
    partner.aliases = dict(counts)  # új dict: a JSON-mező változását így érzékeli az ORM
    if counts:
        best = max(counts.values())
        partner.display_name = next(n for n in counts if counts[n] == best)
