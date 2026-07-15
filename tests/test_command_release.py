"""Test di payroll_cli.commands.release (release_app): 'release new' e
'release list'. release_app e' montato su un piccolo Typer 'root' che imposta
ctx.obj. payroll_cli.releaser/changelog sono mockati: nessun git/gh reale."""

from __future__ import annotations

import typer
from typer.testing import CliRunner

from payroll_cli import changelog, releaser
from payroll_cli.commands.release import release_app
from payroll_cli.context import Context, MachineConfig

runner = CliRunner()


def _root_app(ctx_obj: Context) -> typer.Typer:
    root = typer.Typer()

    @root.callback()
    def _cb(ctx: typer.Context) -> None:
        ctx.obj = ctx_obj

    root.add_typer(release_app, name="release")
    return root


def _ctx(tmp_path, role="source"):
    return Context(repo_root=tmp_path, machine=MachineConfig(name="dev", role=role))


def _patch_happy_path(monkeypatch, *, promoted=True):
    monkeypatch.setattr(releaser, "check_role", lambda machine: None)
    monkeypatch.setattr(releaser, "preflight", lambda repo_root, version: None)
    monkeypatch.setattr(releaser, "run_smoke_test", lambda repo_root, log=print: None)
    monkeypatch.setattr(releaser, "promote_changelog", lambda repo_root, version: promoted)
    monkeypatch.setattr(releaser, "commit_changelog", lambda repo_root, version: None)
    monkeypatch.setattr(releaser, "create_tag", lambda repo_root, version, message: None)
    monkeypatch.setattr(releaser, "push", lambda repo_root, version: None)
    monkeypatch.setattr(releaser, "create_github_release", lambda repo_root, version, notes, log=print: True)
    monkeypatch.setattr(changelog, "section_for_tag", lambda repo_root, tag: "note di rilascio")


# --- release new: guardie iniziali ---


def test_new_rejects_non_source_role(monkeypatch, tmp_path):
    def fake_check_role(machine):
        raise releaser.ReleaseError("riservato a role=source")

    monkeypatch.setattr(releaser, "check_role", fake_check_role)
    result = runner.invoke(_root_app(_ctx(tmp_path, role="node")), ["release", "new", "v1.0.0"])
    assert result.exit_code == 1
    assert "ERRORE: riservato a role=source" in result.output


def test_new_preflight_failure_exits_1(monkeypatch, tmp_path):
    monkeypatch.setattr(releaser, "check_role", lambda machine: None)

    def fake_preflight(repo_root, version):
        raise releaser.ReleaseError("working tree sporco")

    monkeypatch.setattr(releaser, "preflight", fake_preflight)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["release", "new", "v1.0.0"])
    assert result.exit_code == 1
    assert "ERRORE: working tree sporco" in result.output


def test_new_smoke_test_failure_exits_1(monkeypatch, tmp_path):
    monkeypatch.setattr(releaser, "check_role", lambda machine: None)
    monkeypatch.setattr(releaser, "preflight", lambda repo_root, version: None)

    def fake_smoke(repo_root, log=print):
        raise releaser.ReleaseError("smoke test fallito")

    monkeypatch.setattr(releaser, "run_smoke_test", fake_smoke)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["release", "new", "v1.0.0"])
    assert result.exit_code == 1
    assert "ERRORE: smoke test fallito" in result.output


# --- changelog ---


def test_new_promote_changelog_failure_exits_1(monkeypatch, tmp_path):
    monkeypatch.setattr(releaser, "check_role", lambda machine: None)
    monkeypatch.setattr(releaser, "preflight", lambda repo_root, version: None)
    monkeypatch.setattr(releaser, "run_smoke_test", lambda repo_root, log=print: None)

    def fake_promote(repo_root, version):
        raise releaser.ReleaseError("CHANGELOG.md non trovato")

    monkeypatch.setattr(releaser, "promote_changelog", fake_promote)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["release", "new", "v1.0.0", "-m", "msg"])
    assert result.exit_code == 1
    assert "ERRORE: CHANGELOG.md non trovato" in result.output


def test_new_promoted_changelog_commits_and_continues(monkeypatch, tmp_path):
    _patch_happy_path(monkeypatch, promoted=True)
    result = runner.invoke(
        _root_app(_ctx(tmp_path)), ["release", "new", "v1.0.0", "-m", "msg"], input="y\n"
    )
    assert result.exit_code == 0
    assert "promossa a '[v1.0.0]', committata." in result.output
    assert "Rilasciato v1.0.0 su GitHub." in result.output


def test_new_unreleased_section_empty_skips_commit(monkeypatch, tmp_path):
    _patch_happy_path(monkeypatch, promoted=False)
    committed = {"called": False}
    monkeypatch.setattr(releaser, "commit_changelog", lambda repo_root, version: committed.__setitem__("called", True))
    result = runner.invoke(
        _root_app(_ctx(tmp_path)), ["release", "new", "v1.0.0", "-m", "msg"], input="y\n"
    )
    assert result.exit_code == 0
    assert "Nessun contenuto in '[Non rilasciato]': CHANGELOG.md non modificato." in result.output
    assert committed["called"] is False


def test_new_message_prompted_when_not_given(monkeypatch, tmp_path):
    _patch_happy_path(monkeypatch, promoted=False)
    result = runner.invoke(
        _root_app(_ctx(tmp_path)), ["release", "new", "v1.0.0"], input="messaggio a mano\ny\n"
    )
    assert result.exit_code == 0
    assert "Messaggio di release per v1.0.0" in result.output


# --- conferma tag+push ---


def test_new_declined_confirmation_stops_before_tag(monkeypatch, tmp_path):
    _patch_happy_path(monkeypatch, promoted=False)
    tag_created = {"called": False}
    monkeypatch.setattr(releaser, "create_tag", lambda *a, **kw: tag_created.__setitem__("called", True))
    result = runner.invoke(
        _root_app(_ctx(tmp_path)), ["release", "new", "v1.0.0", "-m", "msg"], input="n\n"
    )
    assert result.exit_code == 0
    assert "Interrotto su richiesta." in result.output
    assert tag_created["called"] is False


def test_new_create_tag_failure_exits_1(monkeypatch, tmp_path):
    _patch_happy_path(monkeypatch, promoted=False)

    def fake_create_tag(repo_root, version, message):
        raise releaser.ReleaseError("tag esiste gia'")

    monkeypatch.setattr(releaser, "create_tag", fake_create_tag)
    result = runner.invoke(
        _root_app(_ctx(tmp_path)), ["release", "new", "v1.0.0", "-m", "msg"], input="y\n"
    )
    assert result.exit_code == 1
    assert "ERRORE: tag esiste gia'" in result.output


def test_new_push_failure_exits_1(monkeypatch, tmp_path):
    _patch_happy_path(monkeypatch, promoted=False)

    def fake_push(repo_root, version):
        raise releaser.ReleaseError("push rifiutato")

    monkeypatch.setattr(releaser, "push", fake_push)
    result = runner.invoke(
        _root_app(_ctx(tmp_path)), ["release", "new", "v1.0.0", "-m", "msg"], input="y\n"
    )
    assert result.exit_code == 1
    assert "ERRORE: push rifiutato" in result.output


# --- release list ---


def test_list_no_tags_found(monkeypatch, tmp_path):
    monkeypatch.setattr(releaser, "list_releases", lambda repo_root: [])
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["release", "list"])
    assert result.exit_code == 0
    assert "Nessun tag SemVer trovato." in result.output


def test_list_shows_pushed_and_local_only_tags(monkeypatch, tmp_path):
    infos = [
        releaser.TagInfo(tag="v1.1.0", date="2026-07-01", subject="release 1.1.0", pushed=True),
        releaser.TagInfo(tag="v1.2.0", date="2026-07-10", subject="release 1.2.0", pushed=False),
    ]
    monkeypatch.setattr(releaser, "list_releases", lambda repo_root: infos)
    result = runner.invoke(_root_app(_ctx(tmp_path)), ["release", "list"])
    assert result.exit_code == 0
    assert "v1.1.0\t2026-07-01\trelease 1.1.0" in result.output
    assert "(solo locale, non pushato)" not in result.output.split("v1.1.0")[1].split("\n")[0]
    assert "v1.2.0\t2026-07-10\trelease 1.2.0  (solo locale, non pushato)" in result.output
