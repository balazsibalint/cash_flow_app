import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from app.config import get_settings
from app.services.extraction.rules import determine_direction, extract, own_tax_keys
from app.services.pdf_text import PdfReadError, load_pdf

FIELDS = [
    "invoice_number", "seller_name", "seller_tax", "buyer_name", "buyer_tax", "issue_date", "supply_date",
    "due_date", "currency", "gross_amount", "direction",
]


def row_for(path: Path) -> dict:
    s = get_settings()
    try:
        doc = load_pdf(path)
    except PdfReadError as exc:
        return {"error": str(exc)}
    inv = extract(doc)
    direction = determine_direction(inv, own_tax_keys(s.own_tax_number, s.own_eu_vat), s.own_company_name)
    as_str = lambda v: None if v is None else (format(v, "f") if isinstance(v, Decimal) else str(v))
    return {
        "invoice_number": inv.invoice_number,
        "seller_name": inv.seller.name,
        "seller_tax": inv.seller.tax_id,
        "buyer_name": inv.buyer.name,
        "buyer_tax": inv.buyer.tax_id,
        "issue_date": as_str(inv.issue_date),
        "supply_date": as_str(inv.supply_date),
        "due_date": as_str(inv.due_date),
        "currency": inv.currency,
        "gross_amount": as_str(inv.gross_amount),
        "direction": direction,
        "_net": as_str(inv.net_amount),
        "_vat": as_str(inv.vat_amount),
        "_terms": inv.payment_terms_days,
        "_doc_type": inv.doc_type,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--json", help="kimeneti JSON-fájl")
    args = ap.parse_args()

    rows = {p.name: row_for(p) for p in sorted(Path(args.folder).glob("*.pdf"))}
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    missing = 0
    for name, r in rows.items():
        empty = [f for f in FIELDS if not r.get(f)]
        sum_ok = ""
        if r.get("_net") and r.get("_vat") and r.get("gross_amount"):
            sum_ok = "" if Decimal(r["_net"]) + Decimal(r["_vat"]) == Decimal(r["gross_amount"]) else " SUM!"
        flag = (" HIÁNYZIK: " + ",".join(empty) if empty else "") + sum_ok
        missing += bool(flag)
        print(f"{name:34} {r.get('direction') or '-':8} {r.get('invoice_number') or '-':16} "
              f"{(r.get('seller_name') or '-')[:22]:22} | {(r.get('buyer_name') or '-')[:22]:22} "
              f"{r.get('issue_date') or '-'} {r.get('supply_date') or '-'} {r.get('due_date') or '-'} "
              f"{r.get('gross_amount') or '-':>12} {r.get('currency') or '-'}{flag}")
    print(f"\n{len(rows)} fájl, {missing} hiányos vagy ellentmondásos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
