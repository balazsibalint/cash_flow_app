from app.services.extraction.layout import compile_labels

INVOICE_NUMBER = [
    "szamlaszam", "szamla szama", "szamla sorszama", "sorszam",
    "invoice no", "invoice number", "invoice #", "invoice nr", "inv no",
    "rechnungsnummer", "rechnung nr", "rechnungs-nr", "re-nr",
    "n° de facture", "no de facture", "numero de facture", "facture n°", "facture no",
    "no de factura", "n° de factura", "numero de factura", "num. factura", "factura no", "factura n°",
    "fattura n", "fattura no", "numero fattura", "n. fattura",
    "numer faktury", "faktura nr", "nr faktury",
]

ISSUE_DATE = [
    "kiallitas datuma", "szamla kelte", "kelte", "kiallitas kelte",
    "invoice date", "date of issue", "issue date", "date issued",
    "rechnungsdatum", "ausstellungsdatum", "datum der rechnung",
    "date de facture", "date d'emission", "date de facturation",
    "fecha de emision", "fecha factura", "fecha de factura", "fecha de expedicion",
    "data fattura", "data emissione", "data documento",
    "data wystawienia",
]

SUPPLY_DATE = [
    "teljesites datuma", "teljesites kelte", "teljesites idopontja", "teljesites",
    "date of supply", "supply date", "delivery date", "date of delivery", "service date",
    "date of service", "performance date", "tax point",
    "leistungsdatum", "lieferdatum", "leistungszeitpunkt", "liefer-/leistungsdatum",
    "date de prestation", "date de livraison", "date d'execution",
    "fecha de operacion", "fecha de prestacion", "fecha de entrega", "fecha del servicio",
    "data prestazione", "data consegna", "data dell'operazione", "data operazione",
    "data sprzedazy", "data dostawy", "data wykonania uslugi", "data wykonania",
]

DUE_DATE = [
    "fizetesi hatarido", "esedekesseg", "fizetes hatarideje",
    "due date", "payment due", "date due", "payment due date", "due by", "pay by",
    "zahlbar bis", "fallig am", "falligkeitsdatum", "falligkeit", "zahlungsfrist",
    "date d'echeance", "echeance", "a payer avant le", "date limite de paiement",
    "fecha de vencimiento", "vencimiento", "fecha limite de pago",
    "data scadenza", "scadenza", "data di scadenza",
    "termin platnosci", "termin zaplaty",
]

CURRENCY = [
    "penznem", "currency", "wahrung", "devise", "moneda", "divisa", "valuta", "waluta",
]

GROSS_TOTAL = [
    "fizetendo osszesen", "fizetendo osszeg", "fizetendo", "brutto osszesen", "brutto vegosszeg", "vegosszeg",
    "szamla vegosszege", "osszesen fizetendo",
    "total due", "amount due", "total amount due", "balance due", "invoice total", "grand total",
    "total to pay", "total payable", "amount payable", "total (incl. vat)", "total incl. vat",
    "rechnungsbetrag", "gesamtbetrag", "zu zahlen", "zahlbetrag", "endbetrag", "bruttobetrag", "gesamtsumme",
    "net a payer ttc", "net a payer", "total ttc", "montant ttc", "montant total ttc",
    "total a pagar", "importe total", "total factura", "total importe",
    "totale documento", "totale fattura", "totale da pagare", "netto a pagare",
    "do zaplaty", "razem do zaplaty", "kwota do zaplaty",
]

NET_TOTAL = [
    "netto osszesen", "netto osszeg", "osszesen netto",
    "subtotal", "net total", "total net", "total excl. vat", "total (excl. vat)",
    "summe netto", "nettobetrag", "zwischensumme",
    "total ht", "montant ht", "total hors taxes",
    "base imponible total", "total base imponible",
    "totale imponibile", "imponibile totale",
    "razem netto", "suma netto",
]

VAT_TOTAL = [
    "afa osszesen", "afa osszeg", "osszes afa",
    "vat total", "total vat", "vat amount", "tax total", "total tax",
    "umsatzsteuer", "mehrwertsteuer", "summe mwst", "summe ust",
    "total tva", "montant tva", "montant total tva",
    "total iva", "cuota iva", "iva total", "importe iva",
    "totale iva",
    "razem vat", "kwota vat", "suma vat",
]
# Az önálló „IVA”, „TVA”, „MwSt” szándékosan hiányzik: ezek oszlopfejlécként is előfordulnak.

# Erős vevő-címkék: ezek egyértelműen a vevő blokkját vezetik be.
BUYER_BLOCK = [
    "vevo", "vevo adatai", "megrendelo",
    "bill to", "billed to", "invoice to", "sold to", "buyer",
    "rechnungsempfanger", "leistungsempfanger",
    "facture a", "facturer a", "destinataire",
    "cliente", "facturar a", "destinatario",
    "cessionario / committente", "cessionario", "committente",
    "nabywca", "odbiorca",
]
# Gyenge vevő-címkék: csak ha erős nincs (pl. „Customer No.” is kezdődhet így).
BUYER_BLOCK_WEAK = ["customer", "client", "kunde", "empfanger", "spett.le"]

PAYMENT_TERMS = [
    "fizetesi feltetel", "fizetesi feltetelek",
    "payment terms", "terms",
    "zahlungsziel", "zahlungsbedingungen",
    "conditions de paiement", "conditions de reglement",
    "condiciones de pago", "forma de pago",
    "pagamento", "termini di pagamento", "condizioni di pagamento",
    "termin platnosci", "warunki platnosci",
]

# Az ilyen sorokból sosem választunk végösszeget vagy ÁFÁ-t: forintra átszámolt tájékoztató adat (K-döntés).
EXCLUDE_AMOUNT_LINE = [
    "forintban", "in huf", "huf-ban", "ft-ban", "mnb arfolyam", "exchange rate", "arfolyam:",
]

# Dokumentumcímek – a kiállító nevének keresésekor ezeket átugorjuk.
DOCUMENT_TITLES = [
    "szamla", "invoice", "tax invoice", "rechnung", "facture", "factura", "fattura", "faktura", "faktura vat",
    "szamla / invoice", "eredeti", "eredeti peldany", "masolat", "original", "oryginal", "copy",
]

RX = {
    "invoice_number": compile_labels(INVOICE_NUMBER),
    "issue_date": compile_labels(ISSUE_DATE),
    "supply_date": compile_labels(SUPPLY_DATE),
    "due_date": compile_labels(DUE_DATE),
    "currency": compile_labels(CURRENCY),
    "gross": compile_labels(GROSS_TOTAL),
    "net": compile_labels(NET_TOTAL),
    "vat": compile_labels(VAT_TOTAL),
    "buyer": compile_labels(BUYER_BLOCK),
    "buyer_weak": compile_labels(BUYER_BLOCK_WEAK),
    "payment_terms": compile_labels(PAYMENT_TERMS),
}
