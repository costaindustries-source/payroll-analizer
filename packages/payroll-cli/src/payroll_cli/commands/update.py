from __future__ import annotations

import typer

from payroll_cli import changelog, git_ops, semver
from payroll_cli.context import Context

update_app = typer.Typer(help="Verifica e applica aggiornamenti da GitHub.", no_args_is_help=True)


@update_app.command("check")
def check(ctx: typer.Context) -> None:
    """Confronta il tag locale con l'ultimo tag SemVer pubblicato su GitHub."""
    app_ctx: Context = ctx.obj
    _run_check(app_ctx)


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
