"""Test di payroll_cli.commands.update (update_app): 'update check' e
'update apply' (incluso il percorso --resume, uso interno post-checkout).
update_app e' montato su un piccolo Typer 'root' che imposta ctx.obj.
payroll_cli.{changelog,db,git_ops,semver,updater} sono mockati: nessun
git/docker/postgres reale."""

from __future__ import annotations

import typer
from typer.testing import CliRunner

from payroll_cli import changelog
from payroll_cli import db as db_module
from payroll_cli import git_ops, semver, updater
from payroll_cli.commands.update import update_app
from payroll_cli.context import Context

runner = CliRunner()


def _root_app(ctx_obj: Context) -> typer.Typer:
    root = typer.Typer()

    @root.callback()
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = ctx_obj

    root.add_typer(update_app, name="update")
    return root


def _ctx(tmp_path):
    return Context(repo_root=tmp_path, machine=None)


def _ok_fetch(monkeypatch):
    monkeypatch.setattr(git_ops, "fetch_tags", lambda repo_root: git_ops.GitResult(0, "", ""))


# --- update check ---


def test_check_fetch_failure_exits_1(monkeypatch, tmp_path):
    monkeypatch.setattr(git_ops, "fetch_tags", lambda repo_root: git_ops.GitResult(1, "", "rete assente"))
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "check"])
    assert result.exit_code == 1
    assert "git fetch fallito: rete assente" in result.output


def test_check_no_current_tag_exits_1(monkeypatch, tmp_path):
    _ok_fetch(monkeypatch)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: None)
    monkeypatch.setattr(git_ops, "nearest_tag", lambda repo_root: None)
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: [])
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "check"])
    assert result.exit_code == 1
    assert "Impossibile determinare il tag corrente" in result.output


def test_check_already_up_to_date(monkeypatch, tmp_path):
    _ok_fetch(monkeypatch)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: "v1.2.0")
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: ["v1.2.0"])
    monkeypatch.setattr(semver, "latest", lambda tags: "v1.2.0")
    monkeypatch.setattr(semver, "tags_after", lambda tags, baseline: [])
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "check"])
    assert result.exit_code == 0
    assert "Versione corrente: v1.2.0" in result.output
    assert "Sei aggiornato." in result.output


def test_check_pending_versions_listed_with_changelog(monkeypatch, tmp_path):
    _ok_fetch(monkeypatch)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: "v1.2.0")
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: ["v1.2.0", "v1.3.0", "v1.4.0"])
    monkeypatch.setattr(semver, "latest", lambda tags: "v1.4.0")
    monkeypatch.setattr(semver, "tags_after", lambda tags, baseline: ["v1.3.0", "v1.4.0"])

    def fake_section(repo_root, tag):
        return "note per " + tag if tag == "v1.3.0" else None

    monkeypatch.setattr(changelog, "section_for_tag", fake_section)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "check"])
    assert result.exit_code == 0
    assert "2 versione/i disponibile/i: v1.3.0, v1.4.0" in result.output
    assert "--- v1.3.0 ---" in result.output
    assert "note per v1.3.0" in result.output
    assert "--- v1.4.0 ---" in result.output
    assert "(nessuna voce in CHANGELOG.md)" in result.output
    assert "payroll update apply --to v1.4.0" in result.output


# --- update apply: percorso normale ---


def test_apply_fetch_failure_exits_1(monkeypatch, tmp_path):
    monkeypatch.setattr(git_ops, "fetch_tags", lambda repo_root: git_ops.GitResult(1, "", "no network"))
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply"])
    assert result.exit_code == 1
    assert "git fetch fallito: no network" in result.output


def test_apply_dirty_worktree_exits_1(monkeypatch, tmp_path):
    _ok_fetch(monkeypatch)

    def fake_ensure_clean(repo_root):
        raise updater.UpdateError("working tree sporco")

    monkeypatch.setattr(updater, "ensure_clean_worktree", fake_ensure_clean)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply"])
    assert result.exit_code == 1
    assert "ERRORE: working tree sporco" in result.output


def test_apply_resolve_target_failure_exits_1(monkeypatch, tmp_path):
    _ok_fetch(monkeypatch)
    monkeypatch.setattr(updater, "ensure_clean_worktree", lambda repo_root: None)

    def fake_resolve(repo_root, to_tag):
        raise updater.UpdateError("tag non trovato")

    monkeypatch.setattr(updater, "resolve_target", fake_resolve)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply"])
    assert result.exit_code == 1
    assert "ERRORE: tag non trovato" in result.output


def test_apply_already_at_target_returns_without_confirm(monkeypatch, tmp_path):
    _ok_fetch(monkeypatch)
    monkeypatch.setattr(updater, "ensure_clean_worktree", lambda repo_root: None)
    monkeypatch.setattr(updater, "resolve_target", lambda repo_root, to_tag: "v1.0.0")
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: "v1.0.0")
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply"])
    assert result.exit_code == 0
    assert "Gia' aggiornato a v1.0.0." in result.output


def _patch_apply_prereqs(monkeypatch, *, current="v1.0.0", target="v1.1.0", volume_changed=False):
    _ok_fetch(monkeypatch)
    monkeypatch.setattr(updater, "ensure_clean_worktree", lambda repo_root: None)
    monkeypatch.setattr(updater, "resolve_target", lambda repo_root, to_tag: target)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: current)
    monkeypatch.setattr(git_ops, "nearest_tag", lambda repo_root: current)
    monkeypatch.setattr(updater, "pg_volume_changed", lambda repo_root, c, t: volume_changed)


def test_apply_declined_confirmation_exits_0(monkeypatch, tmp_path):
    _patch_apply_prereqs(monkeypatch)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply"], input="n\n")
    assert result.exit_code == 0
    assert "Interrotto su richiesta." in result.output


def test_apply_volume_changed_warns_before_confirm(monkeypatch, tmp_path):
    _patch_apply_prereqs(monkeypatch, volume_changed=True)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply"], input="n\n")
    assert "Il volume dati Postgres cambia nome" in result.output


def test_apply_backup_failure_exits_1(monkeypatch, tmp_path):
    _patch_apply_prereqs(monkeypatch, volume_changed=True)

    def fake_backup(repo_root, log=print):
        raise db_module.DbError("dump fallito")

    monkeypatch.setattr(db_module, "backup", fake_backup)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply"], input="y\n")
    assert result.exit_code == 1
    assert "ERRORE: backup fallito, aggiornamento interrotto: dump fallito" in result.output


def test_apply_checkout_failure_exits_1(monkeypatch, tmp_path):
    _patch_apply_prereqs(monkeypatch, volume_changed=False)

    def fake_checkout(repo_root, tag):
        raise updater.UpdateError("checkout fallito")

    monkeypatch.setattr(updater, "checkout", fake_checkout)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply"], input="y\n")
    assert result.exit_code == 1
    assert "ERRORE: checkout fallito" in result.output


def test_apply_reexec_success_logs_update_and_exits_0(monkeypatch, tmp_path):
    _patch_apply_prereqs(monkeypatch, volume_changed=True)
    monkeypatch.setattr(db_module, "backup", lambda repo_root, log=print: None)
    monkeypatch.setattr(updater, "checkout", lambda repo_root, tag: None)
    monkeypatch.setattr(updater, "reexec_resume", lambda repo_root, previous_tag: 0)
    logged = {}
    monkeypatch.setattr(
        updater, "log_update", lambda repo_root, from_tag, to_tag, outcome: logged.update(
            from_tag=from_tag, to_tag=to_tag, outcome=outcome
        )
    )
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply"], input="y\n")
    assert result.exit_code == 0
    assert logged == {"from_tag": "v1.0.0", "to_tag": "v1.1.0", "outcome": "OK"}


def test_apply_reexec_failure_skips_log_and_propagates_exit_code(monkeypatch, tmp_path):
    _patch_apply_prereqs(monkeypatch, volume_changed=False)
    monkeypatch.setattr(updater, "checkout", lambda repo_root, tag: None)
    monkeypatch.setattr(updater, "reexec_resume", lambda repo_root, previous_tag: 7)
    logged = {"called": False}
    monkeypatch.setattr(updater, "log_update", lambda *a, **kw: logged.__setitem__("called", True))
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply"], input="y\n")
    assert result.exit_code == 7
    assert logged["called"] is False


# --- update apply --resume (uso interno post-checkout) ---


def test_apply_resume_success(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "resume", lambda repo_root, log=print: None)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply", "--resume"])
    assert result.exit_code == 0
    assert "Aggiornamento completato e verificato." in result.output


def test_apply_resume_failure_without_previous_tag_no_rollback_prompt(monkeypatch, tmp_path):
    def fake_resume(repo_root, log=print):
        raise updater.UpdateError("migration fallita")

    monkeypatch.setattr(updater, "resume", fake_resume)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: "v1.1.0")
    monkeypatch.setattr(updater, "log_update", lambda *a, **kw: None)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["update", "apply", "--resume"])
    assert result.exit_code == 1
    assert "ERRORE: migration fallita" in result.output
    assert "Rollback automatico" not in result.output


def test_apply_resume_failure_with_previous_tag_rollback_declined(monkeypatch, tmp_path):
    def fake_resume(repo_root, log=print):
        raise updater.UpdateError("migration fallita")

    monkeypatch.setattr(updater, "resume", fake_resume)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: "v1.1.0")
    monkeypatch.setattr(updater, "log_update", lambda *a, **kw: None)
    rollback_called = {"called": False}
    monkeypatch.setattr(updater, "do_rollback", lambda *a, **kw: rollback_called.__setitem__("called", True))
    result = runner.invoke(
        _root_app(_ctx(tmp_path)), ["update", "apply", "--resume", "--previous-tag", "v1.0.0"], input="n\n"
    )
    assert result.exit_code == 1
    assert rollback_called["called"] is False


def test_apply_resume_failure_with_previous_tag_rollback_accepted_succeeds(monkeypatch, tmp_path):
    def fake_resume(repo_root, log=print):
        raise updater.UpdateError("migration fallita")

    monkeypatch.setattr(updater, "resume", fake_resume)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: "v1.1.0")
    monkeypatch.setattr(updater, "log_update", lambda *a, **kw: None)
    monkeypatch.setattr(updater, "do_rollback", lambda repo_root, tag, log=print: None)
    result = runner.invoke(
        _root_app(_ctx(tmp_path)), ["update", "apply", "--resume", "--previous-tag", "v1.0.0"], input="y\n"
    )
    assert result.exit_code == 1  # sempre 1: il resume e' comunque fallito
    assert "Rollback a v1.0.0 completato." in result.output


def test_apply_resume_failure_with_previous_tag_rollback_accepted_but_rollback_fails(monkeypatch, tmp_path):
    def fake_resume(repo_root, log=print):
        raise updater.UpdateError("migration fallita")

    def fake_rollback(repo_root, tag, log=print):
        raise updater.UpdateError("rollback fallito anche lui")

    monkeypatch.setattr(updater, "resume", fake_resume)
    monkeypatch.setattr(git_ops, "exact_tag_on_head", lambda repo_root: "v1.1.0")
    monkeypatch.setattr(updater, "log_update", lambda *a, **kw: None)
    monkeypatch.setattr(updater, "do_rollback", fake_rollback)
    result = runner.invoke(
        _root_app(_ctx(tmp_path)), ["update", "apply", "--resume", "--previous-tag", "v1.0.0"], input="y\n"
    )
    assert result.exit_code == 1
    assert "ERRORE: rollback fallito: rollback fallito anche lui" in result.output
