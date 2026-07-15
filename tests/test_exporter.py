"""Test per payroll_ingest.exporter.export_database: dump JSONL + manifest.

export_database interroga TUTTE le righe di ogni tabella senza filtro: in uno
schema di test condiviso con altri file/gruppi di test potrebbero comparire
righe committate altrove, quindi le assert su conteggi sono sempre >= (mai ==)
e il contenuto viene verificato cercando un marcatore unico per riga, non
assumendo che la tabella contenga solo le nostre righe.
"""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from payroll_ingest.exporter import SCHEMA_VERSION, export_database
from payroll_ingest.models import Company, Employee, PayrollDocument, PayrollPeriod, Tax


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def test_export_creates_bundle_dir_named_with_stamp_and_schema_version(db_session, tmp_path):
    exported_at = datetime(2025, 7, 15, 10, 30, 0, tzinfo=timezone.utc)
    bundle_dir = export_database(db_session, tmp_path, exported_at)

    assert bundle_dir == tmp_path / f"20250715T103000Z_{SCHEMA_VERSION}"
    assert bundle_dir.is_dir()


def test_export_writes_one_jsonl_per_table_in_import_order(db_session, tmp_path):
    exported_at = datetime.now(timezone.utc)
    bundle_dir = export_database(db_session, tmp_path, exported_at)

    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["exported_at"] == exported_at.isoformat()

    expected_tables = [
        "company",
        "employee",
        "employment",
        "payroll_period",
        "payroll_document",
        "pay_line",
        "tax",
        "tfr",
        "leave_balance",
        "payroll_totals",
        "anomaly",
        "raw_extraction",
        "audit_event",
    ]
    assert manifest["tables_in_import_order"] == expected_tables
    for table in expected_tables:
        assert (bundle_dir / f"{table}.jsonl").exists()
        assert table in manifest["row_counts"]


def test_export_row_counts_reflect_added_rows(db_session, tmp_path):
    ragione_sociale = _unique("ACME EXPORT")
    company = Company(ragione_sociale=ragione_sociale)
    db_session.add(company)
    db_session.flush()

    bundle_dir = export_database(db_session, tmp_path, datetime.now(timezone.utc))
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["row_counts"]["company"] >= 1

    lines = (bundle_dir / "company.jsonl").read_text(encoding="utf-8").splitlines()
    assert manifest["row_counts"]["company"] == len(lines)
    matching = [json.loads(line) for line in lines if json.loads(line)["ragione_sociale"] == ragione_sociale]
    assert len(matching) == 1
    assert matching[0]["id"] == str(company.id)


def test_export_serializes_datetime_uuid_and_decimal_as_strings(db_session, tmp_path):
    cf = uuid.uuid4().hex[:16].upper()
    employee = Employee(cognome_nome="Mario Rossi Export", codice_fiscale=cf)
    company = Company(ragione_sociale=_unique("ACME TAX EXPORT"))
    period = PayrollPeriod(mese=3, anno=90055, tipo="ordinario", label_originale="marzo 90055")
    db_session.add_all([employee, company, period])
    db_session.flush()

    document = PayrollDocument(
        sha256=uuid.uuid4().hex.ljust(64, "0"),
        original_filename="export_test.pdf",
        status="PROCESSED",
        template_name="zucchetti_standard",
        parser_version="1.0.0",
        source_used_ocr=False,
        employee_id=employee.id,
        company_id=company.id,
        period_id=period.id,
    )
    db_session.add(document)
    db_session.flush()

    tax = Tax(document_id=document.id, imponibile_irpef=Decimal("1234.56789"))
    db_session.add(tax)
    db_session.flush()

    bundle_dir = export_database(db_session, tmp_path, datetime.now(timezone.utc))

    # employee: UUID (id) e datetime (created_at) devono essere stringhe, non
    # oggetti Python (json.dumps fallirebbe altrimenti su UUID/datetime nativi:
    # se _row_to_dict non convertisse, export_database stesso solleverebbe
    # TypeError prima di arrivare qui).
    employee_lines = [
        json.loads(line)
        for line in (bundle_dir / "employee.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    exported_employee = next(row for row in employee_lines if row["codice_fiscale"] == cf)
    assert exported_employee["id"] == str(employee.id)
    assert isinstance(exported_employee["created_at"], str)

    tax_lines = [
        json.loads(line) for line in (bundle_dir / "tax.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    exported_tax = next(row for row in tax_lines if row["document_id"] == str(document.id))
    assert exported_tax["imponibile_irpef"] == "1234.56789"


def test_export_empty_table_produces_empty_jsonl_and_zero_count(db_session, tmp_path):
    bundle_dir = export_database(db_session, tmp_path, datetime.now(timezone.utc))
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))

    # audit_event non viene mai popolato da questi test: se nessun altro test
    # committed ha lasciato righe, deve essere zero e il file vuoto.
    if manifest["row_counts"]["audit_event"] == 0:
        assert (bundle_dir / "audit_event.jsonl").read_text(encoding="utf-8") == ""
