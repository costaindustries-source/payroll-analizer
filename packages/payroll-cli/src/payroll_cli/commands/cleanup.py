from __future__ import annotations

import typer

from payroll_cli import cleanup as cleanup_module
from payroll_cli.context import Context


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def run(app_ctx: Context, apply_changes: bool) -> None:
    report = cleanup_module.scan(app_ctx.repo_root, app_ctx.machine)

    sections = [
        ("work/ (residui area temporanea OCR)", report.work_residuals),
        ("logs/ (oltre retention)", report.old_logs),
        ("backups/ (oltre il numero da conservare)", report.old_backups),
    ]

    found_filesystem_items = False
    for title, items in sections:
        if not items:
            continue
        found_filesystem_items = True
        typer.echo(f"\n{title}:")
        for item in items:
            typer.echo(f"  {item.path} ({_human_size(item.size_bytes)}) — {item.reason}")

    if report.dangling_images_count:
        typer.echo(
            f"\nImmagini Docker dangling sul sistema: {report.dangling_images_count} "
            f"({_human_size(report.dangling_images_size_bytes)}) — NON associate in modo "
            "affidabile a questo progetto (Docker perde il tag una volta superate), mai "
            "rimosse da --apply. Rimozione manuale: docker image prune"
        )

    if not found_filesystem_items:
        typer.echo("\nNiente da pulire su work/, logs/, backups/.")
        if not apply_changes:
            return

    if not apply_changes:
        typer.echo("\n(dry-run: nessun file rimosso. Rilancia con --apply per rimuovere gli item sopra elencati.)")
        return

    if not found_filesystem_items:
        return

    total = len(report.filesystem_items)
    if not typer.confirm(f"\nRimuovere {total} elementi?"):
        typer.echo("Annullato.")
        raise typer.Exit(code=0)

    cleanup_module.apply(report, log=typer.echo)
