from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as pkg_version

import typer

from payroll_cli import git_ops
from payroll_cli.compose import db_env, db_is_running, run_in_app
from payroll_cli.context import Context


def _cli_version() -> str:
    try:
        return pkg_version("payroll-cli")
    except PackageNotFoundError:
        return "dev"


def run(ctx: Context) -> None:
    repo_root = ctx.repo_root

    typer.echo(f"payroll-cli: {_cli_version()}")

    tag = git_ops.exact_tag_on_head(repo_root)
    branch = git_ops.current_branch(repo_root)
    commit = git_ops.current_commit(repo_root)
    dirty = " (modifiche non committate)" if git_ops.is_dirty(repo_root) else ""
    if tag:
        typer.echo(f"repo: {tag} ({branch}@{commit}){dirty}")
    else:
        nearest = git_ops.nearest_tag(repo_root)
        base = f"da {nearest} " if nearest else ""
        typer.echo(f"repo: {branch}@{commit} {base}(HEAD non e' su un tag){dirty}")

    if ctx.machine:
        typer.echo(f"macchina: {ctx.machine.name} (ruolo: {ctx.machine.role})")
    else:
        typer.echo("macchina: non configurata (esegui 'payroll setup')")

    if not db_is_running(repo_root):
        typer.echo("postgres: container 'db' non in esecuzione")
        typer.echo("alembic: sconosciuto (db non raggiungibile)")
        return

    pg_version_str = _query_pg_version(repo_root)
    typer.echo(f"postgres: {pg_version_str or 'sconosciuta'}")

    current = run_in_app(repo_root, ["alembic", "current"])
    heads = run_in_app(repo_root, ["alembic", "heads"])
    current_rev = current.stdout.strip() or "(nessuna revisione applicata)"
    heads_rev = heads.stdout.strip() or "(sconosciuto)"
    typer.echo(f"alembic current: {current_rev}")
    typer.echo(f"alembic head:    {heads_rev}")


def _query_pg_version(repo_root) -> str | None:
    from payroll_cli.compose import exec_in_db

    user = db_env(repo_root, "POSTGRES_USER") or "payroll"
    db_name = db_env(repo_root, "POSTGRES_DB") or "payroll"
    result = exec_in_db(repo_root, ["psql", "-U", user, "-d", db_name, "-Atc", "SHOW server_version;"])
    return result.stdout.strip() if result.returncode == 0 else None
