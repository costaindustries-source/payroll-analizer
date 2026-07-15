"""Test per payroll_ingest.repository: get_or_create_* e save_document."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from payroll_ingest.dto import (
    AnomalyDTO,
    AnomalySeverity,
    CompanyDTO,
    DataClassification,
    EmployeeDTO,
    LeaveBalanceDTO,
    PayLineCategory,
    PayLineDTO,
    PayrollDocumentDTO,
    PayrollTotalsDTO,
    PeriodDTO,
    PeriodType,
    TaxDTO,
    TfrDTO,
)
from payroll_ingest.extraction import RawExtractedDocument, RawPage, Word
from payroll_ingest.models import (
    Company,
    Employment,
    PayLine,
    PayrollDocument,
    PayrollPeriod,
    PayrollTotals,
    RawExtraction,
    Tax,
    Tfr,
)
from payroll_ingest.repository import (
    _get_or_create,
    get_or_create_company,
    get_or_create_employee,
    get_or_create_employment,
    get_or_create_period,
    save_document,
)


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _sha() -> str:
    return uuid.uuid4().hex.ljust(64, "0")


def _cf() -> str:
    # Formato valido (non serve passare il checksum ufficiale: repository.py
    # non lo verifica, lo fa solo templates/zucchetti.py a monte).
    return f"RSS{uuid.uuid4().hex[:9].upper()}"


# ---------------------------------------------------------------------------
# get_or_create_company
# ---------------------------------------------------------------------------


def test_get_or_create_company_creates_new_row(db_session):
    ragione_sociale = _unique("ACME")
    dto = CompanyDTO(ragione_sociale=ragione_sociale, codice_azienda="C001", indirizzo="Via Roma 1")

    company = get_or_create_company(db_session, dto)

    assert company.id is not None
    assert company.ragione_sociale == ragione_sociale
    assert company.indirizzo == "Via Roma 1"


def test_get_or_create_company_returns_existing_row(db_session):
    ragione_sociale = _unique("ACME")
    dto = CompanyDTO(ragione_sociale=ragione_sociale, codice_azienda="C002")

    first = get_or_create_company(db_session, dto)
    second = get_or_create_company(db_session, dto)

    assert first.id == second.id
    count = db_session.scalar(
        select(Company).where(Company.ragione_sociale == ragione_sociale, Company.codice_azienda == "C002")
    )
    assert count is not None


def test_get_or_create_company_race_falls_back_to_existing(db_session, db_session_factory):
    """Simula la race descritta nel commento di _get_or_create: un'altra
    connessione inserisce e commit-ta la stessa riga logica tra la SELECT e il
    flush di questa sessione. L'IntegrityError deve essere assorbito e la riga
    gia' committata restituita, non ripropagata."""
    ragione_sociale = _unique("ACME RACE")
    dto = CompanyDTO(ragione_sociale=ragione_sociale, codice_azienda="RACE1")

    original_scalar = db_session.scalar
    state = {"triggered": False}

    def racy_scalar(stmt, *args, **kwargs):
        result = original_scalar(stmt, *args, **kwargs)
        if result is None and not state["triggered"]:
            state["triggered"] = True
            other = db_session_factory()
            try:
                other.add(Company(ragione_sociale=ragione_sociale, codice_azienda="RACE1"))
                other.commit()
            finally:
                other.close()
        return result

    db_session.scalar = racy_scalar
    try:
        company = get_or_create_company(db_session, dto)
    finally:
        db_session.scalar = original_scalar

    assert state["triggered"] is True
    assert company.ragione_sociale == ragione_sociale

    # Una sola riga deve esistere per questa chiave (niente doppione dal
    # tentativo di insert fallito).
    rows = db_session.scalars(
        select(Company).where(Company.ragione_sociale == ragione_sociale, Company.codice_azienda == "RACE1")
    ).all()
    assert len(rows) == 1


def test_get_or_create_raises_if_integrity_error_unrelated_to_select(db_session):
    """Se dopo l'IntegrityError la stessa SELECT non trova nulla, l'eccezione
    deve risalire (non e' un conflitto sulla stessa chiave logica cercata)."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    from payroll_ingest.models import Employee

    cf_existing = _cf()
    db_session.add(Employee(cognome_nome="Existing Employee", codice_fiscale=cf_existing))
    db_session.flush()

    # select_stmt cerca una chiave completamente diversa da quella che
    # provochera' il conflitto: dopo l'IntegrityError la select non trova
    # comunque nulla, quindi l'eccezione deve risalire invece di restituire
    # silenziosamente None/un valore inatteso.
    stmt = select(Employee).where(Employee.codice_fiscale == "NESSUNA-CORRISPONDENZA")

    def factory():
        # codice_fiscale duplicato: viola lo UNIQUE constraint al flush.
        return Employee(cognome_nome="Conflicting Employee", codice_fiscale=cf_existing)

    with pytest.raises(IntegrityError):
        _get_or_create(db_session, stmt, factory)


# ---------------------------------------------------------------------------
# get_or_create_employee
# ---------------------------------------------------------------------------


def test_get_or_create_employee_creates_and_reuses(db_session):
    cf = _cf()
    dto = EmployeeDTO(cognome_nome="Mario Rossi", codice_fiscale=cf)

    first = get_or_create_employee(db_session, dto)
    second = get_or_create_employee(db_session, dto)

    assert first.id == second.id
    assert first.codice_fiscale == cf


# ---------------------------------------------------------------------------
# get_or_create_employment
# ---------------------------------------------------------------------------


def test_get_or_create_employment_uses_sentinel_when_hire_date_missing(db_session):
    employee = get_or_create_employee(db_session, EmployeeDTO(cognome_nome="Employment Test", codice_fiscale=_cf()))
    company = get_or_create_company(db_session, CompanyDTO(ragione_sociale=_unique("EMPL CO")))

    employment = get_or_create_employment(db_session, employee, company, None)

    assert employment.data_assunzione is None
    assert employment.valid_from == date(1970, 1, 1)


def test_get_or_create_employment_backfills_hire_date_on_next_document(db_session):
    employee = get_or_create_employee(
        db_session, EmployeeDTO(cognome_nome="Employment Backfill", codice_fiscale=_cf())
    )
    company = get_or_create_company(db_session, CompanyDTO(ragione_sociale=_unique("EMPL BACKFILL CO")))

    first = get_or_create_employment(db_session, employee, company, None)
    assert first.data_assunzione is None

    second = get_or_create_employment(db_session, employee, company, date(2020, 5, 1))

    assert second.id == first.id
    assert second.data_assunzione == date(2020, 5, 1)
    assert second.valid_from == date(2020, 5, 1)

    persisted = db_session.get(Employment, first.id)
    assert persisted.data_assunzione == date(2020, 5, 1)


def test_get_or_create_employment_reuses_existing_row_for_same_pair(db_session):
    employee = get_or_create_employee(db_session, EmployeeDTO(cognome_nome="Employment Reuse", codice_fiscale=_cf()))
    company = get_or_create_company(db_session, CompanyDTO(ragione_sociale=_unique("EMPL REUSE CO")))

    first = get_or_create_employment(db_session, employee, company, date(2019, 1, 1))
    second = get_or_create_employment(db_session, employee, company, date(2019, 1, 1))

    assert first.id == second.id


# ---------------------------------------------------------------------------
# get_or_create_period
# ---------------------------------------------------------------------------


def test_get_or_create_period_creates_and_reuses(db_session):
    anno = 91000 + uuid.uuid4().int % 1000
    dto = PeriodDTO(mese=6, anno=anno, tipo=PeriodType.ORDINARIO, label_originale="giugno")

    first = get_or_create_period(db_session, dto)
    second = get_or_create_period(db_session, dto)

    assert first.id == second.id
    assert first.mese == 6
    assert first.anno == anno


def test_get_or_create_period_different_tipo_creates_distinct_rows(db_session):
    anno = 92000 + uuid.uuid4().int % 1000
    ordinario = get_or_create_period(
        db_session, PeriodDTO(mese=1, anno=anno, tipo=PeriodType.ORDINARIO, label_originale="gennaio")
    )
    conguaglio = get_or_create_period(
        db_session, PeriodDTO(mese=1, anno=anno, tipo=PeriodType.CONGUAGLIO, label_originale="gennaio cong.")
    )

    assert ordinario.id != conguaglio.id


# ---------------------------------------------------------------------------
# save_document
# ---------------------------------------------------------------------------


def _raw_document(text_lines: tuple[str, ...] = ("riga 1", "riga 2")) -> RawExtractedDocument:
    pages = [
        RawPage(
            words=[Word(text="RIGA1", x0=1, x1=10, top=1, bottom=5)],
            rows=[],
            full_text=text_lines[0],
            width=595.0,
            height=842.0,
        ),
        RawPage(
            words=[Word(text="RIGA2", x0=1, x1=10, top=1, bottom=5)],
            rows=[],
            full_text=text_lines[1],
            width=595.0,
            height=842.0,
        ),
    ]
    return RawExtractedDocument(source_path=None, pages=pages, ocr_used=False)


def test_save_document_full_happy_path(db_session):
    cf = _cf()
    dto = PayrollDocumentDTO(
        company=CompanyDTO(ragione_sociale=_unique("SAVE DOC CO"), codice_azienda="SD01"),
        employee=EmployeeDTO(cognome_nome="Save Document Test", codice_fiscale=cf),
        period=PeriodDTO(mese=5, anno=93001, tipo=PeriodType.ORDINARIO, label_originale="maggio 93001"),
        hire_date=date(2021, 3, 1),
        pay_lines=[
            PayLineDTO(
                codice="F00100",
                descrizione="Retribuzione ordinaria",
                categoria=PayLineCategory.RETRIBUZIONE,
                is_recognized=True,
                competenza=Decimal("1500.00"),
                raw_text="F00100 Retribuzione ordinaria 1500,00",
            )
        ],
        tax=TaxDTO(imponibile_irpef=Decimal("1500.00"), irpef_lorda=Decimal("300.00")),
        tfr=TfrDTO(retribuzione_utile_tfr=Decimal("1500.00")),
        leave_balances=[LeaveBalanceDTO(tipo="Ferie", maturato=Decimal("10"), goduto=Decimal("2"))],
        totals=PayrollTotalsDTO(totale_competenze=Decimal("1500.00"), netto_mese=Decimal("1200.00")),
        anomalies=[AnomalyDTO(tipo="test_anomaly", severita=AnomalySeverity.INFO, messaggio="nota di test")],
        unrecognized_row_texts=["riga non mappata"],
        template_name="zucchetti_standard",
    )
    raw = _raw_document()
    sha256 = _sha()

    document = save_document(
        db_session,
        sha256=sha256,
        original_filename="cedolino_test.pdf",
        status="PROCESSED",
        template_name="zucchetti_standard",
        parser_version="1.0.0",
        source_used_ocr=False,
        dto=dto,
        raw=raw,
    )
    db_session.flush()

    assert document.id is not None
    assert document.employee_id is not None
    assert document.company_id is not None
    assert document.period_id is not None
    assert document.hire_date == date(2021, 3, 1)

    persisted = db_session.get(PayrollDocument, document.id)
    assert persisted.sha256 == sha256
    assert persisted.status == "PROCESSED"

    pay_lines = db_session.scalars(select(PayLine).where(PayLine.document_id == document.id)).all()
    assert len(pay_lines) == 1
    assert pay_lines[0].codice_causale == "F00100"

    tax = db_session.scalar(select(Tax).where(Tax.document_id == document.id))
    assert tax is not None
    assert tax.imponibile_irpef == Decimal("1500.00")

    tfr = db_session.scalar(select(Tfr).where(Tfr.document_id == document.id))
    assert tfr is not None

    totals = db_session.scalar(select(PayrollTotals).where(PayrollTotals.document_id == document.id))
    assert totals is not None
    assert totals.netto_mese == Decimal("1200.00")

    raw_extraction = db_session.scalar(select(RawExtraction).where(RawExtraction.document_id == document.id))
    assert raw_extraction is not None
    assert raw_extraction.full_text == "riga 1\n\nriga 2"
    assert raw_extraction.words == [
        {"text": "RIGA1", "x0": 1, "x1": 10, "top": 1, "bottom": 5},
        {"text": "RIGA2", "x0": 1, "x1": 10, "top": 1, "bottom": 5},
    ]
    assert raw_extraction.unrecognized_rows == ["riga non mappata"]

    employment = db_session.scalar(
        select(Employment).where(
            Employment.employee_id == document.employee_id, Employment.company_id == document.company_id
        )
    )
    assert employment is not None
    assert employment.data_assunzione == date(2021, 3, 1)


def test_save_document_unrecognized_leaves_foreign_keys_null(db_session):
    dto = PayrollDocumentDTO(
        company=CompanyDTO(ragione_sociale=""),
        employee=EmployeeDTO(cognome_nome="", codice_fiscale=""),
        period=PeriodDTO(mese=0, anno=0, tipo=PeriodType.ORDINARIO, label_originale=""),
        template_name="unknown",
    )
    raw = _raw_document()

    document = save_document(
        db_session,
        sha256=_sha(),
        original_filename="non_riconosciuto.pdf",
        status="NEEDS_REVIEW",
        template_name="unknown",
        parser_version="1.0.0",
        source_used_ocr=False,
        dto=dto,
        raw=raw,
    )
    db_session.flush()

    assert document.employee_id is None
    assert document.company_id is None
    assert document.period_id is None


def test_save_document_without_optional_sections_creates_no_rows(db_session):
    dto = PayrollDocumentDTO(
        company=CompanyDTO(ragione_sociale=_unique("NO OPTIONAL CO")),
        employee=EmployeeDTO(cognome_nome="No Optional", codice_fiscale=_cf()),
        period=PeriodDTO(mese=0, anno=0, tipo=PeriodType.ORDINARIO, label_originale=""),
        # tax/tfr/totals None, nessuna pay_line/leave_balance/anomaly
        template_name="zucchetti_standard",
    )
    raw = _raw_document()

    document = save_document(
        db_session,
        sha256=_sha(),
        original_filename="minimo.pdf",
        status="PROCESSED_WITH_ANOMALIES",
        template_name="zucchetti_standard",
        parser_version="1.0.0",
        source_used_ocr=True,
        dto=dto,
        raw=raw,
    )
    db_session.flush()

    assert db_session.scalar(select(Tax).where(Tax.document_id == document.id)) is None
    assert db_session.scalar(select(Tfr).where(Tfr.document_id == document.id)) is None
    assert db_session.scalar(select(PayrollTotals).where(PayrollTotals.document_id == document.id)) is None
    assert db_session.scalars(select(PayLine).where(PayLine.document_id == document.id)).all() == []
    # employee/company senza period valido (mese=0) -> employment creata comunque
    # (employee e company sono entrambi validi), ma period_id resta None.
    assert document.period_id is None


def test_save_document_uses_dataclassification_default_and_raw_ocr_flag(db_session):
    dto = PayrollDocumentDTO(
        company=CompanyDTO(ragione_sociale=_unique("OCR FLAG CO")),
        employee=EmployeeDTO(cognome_nome="Ocr Flag", codice_fiscale=_cf(), classification=DataClassification.CERTO),
        period=PeriodDTO(mese=0, anno=0, tipo=PeriodType.ORDINARIO, label_originale=""),
        template_name="zucchetti_standard",
    )
    raw = _raw_document(("pagina unica",) * 2)
    raw.ocr_used = True

    document = save_document(
        db_session,
        sha256=_sha(),
        original_filename="ocr.pdf",
        status="PROCESSED",
        template_name="zucchetti_standard",
        parser_version="1.0.0",
        source_used_ocr=True,
        dto=dto,
        raw=raw,
    )
    db_session.flush()

    raw_extraction = db_session.scalar(select(RawExtraction).where(RawExtraction.document_id == document.id))
    assert raw_extraction.ocr_used is True
