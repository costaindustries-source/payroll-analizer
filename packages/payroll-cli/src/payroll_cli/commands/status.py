from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import typer

from payroll_cli import git_ops, semver
from payroll_cli.compose import app_image_created_at, db_env, db_is_running, exec_in_db, ps_status
from payroll_cli.context import Context

_ZONE_IDENTIFIER_SUFFIX = ":Zone.Identifier"
# packages/ e' l'unico codice che finisce nell'immagine 'app' (v. Dockerfile):
# altre directory (tests/, docs/, scripts/) non ne fanno parte, quindi un loro
# mtime piu' recente della build non e' un segnale di immagine stale.
_APP_SOURCE_DIRS = ("packages/payroll-ingest/src", "packages/payroll-cli/src")


def run(ctx: Context) -> None:
    repo_root = ctx.repo_root

    _print_machine(ctx)
    _print_containers(repo_root)
    _print_stale_image_warning(repo_root)
    _print_db_and_documents(repo_root)
    _print_input_backlog(repo_root)
    _print_disk_usage(repo_root)
    _print_update_hint(repo_root)


def _print_machine(ctx: Context) -> None:
    if ctx.machine:
        typer.echo(f"Macchina: {ctx.machine.name} (ruolo: {ctx.machine.role})")
    else:
        typer.echo("Macchina: non configurata — esegui 'payroll setup'")


def _print_containers(repo_root: Path) -> None:
    db_status = ps_status(repo_root, "db") or "non in esecuzione"
    typer.echo(f"Container db:  {db_status}")


def _newest_source_mtime(repo_root: Path) -> datetime | None:
    newest: float | None = None
    for rel_dir in _APP_SOURCE_DIRS:
        source_dir = repo_root / rel_dir
        if not source_dir.is_dir():
            continue
        for path in source_dir.rglob("*.py"):
            mtime = path.stat().st_mtime
            if newest is None or mtime > newest:
                newest = mtime
    return datetime.fromtimestamp(newest, tz=timezone.utc) if newest is not None else None


def _print_stale_image_warning(repo_root: Path) -> None:
    image_created = app_image_created_at(repo_root)
    if image_created is None:
        return  # immagine non ancora buildata (o docker non raggiungibile): niente da segnalare
    newest_source = _newest_source_mtime(repo_root)
    if newest_source is not None and newest_source > image_created:
        typer.echo(
            f"Attenzione: codice in packages/ modificato dopo l'ultima build dell'immagine 'app' "
            f"({image_created:%Y-%m-%d %H:%M} UTC) — esegui 'docker compose build app' prima di "
            "'docker compose run --rm app ...', altrimenti userai codice vecchio senza saperlo."
        )


def _print_db_and_documents(repo_root: Path) -> None:
    if not db_is_running(repo_root):
        typer.echo("Documenti: sconosciuto (db non in esecuzione)")
        return

    user = db_env(repo_root, "POSTGRES_USER") or "payroll"
    db_name = db_env(repo_root, "POSTGRES_DB") or "payroll"

    counts = exec_in_db(
        repo_root,
        [
            "psql", "-U", user, "-d", db_name, "-Atc",
            "SELECT status, count(*) FROM payroll_document GROUP BY status ORDER BY status;",
        ],
    )
    if counts.returncode != 0:
        typer.echo(f"Documenti: query fallita ({counts.stderr.strip() or 'schema assente?'})")
        return

    rows = [line for line in counts.stdout.strip().splitlines() if line]
    if not rows:
        typer.echo("Documenti: 0 (database vuoto)")
        return

    typer.echo("Documenti per stato:")
    for row in rows:
        status_name, _, count = row.partition("|")
        typer.echo(f"  {status_name}: {count}")


def _print_input_backlog(repo_root: Path) -> None:
    input_dir = repo_root / "input"
    if not input_dir.is_dir():
        return
    pending = [
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf" and not p.name.endswith(_ZONE_IDENTIFIER_SUFFIX)
    ]
    typer.echo(f"In attesa in input/: {len(pending)} file")


def _print_disk_usage(repo_root: Path) -> None:
    usage = shutil.disk_usage(repo_root)
    free_gb = usage.free / (1024**3)
    total_gb = usage.total / (1024**3)
    typer.echo(f"Spazio disco: {free_gb:.1f} GiB liberi su {total_gb:.1f} GiB")

    backups_dir = repo_root / "backups"
    if backups_dir.is_dir():
        dumps = list(backups_dir.glob("payroll_*.dump"))
        if dumps:
            size_mb = sum(p.stat().st_size for p in dumps) / (1024**2)
            typer.echo(f"Backup in backups/: {len(dumps)} file ({size_mb:.1f} MiB)")


def _print_update_hint(repo_root: Path) -> None:
    current = git_ops.exact_tag_on_head(repo_root) or git_ops.nearest_tag(repo_root)
    local_tags = git_ops.list_local_tags(repo_root)
    newer = semver.tags_after(local_tags, current)
    if newer:
        typer.echo(
            f"Aggiornamenti: {len(newer)} tag locali piu' recenti di {current} "
            f"(es. {newer[-1]}) — esegui 'payroll update check' per un confronto col remoto"
        )
    else:
        typer.echo(f"Aggiornamenti: nessun tag locale piu' recente di {current or '(nessuno)'} "
                    "— esegui 'payroll update check' per un confronto col remoto")
