# payroll-ingest

Batch di ingestion cedolini PDF -> database PostgreSQL.

Guide complete: [`INSTALL-INFO.md`](INSTALL-INFO.md) (installazione da zero),
[`docs/RELEASE_PROCESS.md`](docs/RELEASE_PROCESS.md) (rilascio Ubuntu -> GitHub
-> Debian), [`PIANO_TECNICO.md`](PIANO_TECNICO.md) (piano tecnico),
[`docs/CLI_REDESIGN_PROPOSAL.md`](docs/CLI_REDESIGN_PROPOSAL.md) (piano di
reingegnerizzazione della CLI operativa, in corso). Quanto segue è un
riferimento rapido ai comandi usati più spesso.

## Struttura del repo (workspace uv)

Il progetto è un workspace uv con due pacchetti in `packages/`:

- `payroll-ingest` — motore di dominio (parsing, DB, CLI `payroll-ingest`),
  installato **solo dentro il container** `app`. Invariato nel comportamento.
- `payroll-cli` — CLI operativa **host** (`payroll`), pensata per girare sulla
  macchina che ospita Docker, non nel container. Copre oggi `version`,
  `status`, `update check`, `help`; il resto del ciclo di vita (`setup`,
  `update apply`, `db backup/restore`, `cleanup`, `release`) è pianificato in
  `docs/CLI_REDESIGN_PROPOSAL.md` e non ancora implementato — per ora restano
  in vigore `scripts/release.sh` e `scripts/upgrade-postgres.sh` (vedi le
  sezioni più sotto).

```bash
uv sync --all-packages                    # installa entrambi i pacchetti in .venv/
uv run payroll --help                     # CLI operativa (host)
uv run payroll version                    # tag/commit repo, alembic current/head, versione Postgres
uv run payroll status                     # container, documenti per stato, input/ in coda, disco
uv run payroll update check                # confronta il tag locale con l'ultimo pubblicato su GitHub
uv run payroll help update check           # help di un sottocomando annidato
```

`payroll` risale da solo alla radice del repo risalendo dalla cwd (cerca
`docker-compose.yml` + `packages/payroll-cli/pyproject.toml`); se lanciato da
fuori il checkout, imposta `PAYROLL_REPO_ROOT=/percorso/del/repo`.

## Setup iniziale (una tantum)

```bash
docker compose build                          # immagine app (Python + Tesseract + dipendenze)
docker compose up -d db                       # avvia Postgres e attende sia pronto
docker compose run --rm app alembic upgrade head   # crea le tabelle
```

## Uso quotidiano

```bash
cp /percorso/dei/cedolini/*.pdf input/         # PDF da elaborare
docker compose run --rm app payroll-ingest process   # elabora tutto input/
docker compose run --rm app payroll-ingest export    # export completo -> export/<timestamp>_<schema>/
```

`process`: hash SHA-256 (skip dei duplicati già caricati) -> classificazione
testuale/scansionato (OCR solo se serve) -> riconoscimento template + mapping
-> salvataggio in una transazione per documento -> spostamento in
`processed/<anno>/<mese>/` o `error/<file>.error.json` (un errore non blocca
gli altri) -> log in `logs/batch_<run_id>.log` e `logs/run_<run_id>.json`.

### Ricaricare un documento già processato

Un documento con status `PROCESSED`/`PROCESSED_WITH_ANOMALIES` viene
riconosciuto come duplicato (stesso sha256) e scartato senza essere
rielaborato, anche dopo un fix del parser: va prima cancellato dal database.
Solo `NEEDS_REVIEW` viene rielaborato in automatico da `process`.

```bash
docker compose run --rm app payroll-ingest delete-document --filename 07.pdf   # o --sha256/--id se il nome e' ambiguo
cp processed/2025/07/07.pdf input/    # ricopia il PDF (delete-document non tocca il file su disco)
docker compose run --rm app payroll-ingest process
```

### Verificare la copertura per annualita'

```bash
docker compose run --rm app payroll-ingest check-years
```

Per ogni anno mostra `caricati/totale` (caricato = status `PROCESSED`, zero
anomalie di qualunque severita') e, per ogni documento non al 100%, il file e
l'elenco delle anomalie che lo riguardano (comprese quelle solo `info`, es.
`righe_non_mappate`). I documenti il cui periodo non e' stato riconosciuto
(nessun anno attribuibile) sono elencati a parte. Exit code 1 se esiste almeno
un documento non completamente caricato.

## Gestione servizi Docker

```bash
docker compose stop        # ferma i container (dati Postgres intatti)
docker compose up -d db     # riavvia solo il database
docker compose down         # ferma e rimuove i container (volume dati NON toccato)
```

## Database

```bash
docker compose exec db psql -U payroll -d payroll                              # shell psql
docker compose exec db psql -U payroll -d payroll -c "select count(*) from payroll_document;"
docker compose exec db pg_dump -U payroll payroll > backup.sql                 # backup rapido
```

Client esterno (DBeaver/SQLTools): `localhost:5432`, utente/password/db `payroll`.

## Aggiornamento major version di PostgreSQL

`docker-compose.yml` e' identico e versionato su ogni ambiente: un bump di
major version dell'immagine Postgres (es. 16 -> 17) cambia anche il nome del
volume dati, quindi va migrato su **ogni** macchina che aggiorna il checkout,
non solo su quella dove il bump e' stato deciso. Procedura in due fasi:

```bash
scripts/upgrade-postgres.sh backup     # PRIMA di aggiornare il checkout, col vecchio db in esecuzione
git pull                               # (o checkout del tag) -> docker-compose.yml ora punta alla nuova image/volume
scripts/upgrade-postgres.sh restore    # DOPO, ripristina i dati nel nuovo volume
```

`restore` senza argomenti usa automaticamente il backup piu' recente in
`backups/` e non fa nulla (idempotente) se il volume di destinazione ha gia'
uno schema. Il volume precedente non viene mai cancellato automaticamente:
resta come rete di sicurezza, va rimosso a mano (`docker volume ls` / `docker
volume rm`) quando si e' certi che la migrazione sia andata a buon fine.

## Migrations (Alembic)

```bash
docker compose run --rm app alembic upgrade head       # applica tutte le migration
docker compose run --rm app alembic revision -m 'descrizione'   # nuova migration
docker compose run --rm app alembic upgrade +1          # avanza di una
docker compose run --rm app alembic downgrade -1         # torna indietro di una
```

## Test di regressione (smoke test)

Gira sui 6 cedolini reali di riferimento in `docs/payroll-test/` (mai in git)
dopo ogni modifica a `templates/zucchetti.py` o `extraction.py`:

```bash
.venv/bin/python scripts/smoke_test.py                          # locale (Ubuntu, venv host)
docker compose run --rm app python scripts/smoke_test.py --samples-dir /data/docs/payroll-test   # dentro il container
```

## Sviluppo locale senza Docker (Ubuntu, gestito da `uv`)

```bash
uv sync                                  # crea/aggiorna .venv da uv.lock
cp .env.example .env                     # DATABASE_URL -> localhost:5432 (serve comunque `docker compose up -d db`)
uv run payroll-ingest process            # o: source .venv/bin/activate && payroll-ingest process
uv run python scripts/smoke_test.py
```

## Rilascio (Ubuntu -> GitHub -> Debian prod)

```bash
scripts/release.sh vX.Y.Z          # rilascio completo: smoke test, tag+push, deploy Debian (con gate di conferma), smoke test post-deploy, log
scripts/release.sh --deploy vX.Y.Z # riprende solo il deploy su Debian di un tag già pushato
scripts/release.sh --rollback vX.Y.Z   # riporta Debian a un tag precedente
```

SemVer: **patch** (`v0.1.x`) fix senza cambio schema, **minor** (`v0.2.0`)
nuove funzionalità, **major** (`v1.0.0`) cambio schema DB non retrocompatibile.

## Risoluzione problemi comuni

Vedi la sezione "Risoluzione problemi noti" in [`INSTALL-INFO.md`](INSTALL-INFO.md#7-risoluzione-problemi-noti)
(plugin Compose mancante, permessi Docker, file di proprietà `root`, credential
helper di Docker Desktop residuo).
