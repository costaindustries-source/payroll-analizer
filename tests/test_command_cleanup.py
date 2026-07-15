"""Test di payroll_cli.commands.cleanup.run(): report vs --apply, conferma
richiesta prima della rimozione, immagini dangling (mai rimosse), formattazione
dimensioni. payroll_cli.cleanup.scan/apply sono mockati (nessuna rimozione reale)."""

from __future__ import annotations

import typer

from payroll_cli import cleanup as cleanup_module
from payroll_cli.commands import cleanup as cleanup_cmd
from payroll_cli.context import Context


def _ctx(tmp_path):
    return Context(repo_root=tmp_path, machine=None)


def _report(**kwargs):
    return cleanup_module.CleanupReport(**kwargs)


def test_human_size_formatting_across_units():
    assert cleanup_cmd._human_size(500) == "500.0 B"
    assert cleanup_cmd._human_size(1536) == "1.5 KiB"
    assert cleanup_cmd._human_size(1024**2 * 3) == "3.0 MiB"
    assert cleanup_cmd._human_size(1024**3 * 2) == "2.0 GiB"
    assert cleanup_cmd._human_size(1024**4 * 2) == "2.0 TiB"


def test_nothing_to_clean_dry_run(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cleanup_module, "scan", lambda repo_root, machine: _report())
    cleanup_cmd.run(_ctx(tmp_path), apply_changes=False)
    out = capsys.readouterr().out
    assert "Niente da pulire su work/, logs/, backups/." in out
    assert "dry-run" not in out


def test_nothing_to_clean_with_apply_does_not_confirm(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cleanup_module, "scan", lambda repo_root, machine: _report())

    def fail_confirm(*a, **kw):
        raise AssertionError("confirm non dovrebbe essere chiamato quando non c'e' nulla da pulire")

    monkeypatch.setattr(typer, "confirm", fail_confirm)
    cleanup_cmd.run(_ctx(tmp_path), apply_changes=True)
    out = capsys.readouterr().out
    assert "Niente da pulire su work/, logs/, backups/." in out


def test_dry_run_lists_items_without_removing(monkeypatch, tmp_path, capsys):
    item = cleanup_module.CleanupItem(path=tmp_path / "work" / "leftover.tmp", reason="residuo", size_bytes=2048)
    monkeypatch.setattr(cleanup_module, "scan", lambda repo_root, machine: _report(work_residuals=[item]))
    cleanup_cmd.run(_ctx(tmp_path), apply_changes=False)
    out = capsys.readouterr().out
    assert "work/ (residui area temporanea OCR):" in out
    assert "leftover.tmp (2.0 KiB) — residuo" in out
    assert "dry-run: nessun file rimosso" in out


def test_apply_declined_prints_annullato_and_exits_0(monkeypatch, tmp_path, capsys):
    item = cleanup_module.CleanupItem(path=tmp_path / "logs" / "old.log", reason="oltre retention", size_bytes=10)
    monkeypatch.setattr(cleanup_module, "scan", lambda repo_root, machine: _report(old_logs=[item]))
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: False)
    applied = {"called": False}
    monkeypatch.setattr(cleanup_module, "apply", lambda report, log=print: applied.__setitem__("called", True))

    try:
        cleanup_cmd.run(_ctx(tmp_path), apply_changes=True)
        exit_code = 0
    except typer.Exit as exc:
        exit_code = exc.exit_code
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Annullato." in out
    assert applied["called"] is False


def test_apply_confirmed_calls_apply(monkeypatch, tmp_path, capsys):
    item = cleanup_module.CleanupItem(path=tmp_path / "backups" / "old.dump", reason="oltre i conservati", size_bytes=10)
    monkeypatch.setattr(cleanup_module, "scan", lambda repo_root, machine: _report(old_backups=[item]))
    monkeypatch.setattr(typer, "confirm", lambda *a, **kw: True)
    applied = {"called_with": None}

    def fake_apply(report, log=print):
        applied["called_with"] = report

    monkeypatch.setattr(cleanup_module, "apply", fake_apply)
    cleanup_cmd.run(_ctx(tmp_path), apply_changes=True)
    assert applied["called_with"] is not None
    assert len(applied["called_with"].filesystem_items) == 1


def test_dangling_images_reported_but_never_apply_target(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cleanup_module,
        "scan",
        lambda repo_root, machine: _report(dangling_images_count=3, dangling_images_size_bytes=1024 * 1024 * 5),
    )
    cleanup_cmd.run(_ctx(tmp_path), apply_changes=False)
    out = capsys.readouterr().out
    assert "Immagini Docker dangling sul sistema: 3 (5.0 MiB)" in out
    assert "mai rimosse da --apply" in out
    # Nessun item su filesystem: il dry-run non stampa la sezione, ma non crasha.
    assert "Niente da pulire su work/, logs/, backups/." in out
