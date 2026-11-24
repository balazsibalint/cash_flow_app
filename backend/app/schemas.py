from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.models import Direction, ExtractionMethod, InvoiceStatus

Money = Annotated[Decimal, PlainSerializer(lambda d: format(d, "f"), return_type=str, when_used="json")]


class Message(BaseModel):
    code: str
    level: Literal["info", "warning", "error"]
    text: str


class Party(BaseModel):
    name: str | None = None
    tax_id: str | None = None  # ahogy a számlán áll
    tax_keys: list[str] = Field(default_factory=list)  # az összes talált adószám normalizálva


class ExtractedInvoice(BaseModel):
    doc_type: str | None = None
    invoice_number: str | None = None
    seller: Party = Field(default_factory=Party)
    buyer: Party = Field(default_factory=Party)
    issue_date: date | None = None
    supply_date: date | None = None
    due_date: date | None = None
    payment_terms_days: int | None = None
    currency: str | None = None
    net_amount: Decimal | None = None
    vat_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    line_items_net_sum: Decimal | None = None


class PartnerRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tax_key: str
    display_name: str


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    status: InvoiceStatus
    status_reason: str | None
    messages: list[Message]
    extraction_method: ExtractionMethod | None
    doc_type: str | None

    invoice_number: str | None
    seller_name: str | None
    seller_tax: str | None
    buyer_name: str | None
    buyer_tax: str | None
    issue_date: date | None
    supply_date: date | None
    due_date: date | None
    supply_date_inferred: bool
    due_date_inferred: bool

    currency: str | None
    net_amount: Money | None
    vat_amount: Money | None
    gross_amount: Money | None
    direction: Direction | None
    partner: PartnerRef | None

    fx_rate: Money | None
    fx_unit: int | None
    fx_rate_date: date | None
    fx_provisional: bool
    gross_huf: int | None
    created_at: datetime


UploadResultKind = Literal["created", "duplicate", "rejected", "review", "error"]


class UploadResult(BaseModel):
    result: UploadResultKind
    message: str
    invoice: InvoiceOut | None = None


class MonthPoint(BaseModel):
    month: str  # ÉÉÉÉ-HH
    incoming_huf: int
    outgoing_huf: int


class PartnerTotals(BaseModel):
    partner_id: int
    name: str
    aliases: list[str]
    incoming_huf: int
    outgoing_huf: int


class ReportOut(BaseModel):
    months: list[MonthPoint]
    partners: list[PartnerTotals]
    totals: dict[str, int]
    counts: dict[str, int]


class HealthOut(BaseModel):
    status: Literal["ok"]
    llm_enabled: bool
