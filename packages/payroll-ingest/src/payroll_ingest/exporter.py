"""Export completo, versionato e reimportabile della base dati.

Formato: una cartella per export con un file JSONL per tabella (ordine di
scrittura = ordine di reimport rispetto alle foreign key) piu' un manifest
con conteggi e versione schema.
"""

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from payroll_ingest.models import (
    Anomaly,
    AuditEvent,
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

SCHEMA_VERSION = "1.0.0"

# Ordine di export = ordine di reimport valido rispetto alle foreign key.
_EXPORT_TABLES = [
    Company,
    Employee,
    Employment,
    PayrollPeriod,
    PayrollDocument,
    PayLine,
    Tax,
    Tfr,
    LeaveBalance,
    PayrollTotals,
    Anomaly,
    RawExtraction,
    AuditEvent,
]


def _row_to_dict(obj) -> dict:
    result = {}
    for column in inspect(obj.__class__).columns:
        value = getattr(obj, column.name)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif value.__class__.__name__ == "Decimal":
            value = str(value)
        elif value.__class__.__name__ == "UUID":
            value = str(value)
        result[column.name] = value
    return result


def export_database(session: Session, export_dir: Path, exported_at: datetime) -> Path:
    stamp = exported_at.strftime("%Y%m%dT%H%M%SZ")
    bundle_dir = export_dir / f"{stamp}_{SCHEMA_VERSION}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    for model in _EXPORT_TABLES:
        table_name = model.__tablename__
        out_path = bundle_dir / f"{table_name}.jsonl"
        n = 0
        with out_path.open("w", encoding="utf-8") as f:
            for row in session.query(model).yield_per(500):
                f.write(json.dumps(_row_to_dict(row), ensure_ascii=False))
                f.write("\n")
                n += 1
        counts[table_name] = n

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": exported_at.isoformat(),
        "tables_in_import_order": [m.__tablename__ for m in _EXPORT_TABLES],
        "row_counts": counts,
    }
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return bundle_dir
