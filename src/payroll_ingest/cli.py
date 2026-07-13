import uuid
from datetime import datetime, timezone

import typer

from payroll_ingest.config import get_settings
from payroll_ingest.db import make_session_factory
from payroll_ingest.db import session_scope as _session_scope
from payroll_ingest.exporter import export_database
from payroll_ingest.logging_setup import configure_logging
from payroll_ingest.orchestrator import run_batch

app = typer.Typer(help="Batch di ingestion cedolini PDF -> database PostgreSQL.")


@app.command()
def process() -> None:
    """Elabora tutti i PDF presenti in input/, uno alla volta e in isolamento."""
    settings = get_settings()
    settings.ensure_folders()
    run_id = str(uuid.uuid4())
    configure_logging(settings.logs_dir, run_id)

    session_factory = make_session_factory(settings)
    summary = run_batch(settings, session_factory, run_id)

    typer.echo(
        f"Run {run_id}: {summary.total} file, {summary.processed} ok, "
        f"{summary.processed_with_anomalies} con anomalie, {summary.needs_review} da rivedere, "
        f"{summary.failed} in errore, {summary.skipped} duplicati saltati."
    )
    if summary.failed:
        raise typer.Exit(code=1)


@app.command()
def export() -> None:
    """Genera un export completo, versionato e reimportabile della base dati."""
    settings = get_settings()
    settings.ensure_folders()
    session_factory = make_session_factory(settings)

    with _session_scope(session_factory) as session:
        bundle_dir = export_database(session, settings.export_dir, datetime.now(timezone.utc))

    typer.echo(f"Export creato in {bundle_dir}")


if __name__ == "__main__":
    app()
