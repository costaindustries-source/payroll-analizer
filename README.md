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
  `status`, `update check/apply`, `rollback`, `help`, `setup`,
  `db backup/restore/migrate/shell`, `cleanup`, `release new/list`. Il modello
  è **pull**: `release new` (solo sulla macchina `role=source`, v. `payroll
  setup`) pubblica soltanto un tag su GitHub — non deploya nulla — e ogni
  macchina installata si aggiorna da sola con `update apply`.
  `scripts/release.sh --deploy`/`--rollback` restano per ora l'unico modo per
  promuovere davvero il codice su Debian (v. sezione dedicata più sotto):
  finché quella parte del flusso non è stata validata su un aggiornamento
  reale con `payroll update apply`, non va rimossa. `scripts/upgrade-postgres.sh`
  è deprecato: e' un thin shim che delega a `payroll db backup`/`payroll db
  restore` (stessa interfaccia, nessuna logica duplicata).

```bash
uv sync --all-packages                    # installa entrambi i pacchetti in .venv/
uv run payroll --help                     # CLI operativa (host)
uv run payroll version                    # tag/commit repo, alembic current/head, versione Postgres
uv run payroll status                     # container, documenti per stato, input/ in coda, disco
uv run payroll update check                # confronta il tag locale con l'ultimo pubblicato su GitHub
uv run payroll update apply [--to vX.Y.Z]  # checkout al tag piu' recente (o --to), backup automatico se
                                            # cambia il volume Postgres, poi build/restore/migration/smoke test
uv run payroll rollback vX.Y.Z             # torna a un tag precedente: checkout + rebuild (non tocca dati)
uv run payroll help update check           # help di un sottocomando annidato
uv run payroll setup --check               # solo verifica prerequisiti (docker/compose/git/uv/disco/UID)
uv run payroll setup --bootstrap           # wizard configurazione + build/avvio/migration/smoke test
uv run payroll db backup                   # dump verificato + snapshot conteggi righe (backups/)
uv run payroll db restore [dump]           # idempotente: no-op se lo schema esiste gia'
uv run payroll db migrate [revision]       # alembic upgrade (default: head)
uv run payroll db shell                    # psql interattivo nel container db
uv run payroll cleanup                     # report (dry-run) di work/logs/backups oltre soglia
uv run payroll cleanup --apply             # rimuove gli item elencati (con conferma)
uv run payroll release list                # storia dei tag pubblicati (fetch + confronto con origin)
uv run payroll release new vX.Y.Z [-m msg] # solo role=source: preflight+smoke test+CHANGELOG+tag+push
```

`payroll` risale da solo alla radice del repo risalendo dalla cwd (cerca
`docker-compose.yml` + `packages/payroll-cli/pyproject.toml`); se lanciato da
fuori il checkout, imposta `PAYROLL_REPO_ROOT=/percorso/del/repo`.
`payroll setup` scrive `payroll.local.toml` (non versionato: nome macchina,
ruolo `source`/`node`, porta DB, retention log, backup da conservare) e
rigenera `docker-compose.override.yml` solo se la porta scelta differisce dal
default 5432 (non sovrascrive mai un override esistente).

`payroll update apply` blocca se il working tree non e' pulito, rifiuta di
procedere se sei gia' sull'ultimo tag, e chiede sempre conferma esplicita
prima del checkout. Se il bump cambia il nome del volume dati Postgres (v.
"Aggiornamento major version di PostgreSQL" più sotto) esegue da solo un
backup prima del checkout — non serve più ricordarsi l'ordine backup ->
checkout -> restore a mano. Dopo il checkout, il resto della sequenza
(build immagine, avvio db, restore, migration, smoke test) gira col codice
del *nuovo* tag appena installato, non con quello del processo che ha
avviato l'aggiornamento. Se lo smoke test fallisce, propone il rollback
automatico al tag precedente (`payroll rollback`, che fa solo checkout +
rebuild immagine: non tocca mai dati o volumi). Traccia ogni esito in
`logs/updates.log` (locale, non versionato).

`payroll release new` e' riservato alla macchina configurata con `role=source`
(Ubuntu/dev). Preflight (branch `main`, working tree pulito, tag non
esistente) -> smoke test locale **obbligatorio** sui campioni di
`docs/payroll-test/` (a differenza di `setup`/`update apply`, qui non viene
mai saltato) -> promuove la sezione `## [Non rilasciato]` di `CHANGELOG.md` a
`## [vX.Y.Z] - <data>` (lasciandone una vuota in cima per il prossimo giro) e
la committa -> chiede conferma esplicita -> crea il tag annotato e pusha
`main` + il tag. **Non deploya nulla**: la promozione sulle macchine resta
compito di ciascun nodo con `payroll update apply`.

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
uv run payroll db shell                                                         # shell psql (via CLI)
docker compose exec db psql -U payroll -d payroll -c "select count(*) from payroll_document;"
uv run payroll db backup                                                        # backup verificato (via CLI)
```

Client esterno (DBeaver/SQLTools): `localhost:5432`, utente/password/db `payroll`.

## Aggiornamento major version di PostgreSQL

`docker-compose.yml` e' identico e versionato su ogni ambiente: un bump di
major version dell'immagine Postgres (es. 16 -> 17) cambia anche il nome del
volume dati, quindi va migrato su **ogni** macchina che aggiorna il checkout,
non solo su quella dove il bump e' stato deciso. Procedura in due fasi:

```bash
uv run payroll db backup     # PRIMA di aggiornare il checkout, col vecchio db in esecuzione
git pull                     # (o checkout del tag) -> docker-compose.yml ora punta alla nuova image/volume
uv run payroll db restore    # DOPO, ripristina i dati nel nuovo volume
```

`restore` senza argomenti usa automaticamente il backup piu' recente in
`backups/` e non fa nulla (idempotente) se il volume di destinazione ha gia'
uno schema. Il volume precedente non viene mai cancellato automaticamente:
resta come rete di sicurezza, va rimosso a mano (`docker volume ls` / `docker
volume rm`) quando si e' certi che la migrazione sia andata a buon fine.

`scripts/upgrade-postgres.sh backup|restore` resta disponibile come alias
deprecato (delega a `payroll db backup`/`payroll db restore`, stessa
interfaccia) per chi ha ancora l'abitudine digitata.

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

Due comandi coesistono, con responsabilità diverse (v. `docs/CLI_REDESIGN_PROPOSAL.md`):

```bash
uv run payroll release new vX.Y.Z [-m msg]   # pubblica il tag su GitHub (solo su Ubuntu, role=source). Nessun deploy.
uv run payroll update apply                   # su OGNI macchina (Debian inclusa): si aggiorna da sola all'ultimo tag
uv run payroll rollback vX.Y.Z                # su una macchina: torna a un tag precedente

# Ancora in vigore per il deploy verso Debian finche' il flusso sopra non e' collaudato dal vivo:
scripts/release.sh vX.Y.Z          # rilascio completo: smoke test, tag+push, deploy Debian (con gate di conferma), smoke test post-deploy, log
scripts/release.sh --deploy vX.Y.Z # riprende solo il deploy su Debian di un tag già pushato
scripts/release.sh --rollback vX.Y.Z   # riporta Debian a un tag precedente
```

`payroll release new` sostituisce solo la parte "tag + push" di
`scripts/release.sh` (preflight, smoke test, CHANGELOG, tag, push) — non
deploya. Finché Debian non aggiorna se stesso con `payroll update apply` in
un caso reale, `scripts/release.sh --deploy`/`--rollback` restano il modo
per portare davvero il codice sull'ambiente di produzione.

SemVer: **patch** (`v0.1.x`) fix senza cambio schema, **minor** (`v0.2.0`)
nuove funzionalità, **major** (`v1.0.0`) cambio schema DB non retrocompatibile.

## Risoluzione problemi comuni

Vedi la sezione "Risoluzione problemi noti" in [`INSTALL-INFO.md`](INSTALL-INFO.md#7-risoluzione-problemi-noti)
(plugin Compose mancante, permessi Docker, file di proprietà `root`, credential
helper di Docker Desktop residuo).
