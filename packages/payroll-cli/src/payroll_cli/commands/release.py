from __future__ import annotations

import typer

from payroll_cli import releaser
from payroll_cli.context import Context

release_app = typer.Typer(
    help="Pubblica un nuovo tag SemVer su GitHub (solo role=source). Nessun deploy.",
    no_args_is_help=True,
)


@release_app.command("new")
def new(
    ctx: typer.Context,
    version: str = typer.Argument(..., help="Versione da rilasciare (es. v0.4.0)."),
    message: str = typer.Option(None, "-m", "--message", help="Messaggio di release (annotazione del tag)."),
) -> None:
    """Preflight (main, tree pulito, tag libero) -> smoke test -> CHANGELOG -> tag annotato -> push. Nessun deploy."""
    app_ctx: Context = ctx.obj
    repo_root = app_ctx.repo_root

    try:
        releaser.check_role(app_ctx.machine)
        releaser.preflight(repo_root, version)
    except releaser.ReleaseError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        releaser.run_smoke_test(repo_root, log=typer.echo)
    except releaser.ReleaseError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    message = message or typer.prompt(f"Messaggio di release per {version}")

    typer.echo("\n== CHANGELOG.md ==")
    try:
        promoted = releaser.promote_changelog(repo_root, version)
    except releaser.ReleaseError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if promoted:
        releaser.commit_changelog(repo_root, version)
        typer.echo(f"Sezione '[Non rilasciato]' promossa a '[{version}]', committata.")
    else:
        typer.echo("Nessun contenuto in '[Non rilasciato]': CHANGELOG.md non modificato.")

    if not typer.confirm(f"\nCreare il tag {version} e pubblicarlo su GitHub (git push)?"):
        typer.echo("Interrotto su richiesta. L'eventuale commit del CHANGELOG resta locale.")
        raise typer.Exit(code=0)

    typer.echo(f"\n== Tag {version} + push ==")
    try:
        releaser.create_tag(repo_root, version, message)
        releaser.push(repo_root, version)
    except releaser.ReleaseError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"\nRilasciato {version} su GitHub. Ogni macchina si aggiorna con 'payroll update apply'.")


@release_app.command("list")
def list_command(ctx: typer.Context) -> None:
    """Storia dei tag pubblicati (fetch + confronto con origin)."""
    app_ctx: Context = ctx.obj
    infos = releaser.list_releases(app_ctx.repo_root)
    if not infos:
        typer.echo("Nessun tag SemVer trovato.")
        return
    for info in infos:
        marker = "" if info.pushed else "  (solo locale, non pushato)"
        typer.echo(f"{info.tag}\t{info.date}\t{info.subject}{marker}")
