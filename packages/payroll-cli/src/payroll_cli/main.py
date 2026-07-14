from __future__ import annotations

import typer
import typer.core

from payroll_cli import context as context_module
from payroll_cli.commands import status as status_cmd
from payroll_cli.commands import version as version_cmd
from payroll_cli.commands.update import update_app

app = typer.Typer(
    help="payroll: CLI operativa per payroll-analizer (setup, aggiornamento, manutenzione, rilascio).",
    no_args_is_help=True,
)
app.add_typer(update_app, name="update")


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
