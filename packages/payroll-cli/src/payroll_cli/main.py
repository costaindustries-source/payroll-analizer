from __future__ import annotations

import typer
import typer.core

from payroll_cli import context as context_module
from payroll_cli import git_ops, updater
from payroll_cli.commands import cleanup as cleanup_cmd
from payroll_cli.commands import setup as setup_cmd
from payroll_cli.commands import status as status_cmd
from payroll_cli.commands import version as version_cmd
from payroll_cli.commands.db import db_app
from payroll_cli.commands.release import release_app
from payroll_cli.commands.update import update_app

app = typer.Typer(
    help="payroll: CLI operativa per payroll-analizer (setup, aggiornamento, manutenzione, rilascio).",
    no_args_is_help=True,
)
app.add_typer(update_app, name="update")
app.add_typer(db_app, name="db")
app.add_typer(release_app, name="release")


@app.callback()
def main(ctx: typer.Context) -> None:
    try:
        repo_root = context_module.find_repo_root()
    except context_module.RepoNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    machine = context_module.load_machine_config(repo_root)
    ctx.obj = context_module.Context(repo_root=repo_root, machine=machine)


@app.command()
def version(ctx: typer.Context) -> None:
    """Versione CLI, tag/commit del repo, stato migrazioni, versione Postgres."""
    version_cmd.run(ctx.obj)


@app.command()
def status(ctx: typer.Context) -> None:
    """Salute della macchina: container, DB, migrazioni, documenti, disco, config."""
    status_cmd.run(ctx.obj)


@app.command()
def cleanup(
    ctx: typer.Context,
    apply: bool = typer.Option(False, "--apply", help="Rimuove gli item elencati (default: solo report)."),
) -> None:
    """Report (default) o rimozione di work/logs/backups oltre le soglie configurate."""
    cleanup_cmd.run(ctx.obj, apply_changes=apply)


@app.command()
def setup(
    ctx: typer.Context,
    check: bool = typer.Option(False, "--check", help="Solo verifica prerequisiti, nessuna modifica."),
    name: str = typer.Option(None, "--name", help="Nome macchina."),
    role: str = typer.Option(None, "--role", help="Ruolo: 'source' (solo Ubuntu/dev) o 'node'."),
    db_port: int = typer.Option(None, "--db-port", help="Porta host pubblicata per Postgres."),
    logs_retention_days: int = typer.Option(None, "--logs-retention-days"),
    backups_keep: int = typer.Option(None, "--backups-keep"),
    bootstrap: bool = typer.Option(
        False, "--bootstrap", help="Dopo la configurazione: build immagine + avvio DB + migration (+ smoke test)."
    ),
) -> None:
    """Prima installazione: verifica prerequisiti, scrive la config per-macchina, opzionalmente fa il bootstrap."""
    setup_cmd.run(
        ctx.obj,
        check_only=check,
        name=name,
        role=role,
        db_port=db_port,
        logs_retention_days=logs_retention_days,
        backups_keep=backups_keep,
        do_bootstrap=bootstrap,
    )


@app.command()
def rollback(
    ctx: typer.Context,
    tag: str = typer.Argument(..., help="Tag a cui tornare (deve esistere localmente)."),
) -> None:
    """Torna a un tag precedente: checkout + rebuild immagine. Non tocca dati/volumi."""
    app_ctx = ctx.obj
    repo_root = app_ctx.repo_root
    local_tags = git_ops.list_local_tags(repo_root)
    if tag not in local_tags:
        typer.echo(f"ERRORE: tag '{tag}' non trovato localmente (esegui prima 'payroll update check').", err=True)
        raise typer.Exit(code=1)
    if not typer.confirm(f"Riportare il checkout a {tag} e ricostruire l'immagine Docker?"):
        typer.echo("Interrotto su richiesta.")
        raise typer.Exit(code=0)
    try:
        updater.do_rollback(repo_root, tag, log=typer.echo)
    except updater.UpdateError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"\nRollback a {tag} completato. Verifica manualmente (es. 'payroll status') se necessario.")


@app.command("help")
def help_command(
    ctx: typer.Context,
    command: list[str] = typer.Argument(None, help="Comando (e sottocomando) di cui mostrare l'help."),
) -> None:
    """Mostra l'help di 'payroll' o di un comando/sottocomando specifico."""
    root_ctx = ctx.find_root()
    target = root_ctx.command
    current_ctx = root_ctx
    for name in command or []:
        if not isinstance(target, typer.core.TyperGroup):
            typer.echo(f"'{name}' non e' un gruppo di comandi.", err=True)
            raise typer.Exit(code=1)
        resolved = target.get_command(current_ctx, name)
        if resolved is None:
            typer.echo(f"Comando sconosciuto: {' '.join(command)}", err=True)
            raise typer.Exit(code=1)
        current_ctx = resolved.make_context(name, [], parent=current_ctx, resilient_parsing=True)
        target = resolved
    typer.echo(target.get_help(current_ctx))


if __name__ == "__main__":
    app()
