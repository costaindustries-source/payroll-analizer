import uuid
from datetime import datetime, timezone

import typer
from sqlalchemy import delete, select

from payroll_ingest.config import get_settings
from payroll_ingest.db import make_session_factory
from payroll_ingest.db import session_scope as _session_scope
from payroll_ingest.exporter import export_database
from payroll_ingest.logging_setup import configure_logging
from payroll_ingest.models import AuditEvent, PayrollDocument
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


@app.command("delete-document")
def delete_document(
    filename: str = typer.Option(None, "--filename", help="original_filename da cercare (ambiguo se piu' documenti condividono lo stesso nome, v. --id/--sha256)"),
    sha256: str = typer.Option(None, "--sha256", help="sha256 esatto del documento"),
    document_id: str = typer.Option(None, "--id", help="UUID di payroll_document.id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="non chiedere conferma"),
) -> None:
    """Cancella un documento dal database (cascata su pay_line/tax/tfr/leave_balance/
    payroll_totals/anomaly/raw_extraction) cosi' da poterlo ricaricare con `process`:
    un documento gia' in stato PROCESSED/PROCESSED_WITH_ANOMALIES viene altrimenti
    riconosciuto come duplicato (stesso sha256) e scartato senza essere rielaborato.
    Non tocca il file PDF su disco: va ricopiato manualmente in input/ dopo la cancellazione."""
    filters = [f for f in (filename, sha256, document_id) if f]
    if len(filters) != 1:
        typer.echo("Specifica esattamente uno tra --filename, --sha256, --id.", err=True)
        raise typer.Exit(code=1)

    settings = get_settings()
    session_factory = make_session_factory(settings)

    with _session_scope(session_factory) as session:
        if document_id:
            stmt = select(PayrollDocument).where(PayrollDocument.id == uuid.UUID(document_id))
        elif sha256:
            stmt = select(PayrollDocument).where(PayrollDocument.sha256 == sha256)
        else:
            stmt = select(PayrollDocument).where(PayrollDocument.original_filename == filename)
        matches = list(session.scalars(stmt).all())

        if not matches:
            typer.echo("Nessun documento trovato.", err=True)
            raise typer.Exit(code=1)
        if len(matches) > 1:
            typer.echo(f"{len(matches)} documenti corrispondono, disambigua con --id o --sha256:")
            for doc in matches:
                typer.echo(
                    f"  id={doc.id} sha256={doc.sha256} status={doc.status} "
                    f"filename={doc.original_filename} created_at={doc.created_at}"
                )
            raise typer.Exit(code=1)

        doc = matches[0]
        typer.echo(
            f"id={doc.id} filename={doc.original_filename} status={doc.status} "
            f"sha256={doc.sha256} created_at={doc.created_at}"
        )
        if not yes and not typer.confirm("Cancellare questo documento (e tutti i dati collegati) dal database?"):
            typer.echo("Annullato.")
            raise typer.Exit(code=0)

        session.execute(delete(AuditEvent).where(AuditEvent.document_id == doc.id))
        session.delete(doc)

    typer.echo("Documento cancellato. Ricopia il PDF in input/ e rilancia `payroll-ingest process` per ricaricarlo.")


if __name__ == "__main__":
    app()
