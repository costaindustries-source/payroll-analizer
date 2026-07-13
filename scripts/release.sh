#!/usr/bin/env bash
# Processo di rilascio payroll-analizer: Ubuntu (dev) -> GitHub -> Debian (prod reale).
#
# Modello (v. docs/RELEASE_PROCESS.md):
#   - GitHub (origin) e' la fonte di verita' del codice.
#   - Debian (~/app/payroll-analizer) e' l'unico ambiente che esegue realmente
#     il batch: va sempre aggiornato a un TAG annotato, mai a un commit sciolto
#     (stesso principio "deploy da tag" usato in REVO per bp-revo-parametric).
#   - Ogni release e' preceduta da smoke test locale e seguita da smoke test
#     sull'immagine Debian appena rebuildata, prima di considerarla riuscita.
#
# Uso:
#   scripts/release.sh <versione>          # es: scripts/release.sh v0.1.1
#   scripts/release.sh --rollback <tag>    # riporta Debian a un tag precedente
#
set -euo pipefail

WSL=/mnt/c/Windows/System32/wsl.exe
DEBIAN_DISTRO=Debian
DEBIAN_REPO=/home/matteocostantini/app/payroll-analizer
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE_LOG="$REPO_ROOT/RELEASE_LOG.md"

on_debian() {
    "$WSL" -d "$DEBIAN_DISTRO" -- bash -lc "cd $DEBIAN_REPO && $1"
}

confirm() {
    read -r -p "$1 [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

cmd_rollback() {
    local target_tag="$1"
    echo "== Rollback Debian al tag $target_tag =="
    on_debian "git fetch --tags -q && git checkout -q $target_tag"
    if ! confirm "Rebuild immagine Docker su Debian per il tag $target_tag?"; then
        echo "Rollback interrotto: codice checked out, immagine non ricostruita."
        exit 1
    fi
    on_debian "docker compose build app"
    echo "Rollback a $target_tag completato. Verifica manualmente con smoke test se necessario."
}

cmd_release() {
    local version="$1"

    echo "== 1/6 Preflight: working tree pulito, su main =="
    if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
        echo "ERRORE: working tree non pulito. Committa o stash prima di rilasciare." >&2
        exit 1
    fi
    local branch
    branch="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
    if [[ "$branch" != "main" ]]; then
        echo "ERRORE: sei su '$branch', non su 'main'." >&2
        exit 1
    fi

    echo "== 2/6 Smoke test locale (Ubuntu, venv host) =="
    "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/scripts/smoke_test.py"

    echo "== 3/6 Tag e push su GitHub =="
    if git -C "$REPO_ROOT" rev-parse "$version" >/dev/null 2>&1; then
        echo "ERRORE: il tag $version esiste gia'." >&2
        exit 1
    fi
    read -r -p "Messaggio di release per $version: " release_msg
    git -C "$REPO_ROOT" tag -a "$version" -m "$release_msg"
    git -C "$REPO_ROOT" push origin main
    git -C "$REPO_ROOT" push origin "$version"

    echo "== 4/6 Deploy su Debian: gate di conferma =="
    if ! confirm "Portare Debian (ambiente REALE) al tag $version e ricostruire l'immagine Docker?"; then
        echo "Tag $version pushato su GitHub, ma NON deployato su Debian (fermato su richiesta)."
        echo "Puoi rilanciare in seguito con: git fetch --tags && git checkout $version && docker compose build app (su Debian)."
        exit 0
    fi
    local previous_tag
    previous_tag="$(on_debian "git describe --tags --abbrev=0" || echo "")"
    # Garantisce l'override di config specifica per ambiente PRIMA del checkout
    # (idempotente: non tocca nulla se il file esiste gia'): senza, un checkout
    # che tocca docker-compose.yml lascerebbe una finestra con la porta host
    # del DB tornata al default versionato, invece di quella reale di questo
    # ambiente (v. docs/RELEASE_PROCESS.md, sezione "Configurazione specifica
    # per ambiente").
    on_debian "test -f docker-compose.override.yml || printf 'services:\n  db:\n    ports:\n      - \\\"127.0.0.1:5433:5432\\\"\n' > docker-compose.override.yml"
    on_debian "git fetch --tags -q && git checkout -q $version"
    on_debian "docker compose build app"

    echo "== 5/6 Smoke test sull'immagine Debian appena costruita =="
    if ! on_debian "docker compose run --rm -v \"\$(pwd)/scripts:/smoke:ro\" app python /smoke/smoke_test.py --samples-dir /data/docs/payroll-test"; then
        echo "SMOKE TEST FALLITO su Debian." >&2
        if [[ -n "$previous_tag" ]] && confirm "Rollback automatico al tag precedente ($previous_tag)?"; then
            on_debian "git checkout -q $previous_tag && docker compose build app"
            echo "Rollback a $previous_tag eseguito."
        fi
        exit 1
    fi

    echo "== 6/6 Log della release =="
    {
        echo ""
        echo "## $version — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo ""
        echo "$release_msg"
        echo ""
        echo "- Tag precedente su Debian: ${previous_tag:-nessuno}"
        echo "- Smoke test post-deploy: OK"
    } >> "$RELEASE_LOG"
    git -C "$REPO_ROOT" add "$RELEASE_LOG"
    git -C "$REPO_ROOT" commit -m "docs: log rilascio $version"
    git -C "$REPO_ROOT" push origin main

    echo ""
    echo "Release $version completata: GitHub aggiornato, Debian deployato e verificato."
}

case "${1:-}" in
    --rollback)
        [[ -n "${2:-}" ]] || { echo "Uso: $0 --rollback <tag>" >&2; exit 1; }
        cmd_rollback "$2"
        ;;
    "" )
        echo "Uso: $0 <versione es. v0.1.1> | $0 --rollback <tag>" >&2
        exit 1
        ;;
    *)
        cmd_release "$1"
        ;;
esac
