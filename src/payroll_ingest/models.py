import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NUMERIC = Numeric(14, 5)


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Company(Base):
    __tablename__ = "company"

    id: Mapped[uuid.UUID] = _uuid_pk()
    ragione_sociale: Mapped[str] = mapped_column(String(255), nullable=False)
    indirizzo: Mapped[str | None] = mapped_column(String(255))
    codice_azienda: Mapped[str | None] = mapped_column(String(32))
    inail_aut: Mapped[str | None] = mapped_column(String(32))
    inail_del: Mapped[str | None] = mapped_column(String(32))
    inail_sede: Mapped[str | None] = mapped_column(String(32))
    posizione_inps: Mapped[str | None] = mapped_column(String(64))
    pat_inail: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("ragione_sociale", "codice_azienda", name="uq_company_identity"),)


class Employee(Base):
    __tablename__ = "employee"

    id: Mapped[uuid.UUID] = _uuid_pk()
    cognome_nome: Mapped[str] = mapped_column(String(255), nullable=False)
    codice_fiscale: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Employment(Base):
    """Rapporto dipendente<->azienda con validita' temporale (gestisce il cambio datore)."""

    __tablename__ = "employment"

    id: Mapped[uuid.UUID] = _uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employee.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("company.id"), nullable=False)
    matricola: Mapped[str | None] = mapped_column(String(32))
    data_assunzione: Mapped[date | None] = mapped_column(Date)
    data_cessazione: Mapped[date | None] = mapped_column(Date)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (UniqueConstraint("employee_id", "company_id", "valid_from", name="uq_employment_span"),)


class PayrollPeriod(Base):
    __tablename__ = "payroll_period"

    id: Mapped[uuid.UUID] = _uuid_pk()
    mese: Mapped[int] = mapped_column(nullable=False)
    anno: Mapped[int] = mapped_column(nullable=False)
    tipo: Mapped[str] = mapped_column(String(32), nullable=False)
    label_originale: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("mese", "anno", "tipo", name="uq_period"),
        CheckConstraint("mese >= 1 AND mese <= 12", name="ck_period_mese"),
    )


class PayrollDocument(Base):
    __tablename__ = "payroll_document"

    id: Mapped[uuid.UUID] = _uuid_pk()
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    template_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_used_ocr: Mapped[bool] = mapped_column(default=False)
    processed_path: Mapped[str | None] = mapped_column(String(512))
    error_path: Mapped[str | None] = mapped_column(String(512))

    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employee.id"), index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("company.id"), index=True)
    period_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payroll_period.id"), index=True)

    hire_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    employee: Mapped[Employee | None] = relationship()
    company: Mapped[Company | None] = relationship()
    period: Mapped[PayrollPeriod | None] = relationship()

    pay_lines: Mapped[list["PayLine"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    tax: Mapped["Tax | None"] = relationship(back_populates="document", cascade="all, delete-orphan", uselist=False)
    tfr: Mapped["Tfr | None"] = relationship(back_populates="document", cascade="all, delete-orphan", uselist=False)
    leave_balances: Mapped[list["LeaveBalance"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    totals: Mapped["PayrollTotals | None"] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )
    anomalies: Mapped[list["Anomaly"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    raw_extraction: Mapped["RawExtraction | None"] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("employee_id", "company_id", "period_id", name="uq_document_logical_key"),
    )


class PayLine(Base):
    """Riga retributiva dinamica (competenza/trattenuta/contributo)."""

    __tablename__ = "pay_line"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payroll_document.id"), nullable=False, index=True)
    codice_causale: Mapped[str | None] = mapped_column(String(16))
    descrizione: Mapped[str] = mapped_column(String(255), nullable=False)
    categoria: Mapped[str] = mapped_column(String(32), nullable=False)
    is_recognized: Mapped[bool] = mapped_column(default=True)
    importo_base: Mapped[Decimal | None] = mapped_column(NUMERIC)
    quantita: Mapped[Decimal | None] = mapped_column(NUMERIC)
    unita: Mapped[str | None] = mapped_column(String(8))
    aliquota: Mapped[Decimal | None] = mapped_column(NUMERIC)
    trattenuta: Mapped[Decimal | None] = mapped_column(NUMERIC)
    competenza: Mapped[Decimal | None] = mapped_column(NUMERIC)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped[PayrollDocument] = relationship(back_populates="pay_lines")


class Tax(Base):
    __tablename__ = "tax"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payroll_document.id"), nullable=False, unique=True
    )
    imponibile_irpef: Mapped[Decimal | None] = mapped_column(NUMERIC)
    irpef_lorda: Mapped[Decimal | None] = mapped_column(NUMERIC)
    detrazioni_lav_dip: Mapped[Decimal | None] = mapped_column(NUMERIC)
    ritenute_irpef: Mapped[Decimal | None] = mapped_column(NUMERIC)
    addizionale_regionale: Mapped[Decimal | None] = mapped_column(NUMERIC)
    addizionale_regionale_regione: Mapped[str | None] = mapped_column(String(64))
    addizionale_comunale: Mapped[Decimal | None] = mapped_column(NUMERIC)
    acconto_addizionale_comunale: Mapped[Decimal | None] = mapped_column(NUMERIC)

    document: Mapped[PayrollDocument] = relationship(back_populates="tax")


class Tfr(Base):
    __tablename__ = "tfr"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payroll_document.id"), nullable=False, unique=True
    )
    retribuzione_utile_tfr: Mapped[Decimal | None] = mapped_column(NUMERIC)
    quota_tfr_fondi: Mapped[Decimal | None] = mapped_column(NUMERIC)
    rivalutazione: Mapped[Decimal | None] = mapped_column(NUMERIC)
    imponibile_rivalutazione: Mapped[Decimal | None] = mapped_column(NUMERIC)
    quota_anno: Mapped[Decimal | None] = mapped_column(NUMERIC)
    anticipi: Mapped[Decimal | None] = mapped_column(NUMERIC)

    document: Mapped[PayrollDocument] = relationship(back_populates="tfr")


class LeaveBalance(Base):
    __tablename__ = "leave_balance"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payroll_document.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(32), nullable=False)
    maturato: Mapped[Decimal | None] = mapped_column(NUMERIC)
    goduto: Mapped[Decimal | None] = mapped_column(NUMERIC)
    residuo: Mapped[Decimal | None] = mapped_column(NUMERIC)
    residuo_ap: Mapped[Decimal | None] = mapped_column(NUMERIC)

    document: Mapped[PayrollDocument] = relationship(back_populates="leave_balances")


class PayrollTotals(Base):
    __tablename__ = "payroll_totals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payroll_document.id"), nullable=False, unique=True
    )
    imponibile_inps: Mapped[Decimal | None] = mapped_column(NUMERIC)
    imponibile_inail: Mapped[Decimal | None] = mapped_column(NUMERIC)
    imponibile_irpef: Mapped[Decimal | None] = mapped_column(NUMERIC)
    totale_competenze: Mapped[Decimal | None] = mapped_column(NUMERIC)
    totale_trattenute: Mapped[Decimal | None] = mapped_column(NUMERIC)
    netto_mese: Mapped[Decimal | None] = mapped_column(NUMERIC)
    iban: Mapped[str | None] = mapped_column(String(34))
    banca: Mapped[str | None] = mapped_column(String(255))

    document: Mapped[PayrollDocument] = relationship(back_populates="totals")


class Anomaly(Base):
    __tablename__ = "anomaly"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payroll_document.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(64), nullable=False)
    severita: Mapped[str] = mapped_column(String(16), nullable=False)
    messaggio: Mapped[str] = mapped_column(Text, nullable=False)
    campo: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[PayrollDocument] = relationship(back_populates="anomalies")

    __table_args__ = (
        CheckConstraint("severita IN ('info','warning','error')", name="ck_anomaly_severita"),
    )


class RawExtraction(Base):
    __tablename__ = "raw_extraction"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payroll_document.id"), nullable=False, unique=True
    )
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    words: Mapped[list] = mapped_column(JSONB, nullable=False)
    unrecognized_rows: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    font_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ocr_used: Mapped[bool] = mapped_column(default=False)

    document: Mapped[PayrollDocument] = relationship(back_populates="raw_extraction")


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payroll_document.id"), index=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
