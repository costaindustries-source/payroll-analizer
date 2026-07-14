from __future__ import annotations

import typer

from payroll_cli import changelog, db as db_module, git_ops, semver, updater
from payroll_cli.context import Context

update_app = typer.Typer(help="Verifica e applica aggiornamenti da GitHub.", no_args_is_help=True)


@update_app.command("check")
def check(ctx: typer.Context) -> None:
    """Confronta il tag locale con l'ultimo tag SemVer pubblicato su GitHub."""
    app_ctx: Context = ctx.obj
    _run_check(app_ctx)


@update_app.command("apply")
def apply(
    ctx: typer.Context,
    to: str = typer.Option(None, "--to", help="Tag di destinazione (default: l'ultimo SemVer noto localmente)."),
    resume: bool = typer.Option(
        False, "--resume", hidden=True, help="Uso interno: eseguito dopo il checkout, non invocare direttamente."
    ),
    previous_tag: str = typer.Option(None, "--previous-tag", hidden=True, help="Uso interno."),
) -> None:
    """Aggiorna il checkout all'ultimo tag (o --to), con backup automatico se cambia il volume Postgres."""
    app_ctx: Context = ctx.obj
    repo_root = app_ctx.repo_root

    if resume:
        _run_resume(repo_root, previous_tag)
        return

    typer.echo("== Fetch tag da origin ==")
    fetch_result = git_ops.fetch_tags(repo_root)
    if not fetch_result.ok:
        typer.echo(f"ERRORE: git fetch fallito: {fetch_result.stderr}", err=True)
        raise typer.Exit(code=1)

    try:
        updater.ensure_clean_worktree(repo_root)
        target = updater.resolve_target(repo_root, to)
    except updater.UpdateError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    current = git_ops.exact_tag_on_head(repo_root) or git_ops.nearest_tag(repo_root)
    if current == target:
        typer.echo(f"Gia' aggiornato a {target}.")
        return

    typer.echo(f"Aggiornamento: {current or '(nessun tag)'} -> {target}")
    volume_changed = updater.pg_volume_changed(repo_root, current or "HEAD", target)
    if volume_changed:
        typer.echo(
            "Il volume dati Postgres cambia nome in questa versione: verra' "
            "eseguito un backup automatico prima del checkout."
        )

    if not typer.confirm(f"\nProcedere con l'aggiornamento a {target}?"):
        typer.echo("Interrotto su richiesta.")
        raise typer.Exit(code=0)

    if volume_changed:
        typer.echo("\n== Backup automatico pre-checkout ==")
        try:
            db_module.backup(repo_root, log=typer.echo)
        except db_module.DbError as exc:
            typer.echo(f"ERRORE: backup fallito, aggiornamento interrotto: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    typer.echo(f"\n== Checkout {target} ==")
    try:
        updater.checkout(repo_root, target)
    except updater.UpdateError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("\n== Ripresa con il codice del nuovo checkout ==")
    returncode = updater.reexec_resume(repo_root, previous_tag=current)
    if returncode == 0:
        updater.log_update(repo_root, current, target, "OK")
    raise typer.Exit(code=returncode)


def _run_resume(repo_root, previous_tag: str | None) -> None:
    try:
        updater.resume(repo_root, log=typer.echo)
    except updater.UpdateError as exc:
        typer.echo(f"\nERRORE: {exc}", err=True)
        current_tag = git_ops.exact_tag_on_head(repo_root) or "(sconosciuto)"
        updater.log_update(repo_root, previous_tag, current_tag, f"FALLITO: {exc}")
        if previous_tag and typer.confirm(f"\nRollback automatico a {previous_tag}?"):
            try:
                updater.do_rollback(repo_root, previous_tag, log=typer.echo)
                typer.echo(f"Rollback a {previous_tag} completato.")
            except updater.UpdateError as rollback_exc:
                typer.echo(f"ERRORE: rollback fallito: {rollback_exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("\nAggiornamento completato e verificato.")


def _run_check(app_ctx: Context) -> None:
    repo_root = app_ctx.repo_root

    typer.echo("== Fetch tag da origin ==")
    fetch_result = git_ops.fetch_tags(repo_root)
    if not fetch_result.ok:
        typer.echo(f"ERRORE: git fetch fallito: {fetch_result.stderr}", err=True)
        raise typer.Exit(code=1)

    current = git_ops.exact_tag_on_head(repo_root) or git_ops.nearest_tag(repo_root)
    local_tags = git_ops.list_local_tags(repo_root)
    latest = semver.latest(local_tags)

    if current is None:
        typer.echo("Impossibile determinare il tag corrente (nessun tag raggiungibile da HEAD).", err=True)
        raise typer.Exit(code=1)

    typer.echo(f"Versione corrente: {current}")
    typer.echo(f"Ultima versione pubblicata: {latest or '(nessun tag SemVer trovato)'}")

    pending = semver.tags_after(local_tags, current)
    if not pending:
        typer.echo("Sei aggiornato.")
        return

    typer.echo(f"\n{len(pending)} versione/i disponibile/i: {', '.join(pending)}")
    for tag in pending:
        section = changelog.section_for_tag(repo_root, tag)
        typer.echo(f"\n--- {tag} ---")
        typer.echo(section if section else "(nessuna voce in CHANGELOG.md)")

    typer.echo(f"\nPer aggiornare: payroll update apply --to {pending[-1]}")
