"""Test per i wrapper git in payroll_cli.git_ops.

Usa repo git reali creati in tmp_path (mai il repo/config reale dell'utente):
piu' robusto di mockare subprocess e verifica il comportamento vero di git.
"""

import subprocess

from payroll_cli import git_ops

_ENV_ARGS = ["-c", "user.email=test@example.com", "-c", "user.name=Test"]


def _git(repo_root, *args):
    return subprocess.run(["git", *_ENV_ARGS, *args], cwd=repo_root, capture_output=True, text=True, check=True)


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "file.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-m", "initial commit")
    return repo


def test_current_branch(tmp_path):
    repo = _init_repo(tmp_path)
    assert git_ops.current_branch(repo) == "main"
    _git(repo, "checkout", "-b", "feature/OSQ-1-test")
    assert git_ops.current_branch(repo) == "feature/OSQ-1-test"


def test_exact_tag_on_head(tmp_path):
    repo = _init_repo(tmp_path)
    assert git_ops.exact_tag_on_head(repo) is None
    _git(repo, "tag", "v1.0.0")
    assert git_ops.exact_tag_on_head(repo) == "v1.0.0"


def test_nearest_tag_after_head_moved_past(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "tag", "v1.0.0")
    (repo / "file.txt").write_text("v2\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-m", "second commit")
    # HEAD non e' esattamente sul tag, ma nearest_tag lo trova comunque
    assert git_ops.exact_tag_on_head(repo) is None
    assert git_ops.nearest_tag(repo) == "v1.0.0"


def test_nearest_tag_none_when_no_tags(tmp_path):
    repo = _init_repo(tmp_path)
    assert git_ops.nearest_tag(repo) is None


def test_current_commit_short_and_full(tmp_path):
    repo = _init_repo(tmp_path)
    short = git_ops.current_commit(repo)
    full = git_ops.current_commit(repo, short=False)
    assert len(short) < len(full)
    assert full.startswith(short)


def test_is_dirty(tmp_path):
    repo = _init_repo(tmp_path)
    assert git_ops.is_dirty(repo) is False
    (repo / "file.txt").write_text("modificato\n", encoding="utf-8")
    assert git_ops.is_dirty(repo) is True


def test_list_local_tags(tmp_path):
    repo = _init_repo(tmp_path)
    assert git_ops.list_local_tags(repo) == []
    _git(repo, "tag", "v1.0.0")
    _git(repo, "tag", "v1.1.0")
    tags = git_ops.list_local_tags(repo)
    assert set(tags) == {"v1.0.0", "v1.1.0"}


def test_diff_file_between_refs(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "tag", "v1.0.0")
    (repo / "file.txt").write_text("v2\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-m", "modifica file")
    _git(repo, "tag", "v2.0.0")

    diff = git_ops.diff_file_between(repo, "v1.0.0", "v2.0.0", "file.txt")
    assert "v1" in diff
    assert "v2" in diff

    no_diff = git_ops.diff_file_between(repo, "v1.0.0", "v1.0.0", "file.txt")
    assert no_diff == ""


def test_tag_date_and_subject_lightweight_tag_falls_back_to_commit_subject(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "tag", "v1.0.0")  # tag leggero: nessun messaggio proprio
    date = git_ops.tag_date(repo, "v1.0.0")
    assert len(date) == 10  # formato YYYY-MM-DD
    # per un tag leggero, %(contents:subject) ricade sul subject del commit puntato
    assert git_ops.tag_subject(repo, "v1.0.0") == "initial commit"


def test_tag_subject_annotated_tag(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "tag", "-a", "v1.0.0", "-m", "Release v1.0.0\n\ndettagli qui")
    assert git_ops.tag_subject(repo, "v1.0.0") == "Release v1.0.0"


def test_pull_ff_only_success(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)

    origin_checkout = tmp_path / "origin_checkout"
    subprocess.run(["git", "clone", str(remote), str(origin_checkout)], check=True, capture_output=True)
    (origin_checkout / "file.txt").write_text("v1\n", encoding="utf-8")
    _git(origin_checkout, "add", "file.txt")
    _git(origin_checkout, "commit", "-m", "initial")
    _git(origin_checkout, "push", "origin", "main")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True)

    # nuovo commit pushato da un altro checkout: il clone locale puo' fare fast-forward
    (origin_checkout / "file.txt").write_text("v2\n", encoding="utf-8")
    _git(origin_checkout, "add", "file.txt")
    _git(origin_checkout, "commit", "-m", "second")
    _git(origin_checkout, "push", "origin", "main")

    result = git_ops.pull_ff_only(clone)
    assert result.ok
    assert (clone / "file.txt").read_text(encoding="utf-8") == "v2\n"


def test_pull_ff_only_fails_on_divergent_history(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)

    origin_checkout = tmp_path / "origin_checkout"
    subprocess.run(["git", "clone", str(remote), str(origin_checkout)], check=True, capture_output=True)
    (origin_checkout / "file.txt").write_text("v1\n", encoding="utf-8")
    _git(origin_checkout, "add", "file.txt")
    _git(origin_checkout, "commit", "-m", "initial")
    _git(origin_checkout, "push", "origin", "main")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True)

    # commit divergente sia sul remote sia sul clone locale
    (origin_checkout / "file.txt").write_text("remote-side\n", encoding="utf-8")
    _git(origin_checkout, "add", "file.txt")
    _git(origin_checkout, "commit", "-m", "remote side change")
    _git(origin_checkout, "push", "origin", "main")

    (clone / "file.txt").write_text("local-side\n", encoding="utf-8")
    _git(clone, "add", "file.txt")
    _git(clone, "commit", "-m", "local side change")

    result = git_ops.pull_ff_only(clone)
    assert not result.ok


def test_list_remote_tags_skips_lines_without_tab(tmp_path, monkeypatch):
    """Riga malformata (senza tab) in output da ls-remote: caso limite difficile
    da riprodurre con un remote git vero, quindi mockiamo qui subprocess.run."""

    def fake_run(*args, **kwargs):
        # _run() fa .strip() sull'intero stdout: una riga vuota in mezzo
        # sopravvive, mentre una vuota iniziale/finale verrebbe rimossa.
        return subprocess.CompletedProcess(
            args, returncode=0, stdout="abc123\trefs/tags/v1.0.0\n\ndef456\trefs/tags/v2.0.0", stderr=""
        )

    monkeypatch.setattr(git_ops.subprocess, "run", fake_run)
    tags = git_ops.list_remote_tags(tmp_path)
    assert tags == ["v1.0.0", "v2.0.0"]  # la riga vuota di mezzo (senza tab) e' stata ignorata


def test_fetch_tags_and_list_remote_tags(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True, capture_output=True)

    origin_checkout = tmp_path / "origin_checkout"
    subprocess.run(["git", "clone", str(remote), str(origin_checkout)], check=True, capture_output=True)
    (origin_checkout / "file.txt").write_text("v1\n", encoding="utf-8")
    _git(origin_checkout, "add", "file.txt")
    _git(origin_checkout, "commit", "-m", "initial")
    _git(origin_checkout, "tag", "v1.0.0")
    _git(origin_checkout, "push", "origin", "main", "--tags")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(remote), str(clone)], check=True, capture_output=True)

    remote_tags = git_ops.list_remote_tags(clone)
    assert remote_tags == ["v1.0.0"]

    # nuovo tag pushato dopo il clone: fetch_tags deve recuperarlo localmente
    _git(origin_checkout, "tag", "v2.0.0")
    _git(origin_checkout, "push", "origin", "--tags")

    result = git_ops.fetch_tags(clone)
    assert result.ok
    assert set(git_ops.list_local_tags(clone)) == {"v1.0.0", "v2.0.0"}
