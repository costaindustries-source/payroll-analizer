"""Backup/restore/migrate del servizio Postgres del progetto.

Porting 1:1 della logica di sicurezza di scripts/upgrade-postgres.sh (v.
docs/CLI_REDESIGN_PROPOSAL.md §8): idempotenza del restore (no-op se lo
schema di destinazione esiste gia'), verifica integrita' del dump (conteggio
'TABLE DATA' nel TOC), verifica dei conteggi righe post-restore contro uno
snapshot preso al momento del backup, e non cancella MAI un volume Postgres:
il volume precedente resta sempre sul disco come rete di sicurezza.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from payroll_cli import compose

_DUMP_GLOB = "payroll_*.dump"


class DbError(RuntimeError):
    pass


def _db_credentials(repo_root: Path) -> tuple[str, str]:
    user = compose.db_env(repo_root, "POSTGRES_USER")
    db_name = compose.db_env(repo_root, "POSTGRES_DB")
    if not user or not db_name:
        raise DbError("Impossibile leggere POSTGRES_USER/POSTGRES_DB dal container 'db' (e' in esecuzione?).")
    return user, db_name


def wait_db_healthy(repo_root: Path, tries: int = 30, interval_seconds: float = 2.0) -> None:
    for _ in range(tries):
        status = compose.ps_status(repo_root, "db") or ""
        if "healthy" in status.lower():
            return
        time.sleep(interval_seconds)
    raise DbError("Il servizio 'db' non risulta 'healthy' entro il timeout.")


@dataclass
class BackupResult:
    dump_path: Path
    counts_path: Path
    table_count: int


def backup(repo_root: Path, backups_dir: Path | None = None, log=print) -> BackupResult:
    backups_dir = backups_dir or (repo_root / "backups")

    log("== Avvio/verifica del servizio db (versione attualmente in uso) ==")
    compose.up_db(repo_root)
    wait_db_healthy(repo_root)

    user, db_name = _db_credentials(repo_root)

    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_path = backups_dir / f"payroll_{timestamp}.dump"

    log(f"== Dump di '{db_name}' (formato custom) ==")
    result = compose.exec_in_db_binary_stdout(
        repo_root, ["pg_dump", "-U", user, "-Fc", "-d", db_name], dump_path
    )
    if result.returncode != 0 or not dump_path.exists() or dump_path.stat().st_size == 0:
        dump_path.unlink(missing_ok=True)
        stderr = result.stderr.decode(errors="replace") if result.stderr else ""
        raise DbError(f"Dump vuoto o non creato: {stderr.strip()}")

    log("== Verifica integrita' del dump ==")
    compose.cp_to_db(repo_root, dump_path, "/tmp/verify.dump")
    toc = compose.exec_in_db(repo_root, ["pg_restore", "-l", "/tmp/verify.dump"])
    compose.exec_in_db(repo_root, ["rm", "-f", "/tmp/verify.dump"])
    table_count = sum(1 for line in toc.stdout.splitlines() if "TABLE DATA" in line)
    if table_count == 0:
        raise DbError("Il dump non contiene tabelle (TABLE DATA=0), qualcosa non va.")
    log(f"Dump verificato: {table_count} tabelle con dati.")

    log("== Snapshot conteggi righe (per verifica post-restore) ==")
    counts_query = (
        "SELECT table_name || ':' || (xpath('/row/c/text()', "
        "query_to_xml(format('SELECT count(*) AS c FROM %I', table_name), false, true, ''))"
        ")[1]::text FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name;"
    )
    counts = compose.exec_in_db(repo_root, ["psql", "-U", user, "-d", db_name, "-Atc", counts_query])
    counts_path = dump_path.with_suffix(dump_path.suffix + ".counts")
    counts_path.write_text(counts.stdout, encoding="utf-8")
    log(counts.stdout)

    log(f"\nBackup completato: {dump_path}")
    return BackupResult(dump_path=dump_path, counts_path=counts_path, table_count=table_count)


def _latest_dump(backups_dir: Path) -> Path | None:
    dumps = sorted(backups_dir.glob(_DUMP_GLOB), key=lambda p: p.stat().st_mtime)
    return dumps[-1] if dumps else None


@dataclass
class RestoreResult:
    performed: bool
    dump_path: Path | None
    mismatches: list[str]


def restore(repo_root: Path, dump_path: Path | None = None, backups_dir: Path | None = None, log=print) -> RestoreResult:
    backups_dir = backups_dir or (repo_root / "backups")

    log("== Avvio del servizio db (versione target da docker-compose.yml) ==")
    compose.up_db(repo_root)
    wait_db_healthy(repo_root)

    user, db_name = _db_credentials(repo_root)

    already_migrated = compose.exec_in_db(
        repo_root, ["psql", "-U", user, "-d", db_name, "-Atc", "SELECT to_regclass('public.alembic_version');"]
    ).stdout.strip()
    if already_migrated:
        log(
            "Il database di destinazione ha gia' uno schema (tabella alembic_version presente): "
            "nessun ripristino necessario."
        )
        return RestoreResult(performed=False, dump_path=None, mismatches=[])

    if dump_path is None:
        dump_path = _latest_dump(backups_dir)
        if dump_path is None:
            raise DbError(
                f"Destinazione vuota (nessuno schema) ma nessun dump trovato in {backups_dir}. "
                "Esegui prima 'payroll db backup' sull'ambiente con i dati vecchi."
            )
        log(f"Uso automatico del backup piu' recente: {dump_path}")
    if not dump_path.is_file():
        raise DbError(f"File non trovato: {dump_path}")

    log(f"== Ripristino di '{db_name}' da {dump_path} ==")
    compose.cp_to_db(repo_root, dump_path, "/tmp/restore.dump")
    restore_result = compose.exec_in_db(repo_root, ["pg_restore", "-U", user, "--no-owner", "-d", db_name, "/tmp/restore.dump"])
    compose.exec_in_db(repo_root, ["rm", "-f", "/tmp/restore.dump"])
    if restore_result.returncode != 0:
        raise DbError(f"pg_restore fallito: {restore_result.stderr.strip()}")

    counts_path = dump_path.with_suffix(dump_path.suffix + ".counts")
    mismatches: list[str] = []
    if counts_path.is_file():
        log("== Verifica conteggi righe post-restore ==")
        for line in counts_path.read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            table, expected = line.split(":", 1)
            actual = compose.exec_in_db(
                repo_root, ["psql", "-U", user, "-d", db_name, "-Atc", f'SELECT count(*) FROM "{table}";']
            ).stdout.strip()
            if actual != expected:
                mismatches.append(f"{table} atteso={expected} trovato={actual}")
        if mismatches:
            raise DbError(
                "Conteggi righe non corrispondenti dopo il restore, verifica a mano prima di continuare:\n"
                + "\n".join(mismatches)
                + "\nIl volume precedente NON e' stato toccato."
            )
        log("Conteggi righe verificati: OK.")
    else:
        log("Nota: nessun file .counts accanto al dump, salto la verifica dei conteggi.")

    return RestoreResult(performed=True, dump_path=dump_path, mismatches=mismatches)


def migrate(repo_root: Path, revision: str = "head") -> None:
    result = compose.run_in_app(repo_root, ["alembic", "upgrade", revision])
    if result.returncode != 0:
        raise DbError(f"alembic upgrade {revision} fallito: {result.stderr.strip()}")


def shell(repo_root: Path) -> int:
    user, db_name = _db_credentials(repo_root)
    return compose.exec_in_db_interactive(repo_root, ["psql", "-U", user, "-d", db_name])
