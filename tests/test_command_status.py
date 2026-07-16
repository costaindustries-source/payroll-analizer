"""Test di payroll_cli.commands.status.run(): salute macchina, container,
documenti, backlog input/, spazio disco, hint di aggiornamento. compose/git_ops/
semver sono mockati; per lo spazio disco si usa il filesystem reale (tmp_path)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from payroll_cli.commands import status as status_cmd
from payroll_cli.context import Context, MachineConfig


def _ctx(tmp_path, machine=None):
    return Context(repo_root=tmp_path, machine=machine)


def _quiet_defaults(monkeypatch):
    """Valori neutri per non far esplodere run() quando un test si concentra
    su un'altra sezione: db non in esecuzione, nessun tag/aggiornamento,
    immagine 'app' non ancora buildata (niente avviso di staleness)."""
    monkeypatch.setattr(status_cmd, "ps_status", lambda repo_root, service: None)
    monkeypatch.setattr(status_cmd, "db_is_running", lambda repo_root: False)
    monkeypatch.setattr(status_cmd, "app_image_created_at", lambda repo_root: None)
    monkeypatch.setattr(status_cmd.git_ops, "exact_tag_on_head", lambda repo_root: None)
    monkeypatch.setattr(status_cmd.git_ops, "nearest_tag", lambda repo_root: None)
    monkeypatch.setattr(status_cmd.git_ops, "list_local_tags", lambda repo_root: [])
    monkeypatch.setattr(status_cmd.semver, "tags_after", lambda tags, baseline: [])


def test_machine_not_configured(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    status_cmd.run(_ctx(tmp_path, machine=None))
    out = capsys.readouterr().out
    assert "Macchina: non configurata — esegui 'payroll setup'" in out


def test_machine_configured(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    status_cmd.run(_ctx(tmp_path, machine=MachineConfig(name="host1", role="source")))
    out = capsys.readouterr().out
    assert "Macchina: host1 (ruolo: source)" in out


def test_container_not_running(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Container db:  non in esecuzione" in out


def test_container_running_status_shown(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    monkeypatch.setattr(status_cmd, "ps_status", lambda repo_root, service: "Up 3 hours (healthy)")
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Container db:  Up 3 hours (healthy)" in out


def test_stale_image_warning_shown_when_source_newer_than_build(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    source_dir = tmp_path / "packages" / "payroll-ingest" / "src"
    source_dir.mkdir(parents=True)
    (source_dir / "mod.py").write_bytes(b"x")
    image_created = datetime.now(timezone.utc) - timedelta(hours=1)
    monkeypatch.setattr(status_cmd, "app_image_created_at", lambda repo_root: image_created)
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Attenzione: codice in packages/ modificato dopo l'ultima build" in out


def test_stale_image_warning_absent_when_build_newer_than_source(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    source_dir = tmp_path / "packages" / "payroll-ingest" / "src"
    source_dir.mkdir(parents=True)
    (source_dir / "mod.py").write_bytes(b"x")
    image_created = datetime.now(timezone.utc) + timedelta(hours=1)
    monkeypatch.setattr(status_cmd, "app_image_created_at", lambda repo_root: image_created)
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Attenzione: codice in packages/" not in out


def test_stale_image_warning_absent_when_image_not_built_yet(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)  # app_image_created_at -> None di default
    source_dir = tmp_path / "packages" / "payroll-ingest" / "src"
    source_dir.mkdir(parents=True)
    (source_dir / "mod.py").write_bytes(b"x")
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Attenzione: codice in packages/" not in out


def test_stale_image_warning_absent_when_no_source_dirs(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    monkeypatch.setattr(
        status_cmd, "app_image_created_at", lambda repo_root: datetime.now(timezone.utc) - timedelta(hours=1)
    )
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Attenzione: codice in packages/" not in out


def test_documents_unknown_when_db_not_running(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Documenti: sconosciuto (db non in esecuzione)" in out


def test_documents_query_failed_with_stderr(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    monkeypatch.setattr(status_cmd, "db_is_running", lambda repo_root: True)
    monkeypatch.setattr(status_cmd, "db_env", lambda repo_root, var: "payroll")
    monkeypatch.setattr(
        status_cmd, "exec_in_db", lambda repo_root, args: SimpleNamespace(returncode=1, stdout="", stderr="boom")
    )
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Documenti: query fallita (boom)" in out


def test_documents_query_failed_without_stderr_uses_fallback(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    monkeypatch.setattr(status_cmd, "db_is_running", lambda repo_root: True)
    monkeypatch.setattr(status_cmd, "db_env", lambda repo_root, var: "payroll")
    monkeypatch.setattr(
        status_cmd, "exec_in_db", lambda repo_root, args: SimpleNamespace(returncode=1, stdout="", stderr="")
    )
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Documenti: query fallita (schema assente?)" in out


def test_documents_empty_database(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    monkeypatch.setattr(status_cmd, "db_is_running", lambda repo_root: True)
    monkeypatch.setattr(status_cmd, "db_env", lambda repo_root, var: "payroll")
    monkeypatch.setattr(
        status_cmd, "exec_in_db", lambda repo_root, args: SimpleNamespace(returncode=0, stdout="  \n", stderr="")
    )
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Documenti: 0 (database vuoto)" in out


def test_documents_grouped_by_status(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    monkeypatch.setattr(status_cmd, "db_is_running", lambda repo_root: True)
    monkeypatch.setattr(status_cmd, "db_env", lambda repo_root, var: "payroll")
    monkeypatch.setattr(
        status_cmd,
        "exec_in_db",
        lambda repo_root, args: SimpleNamespace(returncode=0, stdout="processed|3\nfailed|1\n", stderr=""),
    )
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Documenti per stato:" in out
    assert "  processed: 3" in out
    assert "  failed: 1" in out


def test_input_backlog_missing_directory_prints_nothing(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "In attesa" not in out


def test_input_backlog_counts_only_pdf_case_insensitive_and_skips_zone_identifier(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"x")
    (input_dir / "b.PDF").write_bytes(b"x")
    (input_dir / "note.txt").write_bytes(b"x")
    (input_dir / "a.pdf:Zone.Identifier").write_bytes(b"x")
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "In attesa in input/: 2 file" in out


def test_disk_usage_and_backups_reported(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    (backups_dir / "payroll_20260101T000000Z.dump").write_bytes(b"x" * 1024)
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Spazio disco:" in out
    assert "GiB liberi su" in out
    assert "Backup in backups/: 1 file" in out


def test_disk_usage_without_backups_dir_skips_backup_line(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Backup in backups/" not in out


def test_update_hint_up_to_date(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    monkeypatch.setattr(status_cmd.git_ops, "exact_tag_on_head", lambda repo_root: "v1.0.0")
    monkeypatch.setattr(status_cmd.git_ops, "list_local_tags", lambda repo_root: ["v1.0.0"])
    monkeypatch.setattr(status_cmd.semver, "tags_after", lambda tags, baseline: [])
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Aggiornamenti: nessun tag locale piu' recente di v1.0.0" in out


def test_update_hint_newer_tags_available(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    monkeypatch.setattr(status_cmd.git_ops, "exact_tag_on_head", lambda repo_root: "v1.0.0")
    monkeypatch.setattr(status_cmd.git_ops, "list_local_tags", lambda repo_root: ["v1.0.0", "v1.1.0", "v1.2.0"])
    monkeypatch.setattr(status_cmd.semver, "tags_after", lambda tags, baseline: ["v1.1.0", "v1.2.0"])
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Aggiornamenti: 2 tag locali piu' recenti di v1.0.0 (es. v1.2.0)" in out


def test_update_hint_no_current_tag_at_all(monkeypatch, tmp_path, capsys):
    _quiet_defaults(monkeypatch)
    monkeypatch.setattr(status_cmd.git_ops, "exact_tag_on_head", lambda repo_root: None)
    monkeypatch.setattr(status_cmd.git_ops, "nearest_tag", lambda repo_root: None)
    monkeypatch.setattr(status_cmd.git_ops, "list_local_tags", lambda repo_root: [])
    monkeypatch.setattr(status_cmd.semver, "tags_after", lambda tags, baseline: [])
    status_cmd.run(_ctx(tmp_path))
    out = capsys.readouterr().out
    assert "Aggiornamenti: nessun tag locale piu' recente di (nessuno)" in out
