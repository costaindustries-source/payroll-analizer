"""Test per payroll_cli.releaser ('payroll release new/list'): preflight,
smoke test, promozione CHANGELOG, tag+push, creazione GitHub Release. git e'
reale in tmp_path (nessun remote configurato); push/gh sono sempre mockati:
mai un push o una release GitHub reali."""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from payroll_cli import git_ops, releaser
from payroll_cli.context import MachineConfig


def _cp(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _git(repo_root, *args, check=True):
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, stdin=subprocess.DEVNULL
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


def _init_repo_on_main(repo_root: Path) -> None:
    _git(repo_root, "init", "-q", "-b", "main")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / "CHANGELOG.md").write_text("## [Non rilasciato]\n\n- nulla\n", encoding="utf-8")
    _git(repo_root, "add", "CHANGELOG.md")
    _git(repo_root, "commit", "-q", "-m", "init")


# --- check_role ---

def test_check_role_none_raises():
    with pytest.raises(releaser.ReleaseError):
        releaser.check_role(None)


def test_check_role_wrong_role_raises():
    with pytest.raises(releaser.ReleaseError):
        releaser.check_role(MachineConfig(name="n", role="node"))


def test_check_role_source_ok():
    releaser.check_role(MachineConfig(name="n", role="source"))  # non deve sollevare


# --- preflight ---

def test_preflight_invalid_version_raises(tmp_path):
    _init_repo_on_main(tmp_path)
    with pytest.raises(releaser.ReleaseError):
        releaser.preflight(tmp_path, "not-a-version")


def test_preflight_wrong_branch_raises(tmp_path):
    _init_repo_on_main(tmp_path)
    _git(tmp_path, "checkout", "-q", "-b", "feature/x")
    with pytest.raises(releaser.ReleaseError, match="feature/x"):
        releaser.preflight(tmp_path, "v1.0.0")


def test_preflight_dirty_worktree_raises(tmp_path):
    _init_repo_on_main(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text("dirty", encoding="utf-8")
    with pytest.raises(releaser.ReleaseError):
        releaser.preflight(tmp_path, "v1.0.0")


def test_preflight_existing_tag_raises(tmp_path):
    _init_repo_on_main(tmp_path)
    _git(tmp_path, "tag", "v1.0.0")
    with pytest.raises(releaser.ReleaseError, match="v1.0.0"):
        releaser.preflight(tmp_path, "v1.0.0")


def test_preflight_ok(tmp_path):
    _init_repo_on_main(tmp_path)
    releaser.preflight(tmp_path, "v1.0.0")  # non deve sollevare


# --- run_smoke_test ---

def test_run_smoke_test_missing_samples_raises(tmp_path):
    with pytest.raises(releaser.ReleaseError, match="Campioni"):
        releaser.run_smoke_test(tmp_path)


def test_run_smoke_test_failure_raises(tmp_path, monkeypatch):
    samples_dir = tmp_path / "docs" / "payroll-test"
    samples_dir.mkdir(parents=True)
    (samples_dir / "s.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(releaser.subprocess, "run", lambda *a, **k: _cp(returncode=1))
    with pytest.raises(releaser.ReleaseError, match="Smoke test"):
        releaser.run_smoke_test(tmp_path)


def test_run_smoke_test_success(tmp_path, monkeypatch):
    samples_dir = tmp_path / "docs" / "payroll-test"
    samples_dir.mkdir(parents=True)
    (samples_dir / "s.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(releaser.subprocess, "run", lambda *a, **k: _cp(returncode=0))
    releaser.run_smoke_test(tmp_path)  # non deve sollevare


# --- promote_changelog ---

def test_promote_changelog_missing_file_raises(tmp_path):
    with pytest.raises(releaser.ReleaseError):
        releaser.promote_changelog(tmp_path, "v1.0.0")


def test_promote_changelog_missing_heading_raises(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    with pytest.raises(releaser.ReleaseError):
        releaser.promote_changelog(tmp_path, "v1.0.0")


def test_promote_changelog_empty_section_returns_false(tmp_path):
    original = "## [Non rilasciato]\n\n## [v0.9.0] - 2026-01-01\n"
    (tmp_path / "CHANGELOG.md").write_text(original, encoding="utf-8")
    changed = releaser.promote_changelog(tmp_path, "v1.0.0")
    assert changed is False
    assert (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8") == original


def test_promote_changelog_promotes_section(tmp_path):
    original = (
        "## [Non rilasciato]\n\n"
        "- fix importante\n\n"
        "## [v0.9.0] - 2026-01-01\n\n- vecchia voce\n"
    )
    (tmp_path / "CHANGELOG.md").write_text(original, encoding="utf-8")
    changed = releaser.promote_changelog(tmp_path, "v1.0.0", release_date="2026-07-15")
    assert changed is True
    new_text = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Non rilasciato]\n\n## [v1.0.0] - 2026-07-15\n\n- fix importante" in new_text
    assert "## [v0.9.0] - 2026-01-01\n\n- vecchia voce" in new_text
    # la sezione "Non rilasciato" resta vuota in cima, pronta per il prossimo giro
    assert new_text.index("## [Non rilasciato]") < new_text.index("## [v1.0.0]")


def test_promote_changelog_default_date_is_today(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("## [Non rilasciato]\n\n- x\n", encoding="utf-8")
    releaser.promote_changelog(tmp_path, "v2.0.0")
    new_text = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    today = datetime.now(timezone.utc).date().isoformat()
    assert f"## [v2.0.0] - {today}" in new_text


# --- commit_changelog ---

def test_commit_changelog_creates_commit(tmp_path):
    _init_repo_on_main(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "## [Non rilasciato]\n\n## [v1.0.0] - 2026-07-15\n", encoding="utf-8"
    )
    releaser.commit_changelog(tmp_path, "v1.0.0")
    log = _git(tmp_path, "log", "-1", "--format=%s").stdout.strip()
    assert log == "docs: prepara CHANGELOG per rilascio v1.0.0"


def test_commit_changelog_nothing_to_commit_raises(tmp_path):
    _init_repo_on_main(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        releaser.commit_changelog(tmp_path, "v1.0.0")


# --- create_tag ---

def test_create_tag_success(tmp_path):
    _init_repo_on_main(tmp_path)
    releaser.create_tag(tmp_path, "v1.0.0", "release v1.0.0")
    assert "v1.0.0" in git_ops.list_local_tags(tmp_path)


def test_create_tag_duplicate_raises(tmp_path):
    _init_repo_on_main(tmp_path)
    releaser.create_tag(tmp_path, "v1.0.0", "release v1.0.0")
    with pytest.raises(releaser.ReleaseError):
        releaser.create_tag(tmp_path, "v1.0.0", "release v1.0.0 bis")


# --- push (mockato: mai una push reale) ---

def test_push_runs_branch_then_tag(tmp_path, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _cp(returncode=0)

    monkeypatch.setattr(releaser.subprocess, "run", fake_run)
    releaser.push(tmp_path, "v1.0.0")
    assert calls == [
        ["git", "push", "origin", "main"],
        ["git", "push", "origin", "v1.0.0"],
    ]


def test_push_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(releaser.subprocess, "run", lambda args, **k: _cp(returncode=1, stderr="rejected"))
    with pytest.raises(releaser.ReleaseError, match="rejected"):
        releaser.push(tmp_path, "v1.0.0")


# --- create_github_release (mockato: mai gh reale) ---

def test_create_github_release_success(tmp_path, monkeypatch):
    monkeypatch.setattr(
        releaser.subprocess, "run",
        lambda *a, **k: _cp(returncode=0, stdout="https://github.com/x/releases/v1.0.0"),
    )
    logs = []
    ok = releaser.create_github_release(tmp_path, "v1.0.0", "note", log=logs.append)
    assert ok is True
    assert any("GitHub Release creata" in m for m in logs)


def test_create_github_release_failure_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(releaser.subprocess, "run", lambda *a, **k: _cp(returncode=1, stderr="not authenticated"))
    logs = []
    ok = releaser.create_github_release(tmp_path, "v1.0.0", "note", log=logs.append)
    assert ok is False
    assert any("ATTENZIONE" in m for m in logs)


def test_create_github_release_empty_notes_placeholder(tmp_path, monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _cp(returncode=0)

    monkeypatch.setattr(releaser.subprocess, "run", fake_run)
    releaser.create_github_release(tmp_path, "v1.0.0", "")
    assert "(nessuna voce in CHANGELOG.md)" in captured["args"]


# --- list_releases ---

def test_list_releases_no_fetch(tmp_path, monkeypatch):
    def _no_fetch(repo_root):
        raise AssertionError("non deve fetchare se fetch=False")

    monkeypatch.setattr(git_ops, "fetch_tags", _no_fetch)
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: ["v1.0.0", "v1.1.0"])
    monkeypatch.setattr(git_ops, "tag_date", lambda repo_root, tag: "2026-01-01")
    monkeypatch.setattr(git_ops, "tag_subject", lambda repo_root, tag: f"subject {tag}")
    result = releaser.list_releases(tmp_path, fetch=False)
    assert [r.tag for r in result] == ["v1.1.0", "v1.0.0"]
    assert all(r.pushed is False for r in result)


def test_list_releases_with_fetch_marks_pushed(tmp_path, monkeypatch):
    fetched = []
    monkeypatch.setattr(git_ops, "fetch_tags", lambda repo_root: fetched.append(True))
    monkeypatch.setattr(git_ops, "list_local_tags", lambda repo_root: ["v1.0.0", "v1.1.0"])
    monkeypatch.setattr(git_ops, "list_remote_tags", lambda repo_root: ["v1.0.0"])
    monkeypatch.setattr(git_ops, "tag_date", lambda repo_root, tag: "2026-01-01")
    monkeypatch.setattr(git_ops, "tag_subject", lambda repo_root, tag: "subj")
    result = releaser.list_releases(tmp_path, fetch=True)
    assert fetched == [True]
    pushed_map = {r.tag: r.pushed for r in result}
    assert pushed_map == {"v1.0.0": True, "v1.1.0": False}
