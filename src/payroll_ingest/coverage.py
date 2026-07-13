"""Verifica di copertura annuale: per ogni anno, quanti documenti risultano
completamente caricati (status PROCESSED, zero anomalie) e quali file hanno
anomalie o sono stati scartati, cosi' da poter individuare a colpo d'occhio
un'annualita' con documenti mancanti o da rivedere."""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from payroll_ingest.dto import DocumentStatus
from payroll_ingest.models import PayrollDocument, PayrollPeriod


@dataclass
class DocumentIssue:
    filename: str
    status: str
    anomalie: list[str]


@dataclass
class YearCoverage:
    anno: int
    totale: int = 0
    caricati: int = 0
    problemi: list[DocumentIssue] = field(default_factory=list)


def check_years(session: Session) -> tuple[list[YearCoverage], list[DocumentIssue]]:
    """Ritorna (copertura per anno, ordinata per anno; documenti senza annualita'
    attribuibile). Un documento non ha annualita' quando il periodo non e' stato
    riconosciuto (template non riconosciuto o mese/anno mancanti in map_document,
    v. save_document): payroll_document.period_id resta NULL in quel caso."""
    stmt = (
        select(PayrollDocument)
        .outerjoin(PayrollPeriod, PayrollDocument.period_id == PayrollPeriod.id)
        .options(joinedload(PayrollDocument.period), joinedload(PayrollDocument.anomalies))
    )
    documents = session.scalars(stmt).unique().all()

    by_year: dict[int, YearCoverage] = {}
    senza_anno: list[DocumentIssue] = []

    for doc in sorted(documents, key=lambda d: d.original_filename):
        anno = doc.period.anno if doc.period else None

        if doc.status == DocumentStatus.PROCESSED.value:
            if anno is not None:
                coverage = by_year.setdefault(anno, YearCoverage(anno=anno))
                coverage.totale += 1
                coverage.caricati += 1
            continue

        issue = DocumentIssue(
            filename=doc.original_filename,
            status=doc.status,
            anomalie=[f"[{a.severita}] {a.tipo}: {a.messaggio}" for a in doc.anomalies],
        )
        if anno is None:
            senza_anno.append(issue)
            continue

        coverage = by_year.setdefault(anno, YearCoverage(anno=anno))
        coverage.totale += 1
        coverage.problemi.append(issue)

    return [by_year[anno] for anno in sorted(by_year)], senza_anno
