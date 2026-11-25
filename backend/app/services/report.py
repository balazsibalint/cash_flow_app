from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Direction, Invoice, InvoiceStatus
from app.schemas import MonthPoint, PartnerTotals, ReportOut


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_range(first: date, last: date) -> list[str]:
    """Folytonos hónaplista `first` és `last` hónapja között (mindkettőt beleértve)."""
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build_report(s: Session) -> ReportOut:
    invoices = s.scalars(
        select(Invoice).options(selectinload(Invoice.partner)).where(
            Invoice.status == InvoiceStatus.ok,
            Invoice.gross_huf.is_not(None), Invoice.due_date.is_not(None), Invoice.direction.is_not(None),
        )
    ).all()

    by_month: dict[str, dict[Direction, int]] = defaultdict(lambda: defaultdict(int))
    by_partner: dict[int, dict[Direction, int]] = defaultdict(lambda: defaultdict(int))
    partner_objs = {}
    totals: dict[Direction, int] = defaultdict(int)
    for inv in invoices:
        by_month[_month(inv.due_date)][inv.direction] += inv.gross_huf
        totals[inv.direction] += inv.gross_huf
        if inv.partner is not None:
            by_partner[inv.partner.id][inv.direction] += inv.gross_huf
            partner_objs[inv.partner.id] = inv.partner

    months: list[MonthPoint] = []
    if invoices:
        first = min(inv.due_date for inv in invoices)
        last = max(inv.due_date for inv in invoices)
        for m in _month_range(first, last):
            v = by_month.get(m, {})
            months.append(MonthPoint(month=m, incoming_huf=v.get(Direction.incoming, 0),
                                     outgoing_huf=v.get(Direction.outgoing, 0)))

    partner_rows = []
    for pid, v in by_partner.items():
        p = partner_objs[pid]
        aliases = sorted(p.aliases or {}, key=lambda a: -(p.aliases[a]))  # stabil: holtversenynél a rögzítési sorrend
        partner_rows.append(PartnerTotals(
            partner_id=pid, name=p.display_name, aliases=aliases,
            incoming_huf=v.get(Direction.incoming, 0), outgoing_huf=v.get(Direction.outgoing, 0),
        ))
    partner_rows.sort(key=lambda r: (-(r.incoming_huf + r.outgoing_huf), r.name.casefold()))

    counts = {st.value: 0 for st in InvoiceStatus}
    for st, n in s.execute(select(Invoice.status, func.count()).group_by(Invoice.status)):
        counts[st.value] = n
    counts["total"] = sum(counts.values())
    counts["provisional"] = sum(1 for inv in invoices if inv.fx_provisional)

    return ReportOut(
        months=months, partners=partner_rows,
        totals={"incoming_huf": totals[Direction.incoming], "outgoing_huf": totals[Direction.outgoing]},
        counts=counts,
    )
