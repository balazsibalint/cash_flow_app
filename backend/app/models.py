import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DecimalText(TypeDecorator):
    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError(f"DecimalText csak Decimal értéket fogad, kapott: {type(value).__name__}")
        return format(value, "f")

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class InvoiceStatus(str, enum.Enum):
    ok = "ok"
    review = "review"  # ellenőrzendő (K5)
    pending_fx = "pending_fx"  # árfolyamra vár (K9)
    rejected = "rejected"  # elutasítva (K7)
    error = "error"  # feldolgozhatatlan


class ExtractionMethod(str, enum.Enum):
    rule = "rule"
    llm = "llm"


class Direction(str, enum.Enum):
    incoming = "incoming"
    outgoing = "outgoing"


def _str_enum(enum_cls: type[enum.Enum]) -> Enum:
    return Enum(enum_cls, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e])


class Partner(Base):
    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tax_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[dict] = mapped_column(JSON, default=dict)

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="partner")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("seller_tax_key", "invoice_number_norm", name="uq_invoice_seller_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))

    status: Mapped[InvoiceStatus] = mapped_column(_str_enum(InvoiceStatus), index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    extraction_method: Mapped[ExtractionMethod | None] = mapped_column(_str_enum(ExtractionMethod))
    doc_type: Mapped[str | None] = mapped_column(String(32))

    invoice_number: Mapped[str | None] = mapped_column(String(64))
    invoice_number_norm: Mapped[str | None] = mapped_column(String(64))
    seller_name: Mapped[str | None] = mapped_column(String(255))
    seller_tax: Mapped[str | None] = mapped_column(String(64))
    seller_tax_key: Mapped[str | None] = mapped_column(String(64))
    buyer_name: Mapped[str | None] = mapped_column(String(255))
    buyer_tax: Mapped[str | None] = mapped_column(String(64))

    issue_date: Mapped[date | None] = mapped_column(Date)
    supply_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    supply_date_inferred: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date_inferred: Mapped[bool] = mapped_column(Boolean, default=False)

    currency: Mapped[str | None] = mapped_column(String(3))
    net_amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    vat_amount: Mapped[Decimal | None] = mapped_column(DecimalText)
    gross_amount: Mapped[Decimal | None] = mapped_column(DecimalText)

    direction: Mapped[Direction | None] = mapped_column(_str_enum(Direction))
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id", ondelete="SET NULL"), index=True)
    partner: Mapped[Partner | None] = relationship(back_populates="invoices")

    fx_rate: Mapped[Decimal | None] = mapped_column(DecimalText)
    fx_unit: Mapped[int | None] = mapped_column(Integer)
    fx_rate_date: Mapped[date | None] = mapped_column(Date)
    fx_provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    gross_huf: Mapped[int | None] = mapped_column(Integer)

    raw_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate: Mapped[Decimal] = mapped_column(DecimalText)
    unit: Mapped[int] = mapped_column(Integer, default=1)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MnbFetch(Base):
    __tablename__ = "mnb_fetches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
