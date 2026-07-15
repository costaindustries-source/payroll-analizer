"""Test di payroll_cli.commands.setup.run() (delegato dal comando 'payroll
setup'): --pull, verifica prerequisiti, scrittura config, deploy key,
bootstrap. E' la logica piu' ramificata dello strato CLI: doctor/git_ops/
setup_wizard/deploy_key sono tutti mockati (nessun docker/git/ssh-keygen
reale), typer.confirm/typer.prompt sono mockati per pilotare ogni branch senza
dipendere da CliRunner+input testuale."""

from __future__ import annotations

import typer

from payroll_cli import deploy_key as deploy_key_module
from payroll_cli import doctor as doctor_module
from payroll_cli import git_ops
from payroll_cli import setup_wizard
from payroll_cli.commands import setup as setup_cmd
from payroll_cli.context import Context, MachineConfig


def _ctx(tmp_path, machine=None):
    return Context(repo_root=tmp_path, machine=machine)


def _ok_check(name="docker", ok=True, detail="OK", blocking=True):
    return doctor_module.CheckResult(name=name, ok=ok, detail=detail, blocking=blocking)


def _run(ctx, **overrides):
    kwargs = dict(
        check_only=False,
        name=None,
        role=None,
        db_port=None,
        logs_retention_days=None,
        backups_keep=None,
        do_bootstrap=False,
        gen_deploy_key=False,
        do_pull=False,
    )
    kwargs.update(overrides)
    return setup_cmd.run(ctx, **kwargs)


def _exit_code(fn):
    try:
        fn()
        return 0
    except typer.Exit as exc:
        return exc.exit_code


def _all_output(capsys) -> str:
    """stdout+stderr uniti: alcuni messaggi (errori, guardie) sono scritti con err=True."""
    captured = capsys.readouterr()
    return captured.out + captured.err


# --- --pull ---


def test_pull_skipped_on_dirty_worktree(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(git_ops, "is_dirty", lambda repo_root: True)
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _run(_ctx(tmp_path), do_pull=True, check_only=True)
    out = capsys.readouterr().out
    assert "Pull saltato per non rischiare di perderle" in out


def test_pull_skipped_when_on_release_tag(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(git_ops, "is_dirty", lambda repo_root: False)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: "v1.0.0")
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _run(_ctx(tmp_path), do_pull=True, check_only=True)
    out = capsys.readouterr().out
    assert "usa 'payroll update apply'" in out


def test_pull_success_prints_stdout(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(git_ops, "is_dirty", lambda repo_root: False)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: None)
    monkeypatch.setattr(git_ops, "pull_ff_only", lambda repo_root: git_ops.GitResult(0, "Fast-forward...", ""))
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _run(_ctx(tmp_path), do_pull=True, check_only=True)
    out = capsys.readouterr().out
    assert "Fast-forward..." in out


def test_pull_success_empty_stdout_uses_fallback(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(git_ops, "is_dirty", lambda repo_root: False)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: None)
    monkeypatch.setattr(git_ops, "pull_ff_only", lambda repo_root: git_ops.GitResult(0, "", ""))
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _run(_ctx(tmp_path), do_pull=True, check_only=True)
    out = capsys.readouterr().out
    assert "Gia' aggiornato." in out


def test_pull_failure_reports_and_continues(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(git_ops, "is_dirty", lambda repo_root: False)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: None)
    monkeypatch.setattr(git_ops, "pull_ff_only", lambda repo_root: git_ops.GitResult(1, "", "conflitto"))
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _run(_ctx(tmp_path), do_pull=True, check_only=True)
    out = capsys.readouterr().out
    assert "Pull non riuscito, proseguo comunque con il codice attuale: conflitto" in out


# --- verifica prerequisiti ---


def test_check_only_all_ok_returns_without_writing_config(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    write_called = {"called": False}
    monkeypatch.setattr(setup_wizard, "write_config", lambda *a, **kw: write_called.__setitem__("called", True))
    code = _exit_code(lambda: _run(_ctx(tmp_path), check_only=True))
    assert code == 0
    assert write_called["called"] is False
    out = capsys.readouterr().out
    assert "OK docker: OK" in out


def test_check_only_blocking_failure_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        doctor_module, "run_checks", lambda repo_root: [_ok_check(ok=False, detail="non trovato", blocking=True)]
    )
    code = _exit_code(lambda: _run(_ctx(tmp_path), check_only=True))
    assert code == 1
    out = capsys.readouterr().out
    assert "!! docker: non trovato" in out


def test_non_blocking_failure_does_not_block_setup(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        doctor_module,
        "run_checks",
        lambda repo_root: [_ok_check(), _ok_check(name="uv", ok=False, detail="non trovato", blocking=False)],
    )
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: False)
    monkeypatch.setattr(setup_wizard, "default_machine_name", lambda: "host1")
    _run(
        _ctx(tmp_path, machine=MachineConfig(name="host1", role="node")),
        name="host1",
        role="node",
        db_port=5432,
        logs_retention_days=90,
        backups_keep=5,
    )
    out = capsys.readouterr().out
    assert "!! uv: non trovato" in out
    assert "Configurazione invariata." in out


def test_full_prereq_failure_exits_1_with_message(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        doctor_module, "run_checks", lambda repo_root: [_ok_check(ok=False, detail="assente", blocking=True)]
    )
    code = _exit_code(lambda: _run(_ctx(tmp_path)))
    assert code == 1
    out = _all_output(capsys)
    assert "Uno o piu' prerequisiti obbligatori non sono soddisfatti" in out


# --- config esistente: sovrascrivere? ---


def test_existing_config_overwrite_declined(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: False)
    write_called = {"called": False}
    monkeypatch.setattr(setup_wizard, "write_config", lambda *a, **kw: write_called.__setitem__("called", True))
    existing = MachineConfig(name="host1", role="node")
    _run(_ctx(tmp_path, machine=existing))
    out = capsys.readouterr().out
    assert "Configurazione invariata." in out
    assert write_called["called"] is False


def test_existing_config_overwrite_accepted_proceeds(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: True)
    monkeypatch.setattr(setup_wizard, "write_config", lambda repo_root, config: tmp_path / "payroll.local.toml")
    monkeypatch.setattr(setup_wizard, "maybe_write_override", lambda repo_root, db_port, log=print: None)
    monkeypatch.setattr(setup_wizard, "ensure_env_password", lambda repo_root, log=print: None)
    existing = MachineConfig(name="host1", role="node")
    _run(
        _ctx(tmp_path, machine=existing),
        name="host1",
        role="node",
        db_port=5432,
        logs_retention_days=90,
        backups_keep=5,
    )
    out = capsys.readouterr().out
    assert "Configurazione scritta in" in out
    assert "Bootstrap non richiesto" in out


# --- ruolo non valido ---


def test_invalid_role_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    code = _exit_code(
        lambda: _run(_ctx(tmp_path), name="host1", role="bogus", db_port=5432, logs_retention_days=90, backups_keep=5)
    )
    assert code == 1
    out = _all_output(capsys)
    assert "Ruolo non valido: 'bogus'" in out


# --- prompt bypassati se i parametri sono espliciti ---


def test_all_params_explicit_skips_all_prompts(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])

    def fail_prompt(*a, **kw):
        raise AssertionError("prompt non dovrebbe essere chiamato: tutti i parametri sono espliciti")

    monkeypatch.setattr(typer, "prompt", fail_prompt)
    captured = {}
    monkeypatch.setattr(
        setup_wizard,
        "write_config",
        lambda repo_root, config: captured.setdefault("config", config) and (tmp_path / "payroll.local.toml"),
    )
    monkeypatch.setattr(setup_wizard, "maybe_write_override", lambda repo_root, db_port, log=print: None)
    monkeypatch.setattr(setup_wizard, "ensure_env_password", lambda repo_root, log=print: None)
    _run(
        _ctx(tmp_path),
        name="host2",
        role="source",
        db_port=5433,
        logs_retention_days=30,
        backups_keep=3,
    )
    config = captured["config"]
    assert config.name == "host2"
    assert config.role == "source"
    assert config.db_host_port == 5433
    assert config.logs_retention_days == 30
    assert config.backups_keep == 3


def test_missing_params_are_prompted(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    monkeypatch.setattr(setup_wizard, "default_machine_name", lambda: "auto-host")
    prompts = []

    def fake_prompt(text, default=None, type=None):
        prompts.append(text)
        return default

    monkeypatch.setattr(typer, "prompt", fake_prompt)
    monkeypatch.setattr(setup_wizard, "write_config", lambda repo_root, config: tmp_path / "payroll.local.toml")
    monkeypatch.setattr(setup_wizard, "maybe_write_override", lambda repo_root, db_port, log=print: None)
    monkeypatch.setattr(setup_wizard, "ensure_env_password", lambda repo_root, log=print: None)
    _run(_ctx(tmp_path))
    assert "Nome macchina" in prompts
    assert "Ruolo (source/node)" in prompts
    assert "Porta host del DB" in prompts
    assert "Retention log (giorni)" in prompts
    assert "Backup da conservare" in prompts


# --- deploy key ---


def test_deploy_key_skipped_for_source_role(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    monkeypatch.setattr(setup_wizard, "write_config", lambda repo_root, config: tmp_path / "payroll.local.toml")
    monkeypatch.setattr(setup_wizard, "maybe_write_override", lambda repo_root, db_port, log=print: None)
    monkeypatch.setattr(setup_wizard, "ensure_env_password", lambda repo_root, log=print: None)
    ensure_called = {"called": False}
    monkeypatch.setattr(
        deploy_key_module, "ensure_deploy_key", lambda *a, **kw: ensure_called.__setitem__("called", True)
    )
    _run(
        _ctx(tmp_path),
        name="host1",
        role="source",
        db_port=5432,
        logs_retention_days=90,
        backups_keep=5,
        gen_deploy_key=True,
    )
    out = capsys.readouterr().out
    assert "una deploy key read-only non serve qui" in out
    assert ensure_called["called"] is False


def _patch_config_write(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_wizard, "write_config", lambda repo_root, config: tmp_path / "payroll.local.toml")
    monkeypatch.setattr(setup_wizard, "maybe_write_override", lambda repo_root, db_port, log=print: None)
    monkeypatch.setattr(setup_wizard, "ensure_env_password", lambda repo_root, log=print: None)


def test_deploy_key_error_on_ensure_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _patch_config_write(monkeypatch, tmp_path)

    def fake_ensure(*a, **kw):
        raise deploy_key_module.DeployKeyError("ssh-keygen fallito")

    monkeypatch.setattr(deploy_key_module, "ensure_deploy_key", fake_ensure)
    code = _exit_code(
        lambda: _run(
            _ctx(tmp_path),
            name="node1",
            role="node",
            db_port=5432,
            logs_retention_days=90,
            backups_keep=5,
            gen_deploy_key=True,
        )
    )
    assert code == 1
    out = _all_output(capsys)
    assert "ERRORE: ssh-keygen fallito" in out


def test_deploy_key_generated_and_https_switched_to_ssh(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _patch_config_write(monkeypatch, tmp_path)
    status = deploy_key_module.DeployKeyStatus(
        private_key=tmp_path / "key", public_key=tmp_path / "key.pub", generated=True, public_key_content="ssh-ed25519 AAAA"
    )
    monkeypatch.setattr(deploy_key_module, "ensure_deploy_key", lambda: status)
    monkeypatch.setattr(deploy_key_module, "get_remote_url", lambda repo_root: "https://github.com/acme/payroll-analizer")
    monkeypatch.setattr(
        deploy_key_module, "https_to_ssh_url", lambda url: "git@github.com:acme/payroll-analizer.git"
    )
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: True)
    set_url_called = {}
    monkeypatch.setattr(
        deploy_key_module, "set_remote_url", lambda repo_root, remote, url: set_url_called.setdefault("url", url)
    )
    monkeypatch.setattr(deploy_key_module, "configure_ssh_command", lambda repo_root, key_path: None)
    _run(
        _ctx(tmp_path),
        name="node1",
        role="node",
        db_port=5432,
        logs_retention_days=90,
        backups_keep=5,
        gen_deploy_key=True,
    )
    out = capsys.readouterr().out
    assert "Generata nuova deploy key:" in out
    assert "ssh-ed25519 AAAA" in out
    assert "Remote aggiornato a SSH." in out
    assert set_url_called["url"] == "git@github.com:acme/payroll-analizer.git"


def test_deploy_key_already_present_https_switch_declined(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _patch_config_write(monkeypatch, tmp_path)
    status = deploy_key_module.DeployKeyStatus(
        private_key=tmp_path / "key", public_key=tmp_path / "key.pub", generated=False, public_key_content="ssh-ed25519 BBBB"
    )
    monkeypatch.setattr(deploy_key_module, "ensure_deploy_key", lambda: status)
    monkeypatch.setattr(deploy_key_module, "get_remote_url", lambda repo_root: "https://github.com/acme/payroll-analizer")
    monkeypatch.setattr(
        deploy_key_module, "https_to_ssh_url", lambda url: "git@github.com:acme/payroll-analizer.git"
    )
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: False)
    monkeypatch.setattr(deploy_key_module, "configure_ssh_command", lambda repo_root, key_path: None)
    _run(
        _ctx(tmp_path),
        name="node1",
        role="node",
        db_port=5432,
        logs_retention_days=90,
        backups_keep=5,
        gen_deploy_key=True,
    )
    out = capsys.readouterr().out
    assert "Deploy key gia' presente:" in out
    assert "Remote lasciato HTTPS" in out


def test_deploy_key_already_ssh_skips_switch_prompt(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _patch_config_write(monkeypatch, tmp_path)
    status = deploy_key_module.DeployKeyStatus(
        private_key=tmp_path / "key", public_key=tmp_path / "key.pub", generated=False, public_key_content="ssh-ed25519 CCCC"
    )
    monkeypatch.setattr(deploy_key_module, "ensure_deploy_key", lambda: status)
    monkeypatch.setattr(deploy_key_module, "get_remote_url", lambda repo_root: "git@github.com:acme/payroll-analizer.git")
    monkeypatch.setattr(deploy_key_module, "https_to_ssh_url", lambda url: None)

    def fail_confirm(*a, **kw):
        raise AssertionError("confirm non dovrebbe essere chiamato: remote gia' SSH")

    monkeypatch.setattr(typer, "confirm", fail_confirm)
    monkeypatch.setattr(deploy_key_module, "configure_ssh_command", lambda repo_root, key_path: None)
    _run(
        _ctx(tmp_path),
        name="node1",
        role="node",
        db_port=5432,
        logs_retention_days=90,
        backups_keep=5,
        gen_deploy_key=True,
    )
    out = capsys.readouterr().out
    assert "core.sshCommand impostato" in out


def test_deploy_key_get_remote_url_error_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _patch_config_write(monkeypatch, tmp_path)
    status = deploy_key_module.DeployKeyStatus(
        private_key=tmp_path / "key", public_key=tmp_path / "key.pub", generated=True, public_key_content="ssh-ed25519 DDDD"
    )
    monkeypatch.setattr(deploy_key_module, "ensure_deploy_key", lambda: status)

    def fake_get_remote(repo_root):
        raise deploy_key_module.DeployKeyError("remote 'origin' non trovato")

    monkeypatch.setattr(deploy_key_module, "get_remote_url", fake_get_remote)
    code = _exit_code(
        lambda: _run(
            _ctx(tmp_path),
            name="node1",
            role="node",
            db_port=5432,
            logs_retention_days=90,
            backups_keep=5,
            gen_deploy_key=True,
        )
    )
    assert code == 1
    out = _all_output(capsys)
    assert "ERRORE: remote 'origin' non trovato" in out


def test_deploy_key_configure_ssh_command_error_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _patch_config_write(monkeypatch, tmp_path)
    status = deploy_key_module.DeployKeyStatus(
        private_key=tmp_path / "key", public_key=tmp_path / "key.pub", generated=False, public_key_content="ssh-ed25519 EEEE"
    )
    monkeypatch.setattr(deploy_key_module, "ensure_deploy_key", lambda: status)
    monkeypatch.setattr(deploy_key_module, "get_remote_url", lambda repo_root: "git@github.com:acme/payroll-analizer.git")
    monkeypatch.setattr(deploy_key_module, "https_to_ssh_url", lambda url: None)

    def fake_configure(repo_root, key_path):
        raise deploy_key_module.DeployKeyError("git config fallito")

    monkeypatch.setattr(deploy_key_module, "configure_ssh_command", fake_configure)
    code = _exit_code(
        lambda: _run(
            _ctx(tmp_path),
            name="node1",
            role="node",
            db_port=5432,
            logs_retention_days=90,
            backups_keep=5,
            gen_deploy_key=True,
        )
    )
    assert code == 1
    out = _all_output(capsys)
    assert "ERRORE: git config fallito" in out


# --- bootstrap ---


def test_bootstrap_not_requested_prints_hint_and_returns(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _patch_config_write(monkeypatch, tmp_path)
    _run(
        _ctx(tmp_path),
        name="host1",
        role="node",
        db_port=5432,
        logs_retention_days=90,
        backups_keep=5,
        do_bootstrap=False,
    )
    out = capsys.readouterr().out
    assert "Bootstrap non richiesto (--bootstrap per eseguirlo)" in out


def test_bootstrap_declined(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _patch_config_write(monkeypatch, tmp_path)
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: False)
    bootstrap_called = {"called": False}
    monkeypatch.setattr(setup_wizard, "bootstrap", lambda *a, **kw: bootstrap_called.__setitem__("called", True))
    _run(
        _ctx(tmp_path),
        name="host1",
        role="node",
        db_port=5432,
        logs_retention_days=90,
        backups_keep=5,
        do_bootstrap=True,
    )
    out = capsys.readouterr().out
    assert "Bootstrap saltato." in out
    assert bootstrap_called["called"] is False


def test_bootstrap_accepted_success(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _patch_config_write(monkeypatch, tmp_path)
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: True)
    monkeypatch.setattr(setup_wizard, "bootstrap", lambda repo_root, log=print: None)
    _run(
        _ctx(tmp_path),
        name="host1",
        role="node",
        db_port=5432,
        logs_retention_days=90,
        backups_keep=5,
        do_bootstrap=True,
    )
    out = capsys.readouterr().out
    assert "Setup completato." in out


def test_bootstrap_accepted_failure_exits_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(doctor_module, "run_checks", lambda repo_root: [_ok_check()])
    _patch_config_write(monkeypatch, tmp_path)
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: True)

    def fake_bootstrap(repo_root, log=print):
        raise setup_wizard.BootstrapError("build fallita")

    monkeypatch.setattr(setup_wizard, "bootstrap", fake_bootstrap)
    code = _exit_code(
        lambda: _run(
            _ctx(tmp_path),
            name="host1",
            role="node",
            db_port=5432,
            logs_retention_days=90,
            backups_keep=5,
            do_bootstrap=True,
        )
    )
    assert code == 1
    out = _all_output(capsys)
    assert "ERRORE: build fallita" in out
