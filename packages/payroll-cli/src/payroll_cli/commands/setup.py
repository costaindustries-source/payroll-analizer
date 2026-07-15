from __future__ import annotations

from pathlib import Path

import typer

from payroll_cli import deploy_key as deploy_key_module
from payroll_cli import doctor as doctor_module
from payroll_cli import git_ops
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


def _run_pull(repo_root: Path) -> None:
    typer.echo("== Aggiornamento codice (git pull) ==")
    if git_ops.is_dirty(repo_root):
        typer.echo(
            "Working tree non pulito: ci sono modifiche locali non salvate. "
            "Pull saltato per non rischiare di perderle (fai prima commit/stash, poi riprova con --pull)."
        )
        return
    tag = git_ops.exact_tag_on_head(repo_root)
    if tag:
        typer.echo(
            f"Questa macchina e' su un tag di release ({tag}), non su un branch: "
            "usa 'payroll update apply' per aggiornare a un tag piu' recente. Pull saltato."
        )
        return
    result = git_ops.pull_ff_only(repo_root)
    if result.ok:
        typer.echo(result.stdout or "Gia' aggiornato.")
    else:
        typer.echo(
            f"Pull non riuscito, proseguo comunque con il codice attuale: {result.stderr or result.stdout}"
        )


def run(
    app_ctx: Context,
    check_only: bool,
    name: str | None,
    role: str | None,
    db_port: int | None,
    logs_retention_days: int | None,
    backups_keep: int | None,
    do_bootstrap: bool,
    gen_deploy_key: bool,
    do_pull: bool = False,
) -> None:
    if do_pull:
        _run_pull(app_ctx.repo_root)
        typer.echo("")

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
    setup_wizard.ensure_env_password(app_ctx.repo_root, log=typer.echo)

    if gen_deploy_key:
        _run_deploy_key(app_ctx, role)

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


def _run_deploy_key(app_ctx: Context, role: str) -> None:
    typer.echo("\n== Deploy key SSH (read-only) ==")
    if role == "source":
        typer.echo(
            "Ruolo 'source' ha gia' accesso in scrittura (push) tramite le credenziali "
            "esistenti: una deploy key read-only non serve qui. Generazione saltata."
        )
        return

    try:
        status = deploy_key_module.ensure_deploy_key()
    except deploy_key_module.DeployKeyError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if status.generated:
        typer.echo(f"Generata nuova deploy key: {status.private_key}")
    else:
        typer.echo(f"Deploy key gia' presente: {status.private_key}")

    typer.echo(
        "\nChiave pubblica da autorizzare su GitHub (Settings del repo -> Deploy keys -> "
        "Add deploy key, SENZA spuntare 'Allow write access' — read-only):\n"
    )
    typer.echo(status.public_key_content)

    try:
        current_url = deploy_key_module.get_remote_url(app_ctx.repo_root)
    except deploy_key_module.DeployKeyError as exc:
        typer.echo(f"\nERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    ssh_url = deploy_key_module.https_to_ssh_url(current_url)
    if ssh_url:
        if typer.confirm(f"\nIl remote 'origin' e' HTTPS ({current_url}). Passare a SSH ({ssh_url})?"):
            deploy_key_module.set_remote_url(app_ctx.repo_root, "origin", ssh_url)
            typer.echo("Remote aggiornato a SSH.")
        else:
            typer.echo("Remote lasciato HTTPS: la deploy key SSH non verra' usata finche' non lo cambi a mano.")

    try:
        deploy_key_module.configure_ssh_command(app_ctx.repo_root, status.private_key)
    except deploy_key_module.DeployKeyError as exc:
        typer.echo(f"ERRORE: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"\ncore.sshCommand impostato su QUESTO repo per usare {status.private_key} (non tocca ~/.ssh/config).")
    typer.echo("Dopo aver autorizzato la chiave su GitHub, verifica con: git fetch --tags")
