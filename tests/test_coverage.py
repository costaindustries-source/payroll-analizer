"""Test per payroll_ingest.coverage.check_years: aggregazione documenti per
anno/stato. check_years fa una select senza filtro sull'intera tabella
payroll_document, quindi in uno schema di test condiviso con altri file di
test potrebbero comparire anche righe committate altrove: per non essere
fragili filtriamo sempre i risultati sugli anni/filename unici generati da
questo modulo, invece di assumere che la tabella contenga solo le nostre righe."""

import random
import uuid

from payroll_ingest.coverage import check_years
from payroll_ingest.dto import DocumentStatus
from payroll_ingest.models import Anomaly, PayrollDocument, PayrollPeriod

# Range di anni improbabile in dati reali/altri test, per isolare le nostre righe
# in uno schema potenzialmente condiviso senza dover filtrare a mano ogni query.
_YEAR_BASE = 90000


def _unique_year() -> int:
    return _YEAR_BASE + random.randint(0, 9_999_999)


def _make_period(session, anno: int, mese: int = 1) -> PayrollPeriod:
    period = PayrollPeriod(mese=mese, anno=anno, tipo="ordinario", label_originale="test")
    session.add(period)
    session.flush()
    return period


def _make_document(
    session,
    *,
    filename: str,
    status: str,
    sha256: str,
    period: PayrollPeriod | None = None,
) -> PayrollDocument:
    doc = PayrollDocument(
        sha256=sha256,
        original_filename=filename,
        status=status,
        template_name="zucchetti_standard",
        parser_version="1.0.0",
        source_used_ocr=False,
        period_id=period.id if period else None,
    )
    session.add(doc)
    session.flush()
    return doc


def _sha(tag: str) -> str:
    # sha256 e' UNIQUE nello schema: usiamo un valore random per evitare
    # collisioni con righe committate da altri file/gruppi di test nello
    # stesso schema condiviso, il tag serve solo a leggere il test piu' facilmente.
    return uuid.uuid4().hex.ljust(64, "0")


def _find_year(per_anno, anno):
    return next(c for c in per_anno if c.anno == anno)


def test_no_documents_returns_empty(db_session):
    # Anno improbabile: nessun documento in schema per questo anno specifico.
    anno = _unique_year()
    per_anno, senza_anno = check_years(db_session)
    assert not any(c.anno == anno for c in per_anno)


def test_processed_document_counts_as_caricato(db_session):
    anno = _unique_year()
    period = _make_period(db_session, anno)
    _make_document(
        db_session, filename="a.pdf", status=DocumentStatus.PROCESSED.value, sha256=_sha("1"), period=period
    )

    per_anno, senza_anno = check_years(db_session)
    coverage = _find_year(per_anno, anno)
    assert coverage.totale == 1
    assert coverage.caricati == 1
    assert coverage.problemi == []


def test_needs_review_document_is_a_problema_with_anomalie(db_session):
    anno = _unique_year()
    period = _make_period(db_session, anno)
    doc = _make_document(
        db_session, filename="b.pdf", status=DocumentStatus.NEEDS_REVIEW.value, sha256=_sha("2"), period=period
    )
    db_session.add(
        Anomaly(document_id=doc.id, tipo="header_incompleto", severita="error", messaggio="CF mancante")
    )
    db_session.flush()

    per_anno, senza_anno = check_years(db_session)
    coverage = _find_year(per_anno, anno)
    assert coverage.totale == 1
    assert coverage.caricati == 0
    assert len(coverage.problemi) == 1
    problema = coverage.problemi[0]
    assert problema.filename == "b.pdf"
    assert problema.status == DocumentStatus.NEEDS_REVIEW.value
    assert problema.anomalie == ["[error] header_incompleto: CF mancante"]


def test_processed_with_anomalies_and_needs_review_same_year(db_session):
    anno = _unique_year()
    period = _make_period(db_session, anno)
    _make_document(
        db_session, filename="ok.pdf", status=DocumentStatus.PROCESSED.value, sha256=_sha("3"), period=period
    )
    _make_document(
        db_session,
        filename="anomalo.pdf",
        status=DocumentStatus.PROCESSED_WITH_ANOMALIES.value,
        sha256=_sha("4"),
        period=period,
    )

    per_anno, senza_anno = check_years(db_session)
    coverage = _find_year(per_anno, anno)
    assert coverage.totale == 2
    assert coverage.caricati == 1
    assert len(coverage.problemi) == 1
    assert coverage.problemi[0].filename == "anomalo.pdf"


def test_document_without_period_and_not_processed_goes_to_senza_anno(db_session):
    unique_name = f"senza_periodo_{random.randint(0, 10**9)}.pdf"
    doc = _make_document(
        db_session, filename=unique_name, status=DocumentStatus.NEEDS_REVIEW.value, sha256=_sha("5"), period=None
    )
    db_session.add(
        Anomaly(document_id=doc.id, tipo="periodo_non_riconosciuto", severita="warning", messaggio="mese=0")
    )
    db_session.flush()

    per_anno, senza_anno = check_years(db_session)
    matches = [issue for issue in senza_anno if issue.filename == unique_name]
    assert len(matches) == 1
    assert matches[0].anomalie == ["[warning] periodo_non_riconosciuto: mese=0"]


def test_processed_document_without_period_is_silently_ignored(db_session):
    # Comportamento non ovvio del codice: un documento PROCESSED senza periodo
    # non finisce ne' in per_anno ne' in senza_anno (il `continue` scatta prima
    # di costruire un DocumentIssue). Verificato esplicitamente perche' e'
    # facile aspettarsi che compaia in senza_anno.
    unique_name = f"processed_senza_periodo_{random.randint(0, 10**9)}.pdf"
    _make_document(
        db_session, filename=unique_name, status=DocumentStatus.PROCESSED.value, sha256=_sha("6"), period=None
    )

    per_anno, senza_anno = check_years(db_session)
    assert not any(issue.filename == unique_name for issue in senza_anno)
    assert not any(unique_name in (p.filename for p in c.problemi) for c in per_anno)


def test_multiple_years_sorted_ascending(db_session):
    anno_a = _unique_year()
    anno_b = anno_a + 1
    period_b = _make_period(db_session, anno_b)
    period_a = _make_period(db_session, anno_a)
    _make_document(
        db_session, filename="y_b.pdf", status=DocumentStatus.PROCESSED.value, sha256=_sha("7"), period=period_b
    )
    _make_document(
        db_session, filename="y_a.pdf", status=DocumentStatus.PROCESSED.value, sha256=_sha("8"), period=period_a
    )

    per_anno, _senza_anno = check_years(db_session)
    idx_a = next(i for i, c in enumerate(per_anno) if c.anno == anno_a)
    idx_b = next(i for i, c in enumerate(per_anno) if c.anno == anno_b)
    assert idx_a < idx_b


def test_failed_document_is_a_problema(db_session):
    anno = _unique_year()
    period = _make_period(db_session, anno)
    _make_document(
        db_session, filename="failed.pdf", status=DocumentStatus.FAILED.value, sha256=_sha("9"), period=period
    )

    per_anno, _senza_anno = check_years(db_session)
    coverage = _find_year(per_anno, anno)
    assert coverage.problemi[0].status == DocumentStatus.FAILED.value
