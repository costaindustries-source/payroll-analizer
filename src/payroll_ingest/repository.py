from collections.abc import Callable
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from payroll_ingest.dto import PayrollDocumentDTO
from payroll_ingest.extraction import RawExtractedDocument
from payroll_ingest.models import (
    Anomaly,
    Company,
    Employee,
    Employment,
    LeaveBalance,
    PayLine,
    PayrollDocument,
    PayrollPeriod,
    PayrollTotals,
    RawExtraction,
    Tax,
    Tfr,
)


def _get_or_create(session: Session, select_stmt, factory: Callable[[], object]):
    """SELECT-poi-INSERT con fallback su conflitto: se un altro processo del batch
    inserisce la stessa riga logica (stessa azienda/dipendente/periodo) tra la
    SELECT e il flush, il conflitto sul vincolo UNIQUE viene assorbito ripetendo
    la SELECT invece di propagare un IntegrityError e perdere l'intero documento."""
    existing = session.scalar(select_stmt)
    if existing is not None:
        return existing
    obj = factory()
    try:
        with session.begin_nested():
            session.add(obj)
            session.flush()
    except IntegrityError:
        existing = session.scalar(select_stmt)
        if existing is None:
            raise
        return existing
    return obj


def get_or_create_company(session: Session, dto) -> Company:
    stmt = select(Company).where(
        Company.ragione_sociale == dto.ragione_sociale,
        Company.codice_azienda == dto.codice_azienda,
    )
    return _get_or_create(
        session,
        stmt,
        lambda: Company(
            ragione_sociale=dto.ragione_sociale,
            indirizzo=dto.indirizzo,
            codice_azienda=dto.codice_azienda,
            inail_aut=dto.inail_aut,
            inail_del=dto.inail_del,
            inail_sede=dto.inail_sede,
            posizione_inps=dto.posizione_inps,
            pat_inail=dto.pat_inail,
        ),
    )


def get_or_create_employee(session: Session, dto) -> Employee:
    stmt = select(Employee).where(Employee.codice_fiscale == dto.codice_fiscale)
    return _get_or_create(
        session, stmt, lambda: Employee(cognome_nome=dto.cognome_nome, codice_fiscale=dto.codice_fiscale)
    )


def get_or_create_employment(session: Session, employee: Employee, company: Company, hire_date) -> Employment:
    stmt = select(Employment).where(
        Employment.employee_id == employee.id,
        Employment.company_id == company.id,
    )
    employment = _get_or_create(
        session,
        stmt,
        lambda: Employment(
            employee_id=employee.id,
            company_id=company.id,
            data_assunzione=hire_date,
            # valid_from e' NOT NULL: se la data di assunzione non e' stata
            # riconosciuta sul documento, usiamo una sentinella esplicita invece
            # di bloccare il salvataggio.
            valid_from=hire_date or date(1970, 1, 1),
        ),
    )
    # Un documento precedente potrebbe non aver riconosciuto la data di assunzione
    # (sentinella 1970-01-01): se questo documento la riconosce, aggiorniamo la riga
    # invece di lasciarci per sempre il valore sentinella.
    if hire_date is not None and employment.data_assunzione is None:
        employment.data_assunzione = hire_date
        employment.valid_from = hire_date
    return employment


def get_or_create_period(session: Session, dto) -> PayrollPeriod:
    stmt = select(PayrollPeriod).where(
        PayrollPeriod.mese == dto.mese,
        PayrollPeriod.anno == dto.anno,
        PayrollPeriod.tipo == dto.tipo.value,
    )
    return _get_or_create(
        session,
        stmt,
        lambda: PayrollPeriod(mese=dto.mese, anno=dto.anno, tipo=dto.tipo.value, label_originale=dto.label_originale),
    )


def save_document(
    session: Session,
    *,
    sha256: str,
    original_filename: str,
    status: str,
    template_name: str,
    parser_version: str,
    source_used_ocr: bool,
    dto: PayrollDocumentDTO,
    raw: RawExtractedDocument,
) -> PayrollDocument:
    # company/employee/period restano None quando il template non e' stato
    # riconosciuto (DTO di fallback con campi vuoti/mese=0): payroll_document ha le
    # FK nullable apposta per questo caso, e payroll_period ha un CHECK su mese
    # 1..12 che altrimenti farebbe fallire l'insert.
    company = get_or_create_company(session, dto.company) if dto.company.ragione_sociale else None
    employee = get_or_create_employee(session, dto.employee) if dto.employee.codice_fiscale else None
    if employee is not None and company is not None:
        get_or_create_employment(session, employee, company, dto.hire_date)
    period = get_or_create_period(session, dto.period) if dto.period.mese and dto.period.anno else None

    document = PayrollDocument(
        sha256=sha256,
        original_filename=original_filename,
        status=status,
        template_name=template_name,
        parser_version=parser_version,
        source_used_ocr=source_used_ocr,
        employee_id=employee.id if employee else None,
        company_id=company.id if company else None,
        period_id=period.id if period else None,
        hire_date=dto.hire_date,
    )
    session.add(document)
    session.flush()

    for pl in dto.pay_lines:
        session.add(
            PayLine(
                document_id=document.id,
                codice_causale=pl.codice,
                descrizione=pl.descrizione,
                categoria=pl.categoria.value,
                is_recognized=pl.is_recognized,
                importo_base=pl.importo_base,
                quantita=pl.quantita,
                unita=pl.unita,
                aliquota=pl.aliquota,
                trattenuta=pl.trattenuta,
                competenza=pl.competenza,
                raw_text=pl.raw_text,
            )
        )

    if dto.tax is not None:
        session.add(
            Tax(
                document_id=document.id,
                imponibile_irpef=dto.tax.imponibile_irpef,
                irpef_lorda=dto.tax.irpef_lorda,
                detrazioni_lav_dip=dto.tax.detrazioni_lav_dip,
                ritenute_irpef=dto.tax.ritenute_irpef,
                addizionale_regionale=dto.tax.addizionale_regionale,
                addizionale_regionale_regione=dto.tax.addizionale_regionale_regione,
                addizionale_comunale=dto.tax.addizionale_comunale,
                acconto_addizionale_comunale=dto.tax.acconto_addizionale_comunale,
            )
        )

    if dto.tfr is not None:
        session.add(
            Tfr(
                document_id=document.id,
                retribuzione_utile_tfr=dto.tfr.retribuzione_utile_tfr,
                quota_tfr_fondi=dto.tfr.quota_tfr_fondi,
                rivalutazione=dto.tfr.rivalutazione,
                imponibile_rivalutazione=dto.tfr.imponibile_rivalutazione,
                quota_anno=dto.tfr.quota_anno,
                anticipi=dto.tfr.anticipi,
            )
        )

    for lb in dto.leave_balances:
        session.add(
            LeaveBalance(
                document_id=document.id,
                tipo=lb.tipo,
                maturato=lb.maturato,
                goduto=lb.goduto,
                residuo=lb.residuo,
                residuo_ap=lb.residuo_ap,
            )
        )

    if dto.totals is not None:
        session.add(
            PayrollTotals(
                document_id=document.id,
                imponibile_inps=dto.totals.imponibile_inps,
                imponibile_inail=dto.totals.imponibile_inail,
                imponibile_irpef=dto.totals.imponibile_irpef,
                totale_competenze=dto.totals.totale_competenze,
                totale_trattenute=dto.totals.totale_trattenute,
                netto_mese=dto.totals.netto_mese,
                iban=dto.totals.iban,
                banca=dto.totals.banca,
            )
        )

    for a in dto.anomalies:
        session.add(
            Anomaly(
                document_id=document.id,
                tipo=a.tipo,
                severita=a.severita.value,
                messaggio=a.messaggio,
                campo=a.campo,
            )
        )

    session.add(
        RawExtraction(
            document_id=document.id,
            full_text=raw.first_page.full_text,
            words=[
                {"text": w.text, "x0": w.x0, "x1": w.x1, "top": w.top, "bottom": w.bottom}
                for w in raw.first_page.words
            ],
            unrecognized_rows=dto.unrecognized_row_texts,
            font_metadata={},
            ocr_used=raw.ocr_used,
        )
    )

    return document
