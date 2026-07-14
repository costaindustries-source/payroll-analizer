#!/usr/bin/env bash
# Migrazione dati per un cambio di *major version* di Postgres in docker-compose.yml.
#
# docker-compose.yml e' identico e versionato su ogni ambiente (v.
# docs/RELEASE_PROCESS.md): un bump di major version li' dentro cambia anche il
# nome del volume dati (Postgres non legge un data directory scritto da una
# major precedente), quindi va migrato su OGNI macchina che aggiorna il
# checkout, non solo su quella dove il bump e' stato deciso.
#
# Procedura in due fasi, da eseguire su ciascuna macchina:
#   1) PRIMA di aggiornare il checkout (git checkout/pull del tag con il nuovo
#      docker-compose.yml), col vecchio db ancora in esecuzione:
#         scripts/upgrade-postgres.sh backup
#   2) DOPO aver aggiornato il checkout (docker-compose.yml ora punta alla
#      nuova image/volume):
#         scripts/upgrade-postgres.sh restore
#
# 'restore' non fa nulla (exit 0) se il volume di destinazione ha gia' uno
# schema (tabella alembic_version presente): rende lo script idempotente e
# sicuro da rilanciare per errore, e permette di saltare 'backup' quando il
# bump non cambia il nome del volume (patch/minor Postgres, stesso data dir).
#
# Il vecchio volume NON viene mai cancellato da questo script: resta sul disco
# come rete di sicurezza (v. `docker volume ls`), va rimosso a mano quando si
# e' certi che la migrazione e' andata bene.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$REPO_ROOT/backups"
cd "$REPO_ROOT"

wait_db_healthy() {
    local tries=30
    while (( tries > 0 )); do
        if docker compose ps db --format '{{.Status}}' 2>/dev/null | grep -q healthy; then
            return 0
        fi
        sleep 2
        (( tries-- ))
    done
    echo "ERRORE: il servizio db non risulta 'healthy' entro il timeout." >&2
    return 1
}

db_env() {
    # Legge le credenziali direttamente dal container in esecuzione, cosi' lo
    # script resta valido anche se un domani venissero parametrizzate via .env
    # invece di essere letterali in docker-compose.yml.
    docker compose exec -T db printenv "$1"
}

cmd_backup() {
    echo "== Avvio/verifica del servizio db (versione attualmente in uso) =="
    docker compose up -d db
    wait_db_healthy

    local user db_name
    user="$(db_env POSTGRES_USER)"
    db_name="$(db_env POSTGRES_DB)"

    mkdir -p "$BACKUP_DIR"
    local timestamp file
    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    file="$BACKUP_DIR/payroll_${timestamp}.dump"

    echo "== Dump di '$db_name' (formato custom) =="
    docker compose exec -T db pg_dump -U "$user" -Fc -d "$db_name" > "$file"

    if [[ ! -s "$file" ]]; then
        echo "ERRORE: dump vuoto o non creato ($file)." >&2
        rm -f "$file"
        exit 1
    fi

    echo "== Verifica integrita' del dump =="
    docker compose cp "$file" db:/tmp/verify.dump
    local toc_entries
    toc_entries="$(docker compose exec -T db pg_restore -l /tmp/verify.dump | grep -c 'TABLE DATA')"
    docker compose exec -T db rm -f /tmp/verify.dump
    if (( toc_entries == 0 )); then
        echo "ERRORE: il dump non contiene tabelle (TABLE DATA=0), qualcosa non va." >&2
        exit 1
    fi
    echo "Dump verificato: $toc_entries tabelle con dati."

    echo "== Snapshot conteggi righe (per verifica post-restore) =="
    local counts_file="${file}.counts"
    docker compose exec -T db psql -U "$user" -d "$db_name" -Atc "
        SELECT table_name || ':' || (xpath('/row/c/text()',
            query_to_xml(format('SELECT count(*) AS c FROM %I', table_name), false, true, '')))[1]::text
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
    " > "$counts_file"
    cat "$counts_file"

    echo ""
    echo "Backup completato: $file"
    echo "Ora aggiorna il checkout (git checkout/pull del tag con il nuovo docker-compose.yml),"
    echo "poi esegui: scripts/upgrade-postgres.sh restore"
}

cmd_restore() {
    local file="${1:-}"

    echo "== Avvio del servizio db (versione target da docker-compose.yml) =="
    docker compose up -d db
    wait_db_healthy

    local user db_name
    user="$(db_env POSTGRES_USER)"
    db_name="$(db_env POSTGRES_DB)"

    local already_migrated
    already_migrated="$(docker compose exec -T db psql -U "$user" -d "$db_name" -Atc "SELECT to_regclass('public.alembic_version');" | tr -d '[:space:]')"
    if [[ -n "$already_migrated" ]]; then
        echo "Il database di destinazione ha gia' uno schema (tabella alembic_version presente):"
        echo "nessun ripristino necessario (probabilmente gia' migrato, o il bump non ha cambiato volume)."
        exit 0
    fi

    if [[ -z "$file" ]]; then
        file="$(ls -t "$BACKUP_DIR"/payroll_*.dump 2>/dev/null | head -1 || true)"
        if [[ -z "$file" ]]; then
            echo "ERRORE: destinazione vuota (nessuno schema) ma nessun dump trovato in $BACKUP_DIR." >&2
            echo "Esegui prima 'scripts/upgrade-postgres.sh backup' sull'ambiente con i dati vecchi." >&2
            exit 1
        fi
        echo "Uso automatico del backup piu' recente: $file"
    fi
    if [[ ! -f "$file" ]]; then
        echo "ERRORE: file non trovato: $file" >&2
        exit 1
    fi

    echo "== Ripristino di '$db_name' da $file =="
    docker compose cp "$file" db:/tmp/restore.dump
    docker compose exec -T db pg_restore -U "$user" --no-owner -d "$db_name" /tmp/restore.dump
    docker compose exec -T db rm -f /tmp/restore.dump

    local counts_file="${file}.counts"
    if [[ -f "$counts_file" ]]; then
        echo "== Verifica conteggi righe post-restore =="
        local mismatch=0
        while IFS=: read -r table expected; do
            [[ -z "$table" ]] && continue
            local actual
            actual="$(docker compose exec -T db psql -U "$user" -d "$db_name" -Atc "SELECT count(*) FROM \"$table\";")"
            if [[ "$actual" != "$expected" ]]; then
                echo "MISMATCH: $table atteso=$expected trovato=$actual" >&2
                mismatch=1
            fi
        done < "$counts_file"
        if (( mismatch != 0 )); then
            echo "ERRORE: conteggi righe non corrispondenti dopo il restore, verifica a mano prima di continuare." >&2
            echo "Il volume precedente NON e' stato toccato (v. docker volume ls)." >&2
            exit 1
        fi
        echo "Conteggi righe verificati: OK."
    else
        echo "Nota: nessun file .counts accanto al dump, salto la verifica dei conteggi."
    fi

    echo ""
    echo "Restore completato su $(docker compose exec -T db psql -U "$user" -d "$db_name" -Atc 'SELECT version();')."
    echo "Il volume precedente resta sul disco come backup: rimuovilo a mano (docker volume rm ...) quando sei sicuro."
}

case "${1:-}" in
    backup)
        cmd_backup
        ;;
    restore)
        cmd_restore "${2:-}"
        ;;
    *)
        echo "Uso: $0 backup | $0 restore [percorso-dump]" >&2
        exit 1
        ;;
esac
