#!/usr/bin/env python3
"""Gate di accettazione end-to-end per i template Copernico/SAP HR (issue GH #27).

A differenza di `verify_new_templates.py` - che chiama `extract_document` +
`find_template` + `spec.map` direttamente, bypassando l'orchestrator - questo
script esegue il path REALE di `payroll-ingest process`
(`classify_pdf` -> `extract_document` -> `find_template` -> `validate` ->
`save_document` -> spostamento file) tramite `run_batch`, su:

- una copia scratch dei campioni (i file originali di `--samples-dir` non
  vengono mai letti in-place da `run_batch`, che li sposterebbe fuori da
  `input/`: restano intatti);
- uno schema Postgres isolato e usa-e-getta, mai lo schema 'public' dove
  vivono i dati reali di sviluppo (stesso pattern di `tests/conftest.py`).

Nato dall'investigazione di GH #25: il gate esistente dichiarava "57/57 OK"
mentre il batch reale falliva su 12/57 file (causa: side-effect di import di
una dipendenza OCR, non collegato al bypass in se', ma il bypass e' cio' che
ha impedito al gate di accorgersene). Va rilanciato dopo ogni modifica a
extraction.py/templates/*.py/orchestrator.py, in aggiunta a
`verify_new_templates.py` (piu' rapido: nessun DB/OCR coinvolto).

Uso:
    docker compose up -d db   # o: uv run payroll setup (una tantum)
    uv run python scripts/verify_new_templates_real_batch.py [--samples-dir docs/new-templates]

Richiede un Postgres raggiungibile (default: stessa TEST_DATABASE_URL/URL di
tests/conftest.py). Exit code 1 se almeno un documento non risulta PROCESSED
o PROCESSED_WITH_ANOMALIES.
"""

import argparse
import os
import shutil
import sys
import tempfile
import uuid as uuid_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "payroll-ingest" / "src"))

from sqlalchemy import create_engine, event, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from payroll_ingest.config import Settings  # noqa: E402
from payroll_ingest.dto import DocumentStatus  # noqa: E402
from payroll_ingest.models import Base  # noqa: E402
from payroll_ingest.orchestrator import run_batch  # noqa: E402

_DEFAULT_DATABASE_URL = "postgresql+psycopg://payroll:payroll@localhost:5432/payroll"
_OK_STATUSES = {DocumentStatus.PROCESSED.value, DocumentStatus.PROCESSED_WITH_ANOMALIES.value}


def _database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", _DEFAULT_DATABASE_URL)


def _copy_samples_flat(samples_dir: Path, dest_input_dir: Path) -> int:
    # run_batch fa input_dir.glob("*.pdf"), NON recursive: i campioni sono in
    # sottocartelle per anno, vanno appiattiti in un'unica input/ per essere trovati.
    dest_input_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for pdf in sorted(samples_dir.glob("**/*.pdf")):
        shutil.copy2(pdf, dest_input_dir / pdf.name)
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=REPO_ROOT / "docs" / "new-templates",
        help="Cartella con i cedolini di riferimento (default: docs/new-templates)",
    )
    args = parser.parse_args()

    if not args.samples_dir.is_dir():
        print(f"ERRORE: cartella campioni non trovata: {args.samples_dir}")
        print("I cedolini di riferimento non sono versionati in git (v. .gitignore):")
        print("vanno presenti localmente per poter fare il batch di verifica.")
        return 1

    database_url = _database_url()
    schema = f"verify_real_batch_{uuid_module.uuid4().hex[:12]}"
    admin_engine = create_engine(database_url, future=True)
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.commit()
    except Exception as exc:
        print(f"ERRORE: Postgres non raggiungibile ({database_url}): {exc}")
        return 1
    finally:
        admin_engine.dispose()

    engine = create_engine(database_url, future=True)

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}"')
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    exit_code = 0
    with tempfile.TemporaryDirectory(prefix="verify_new_templates_real_batch_") as scratch:
        scratch_dir = Path(scratch)
        n_copied = _copy_samples_flat(args.samples_dir, scratch_dir / "input")
        if n_copied == 0:
            print(f"ERRORE: nessun PDF trovato in {args.samples_dir}")
            exit_code = 1
        else:
            settings = Settings(PAYROLL_BASE_DIR=scratch_dir, DATABASE_URL=database_url)
            summary = run_batch(settings, session_factory, run_id="verify_real_batch")

            with session_factory() as session:
                rows = session.execute(
                    text(
                        "SELECT original_filename, status, template_name FROM payroll_document "
                        "ORDER BY original_filename"
                    )
                ).all()

            problems = [(name, status, template) for name, status, template in rows if status not in _OK_STATUSES]

            for name, status, template in rows:
                marker = "OK  " if status in _OK_STATUSES else "FAIL"
                print(f"{marker} {name:20s} status={status:24s} template={template}")

            print()
            print(f"Riepilogo batch reale: {summary.as_dict()}")
            if problems or summary.failed:
                print(f"{len(problems) + summary.failed}/{summary.total} file non OK nel path reale.")
                exit_code = 1
            else:
                print(f"Tutti i {summary.total} file OK nel path reale (process_document/run_batch).")

    engine.dispose()
    cleanup_engine = create_engine(database_url, future=True)
    with cleanup_engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        conn.commit()
    cleanup_engine.dispose()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
