#!/usr/bin/env bash
# DEPRECATO: la logica di backup/restore ora vive in packages/payroll-cli
# (payroll_cli/db.py), esposta come 'payroll db backup' / 'payroll db restore'
# (v. docs/CLI_REDESIGN_PROPOSAL.md, fase 2). Questo script resta solo come
# shim di compatibilita' per chi ha ancora l'abitudine digitata: delega alla
# CLI, nessuna logica duplicata qui.
#
# Procedura in due fasi invariata (v. README, "Aggiornamento major version di
# PostgreSQL"):
#   1) PRIMA di aggiornare il checkout, col vecchio db ancora in esecuzione:
#         scripts/upgrade-postgres.sh backup   (== payroll db backup)
#   2) DOPO aver aggiornato il checkout:
#         scripts/upgrade-postgres.sh restore  (== payroll db restore)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "ATTENZIONE: scripts/upgrade-postgres.sh e' deprecato — usa direttamente 'payroll db backup' / 'payroll db restore'." >&2

case "${1:-}" in
    backup)
        exec uv run payroll db backup
        ;;
    restore)
        if [[ -n "${2:-}" ]]; then
            exec uv run payroll db restore "$2"
        else
            exec uv run payroll db restore
        fi
        ;;
    *)
        echo "Uso: $0 backup | $0 restore [percorso-dump]" >&2
        exit 1
        ;;
esac
