from __future__ import annotations

from pathlib import Path

import typer

from payroll_cli import db as db_module
from payroll_cli.context import Context

db_app = typer.Typer(help="Backup, restore, migrazioni e shell del database Postgres.", no_args_is_help=True)


@db_app.command("backup")
def backup_command(
    ctx: typer.Context,
    output_dir: Path = typer.Option(None, "--output", help="Directory di destinazione (default: backups/)."),
) -> None:
    """Dump completo (formato custom), verificato, con snapshot dei conteggi righe."""
    app_ctx: Context = ctx.obj
    try:
        result = db_module.backup(app_ctx.repo_root, backups_dir=output_dir, log=typer.echo)
    except db_module.DbError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Backup: {result.dump_path} ({result.table_count} tabelle)")


@db_app.command("restore")
def restore_command(
    ctx: typer.Context,
    dump: Path = typer.Argument(None, help="Dump da ripristinare (default: il piu' recente in backups/)."),
) -> None:
    """Idempotente: no-op se il DB di destinazione ha gia' uno schema."""
    app_ctx: Context = ctx.obj
    try:
        result = db_module.restore(app_ctx.repo_root, dump_path=dump, log=typer.echo)
    except db_module.DbError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if result.performed:
        typer.echo(f"Restore completato da {result.dump_path}.")
        typer.echo(
            "Il volume precedente resta sul disco come backup: rimuovilo a mano "
            "(docker volume rm ...) quando sei sicuro."
        )


@db_app.command("migrate")
def migrate_command(
    ctx: typer.Context,
    revision: str = typer.Argument("head", help="Revisione target (default: head)."),
) -> None:
    """Applica le migration Alembic nel container 'app'."""
    app_ctx: Context = ctx.obj
    try:
        db_module.migrate(app_ctx.repo_root, revision=revision)
    except db_module.DbError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Migration applicate fino a: {revision}")


@db_app.command("shell")
def shell_command(ctx: typer.Context) -> None:
    """Apre una shell psql interattiva nel container 'db'."""
    app_ctx: Context = ctx.obj
    returncode = db_module.shell(app_ctx.repo_root)
    if returncode != 0:
        raise typer.Exit(code=returncode)
