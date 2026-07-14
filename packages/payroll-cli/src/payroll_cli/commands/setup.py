from __future__ import annotations

import typer

from payroll_cli import doctor as doctor_module
from payroll_cli import setup_wizard
from payroll_cli.context import Context, MachineConfig


def _print_checks(checks: list[doctor_module.CheckResult]) -> bool:
    all_blocking_ok = True
    for check in checks:
        marker = "OK " if check.ok else "!! "
        typer.echo(f"{marker}{check.name}: {check.detail}")
        if not check.ok and check.blocking:
            all_blocking_ok = False
    return all_blocking_ok


def run(
    app_ctx: Context,
    check_only: bool,
    name: str | None,
    role: str | None,
    db_port: int | None,
    logs_retention_days: int | None,
    backups_keep: int | None,
    do_bootstrap: bool,
) -> None:
    typer.echo("== Verifica prerequisiti ==")
    checks = doctor_module.run_checks(app_ctx.repo_root)
    all_ok = _print_checks(checks)

    if check_only:
        if not all_ok:
            raise typer.Exit(code=1)
        return

    if not all_ok:
        typer.echo("\nUno o piu' prerequisiti obbligatori non sono soddisfatti: risolvili prima di continuare.", err=True)
        raise typer.Exit(code=1)

    existing = app_ctx.machine
    if existing and not typer.confirm(
        f"\nConfigurazione gia' presente ({existing.name}, ruolo {existing.role}). Sovrascrivere?"
    ):
        typer.echo("Configurazione invariata.")
        return

    name = name or typer.prompt("Nome macchina", default=existing.name if existing else setup_wizard.default_machine_name())
    role = role or typer.prompt("Ruolo (source/node)", default=existing.role if existing else "node")
    if role not in ("source", "node"):
        typer.echo(f"Ruolo non valido: '{role}' (atteso 'source' o 'node').", err=True)
        raise typer.Exit(code=1)
    if db_port is None:
        db_port = typer.prompt("Porta host del DB", default=existing.db_host_port if existing else 5432, type=int)
    if logs_retention_days is None:
        logs_retention_days = typer.prompt(
            "Retention log (giorni)", default=existing.logs_retention_days if existing else 90, type=int
        )
    if backups_keep is None:
        backups_keep = typer.prompt("Backup da conservare", default=existing.backups_keep if existing else 5, type=int)

    config = MachineConfig(
        name=name,
        role=role,
        db_host_port=db_port,
        auto_backup=existing.auto_backup if existing else True,
        logs_retention_days=logs_retention_days,
        backups_keep=backups_keep,
    )
    config_path = setup_wizard.write_config(app_ctx.repo_root, config)
    typer.echo(f"\nConfigurazione scritta in {config_path}")
    setup_wizard.maybe_write_override(app_ctx.repo_root, db_port, log=typer.echo)

    if not do_bootstrap:
        typer.echo("\nBootstrap non richiesto (--bootstrap per eseguirlo): build/avvio/migration saltati.")
        return

    if not typer.confirm("\nEseguire ora build immagine + avvio DB + migration (+ smoke test se disponibile)?"):
        typer.echo("Bootstrap saltato.")
        return

    try:
        setup_wizard.bootstrap(app_ctx.repo_root, log=typer.echo)
    except setup_wizard.BootstrapError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("\nSetup completato.")
