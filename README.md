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
  macchina che ospita Docker, non nel container. Copre `version`, `status`,
  `update check/apply`, `rollback`, `help`, `setup`,
  `db backup/restore/migrate/shell`, `cleanup`, `release new/list`. Processo
  di rilascio e ruoli (`source`/`node`) descritti per intero in
  [`docs/RELEASE_PROCESS.md`](docs/RELEASE_PROCESS.md), non ripetuti qui.

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
uv run payroll setup --deploy-key          # (solo role=node) genera/mostra la deploy key SSH read-only
uv run payroll setup --pull                # git pull --ff-only prima di tutto il resto (saltato se dirty o su un tag)
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
`main` + il tag -> crea anche una GitHub Release con le note del changelog
appena promosso (via `gh`, non bloccante: se fallisce logga solo un avviso).
**Non deploya nulla**: la promozione sulle macchine resta compito di
ciascun nodo con `payroll update apply`.

`payroll setup --deploy-key` (solo `role=node`: su `role=source` viene
saltato con un avviso, quella macchina ha già credenziali in scrittura)
genera — se non esiste già — una deploy key SSH read-only in
`~/.ssh/payroll-deploy`, ne stampa la chiave pubblica da autorizzare a mano
su GitHub (repo → Settings → Deploy keys → Add deploy key, **senza**
spuntare "Allow write access"), offre di convertire il remote `origin` da
HTTPS a SSH, e imposta `core.sshCommand` scoped al solo repo locale (`git
config --local`, non tocca `~/.ssh/config` né altri progetti). Serve perché
`payroll update apply` su un nodo deve poter fare `git fetch` da solo,
senza le credenziali con permesso di scrittura della macchina `source`.

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

`docker compose run` riusa silenziosamente l'immagine `app` gia' buildata anche
se il codice in `packages/` e' cambiato da allora, senza nessun avviso (GH
#26): dopo aver modificato `packages/payroll-ingest` o `packages/payroll-cli`,
rifai sempre la build prima di processare —
`docker compose build app && docker compose run --rm app payroll-ingest process`
— oppure usa direttamente `docker compose run --build --rm app ...`.
`uv run payroll status` segnala un avviso quando rileva codice piu' recente
dell'ultima build.

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

## Test di regressione (smoke test + suite pytest)

Lo smoke test gira sui 6 cedolini reali di riferimento in `docs/payroll-test/`
(mai in git) dopo ogni modifica a `templates/zucchetti.py` o `extraction.py`:

```bash
.venv/bin/python scripts/smoke_test.py                          # locale (Ubuntu, venv host)
docker compose run --rm app python scripts/smoke_test.py --samples-dir /data/docs/payroll-test   # dentro il container
```

Per i template Copernico/SAP HR, `scripts/verify_new_templates.py` (chiama
`extract_document`+`find_template`+`spec.map` direttamente) e
`scripts/verify_new_templates_real_batch.py` (esegue il path reale
`classify_pdf`->...->`save_document`->spostamento file tramite `run_batch`,
su uno schema Postgres isolato usa-e-getta e una copia scratch dei campioni)
vanno lanciati **entrambi** dopo ogni modifica a
`extraction.py`/`templates/*.py`/`orchestrator.py`/`ocr.py`: il primo e' piu'
rapido (nessun DB/OCR coinvolto) ma da solo puo' dare un falso "tutto OK" su
differenze che si manifestano solo nel path reale (v. issue GH #25/#27):

```bash
uv run python scripts/verify_new_templates.py
docker compose up -d db   # se non gia' in esecuzione
uv run python scripts/verify_new_templates_real_batch.py
```

`tests/` contiene la stessa copertura di regressioni note (destination path,
corruzione font) ma con fixture sintetiche, cosi' da poter girare anche in CI
senza dati reali:

```bash
uv run pytest --cov=payroll_ingest --cov=payroll_cli --cov-report=term-missing
uv run python scripts/check_coverage.py   # fallisce se un qualunque file scende sotto l'80%
```

**Ogni nuovo sviluppo richiede test con coverage per-file >=80%** (non solo la
media aggregata): `scripts/check_coverage.py` legge i dati di `coverage.py`
dopo la run di pytest e fallisce elencando i file sotto soglia. I test che
toccano il database usano le fixture `db_session`/`db_session_factory`/
`db_engine` di `tests/conftest.py`: creano uno schema Postgres isolato e
usa-e-getta su un'istanza gia' in esecuzione (locale: `docker compose up -d
db`; CI: service container dedicato), mai lo schema `public` dove vivono i
dati reali.

GitHub Actions (`.github/workflows/ci.yml`) esegue questa suite (con service
container Postgres) + il gate di coverage su ogni push/PR verso `main`. Lo
smoke test sui cedolini reali resta un gate solo locale/di
release (`payroll release new`), perche' i campioni non possono finire su
GitHub (v. `docs/RELEASE_PROCESS.md`, "Dati reali: mai su GitHub").

## Sviluppo locale senza Docker (Ubuntu, gestito da `uv`)

```bash
uv sync                                  # crea/aggiorna .venv da uv.lock
cp .env.example .env                     # DATABASE_URL -> localhost:5432 (serve comunque `docker compose up -d db`)
uv run payroll-ingest process            # o: source .venv/bin/activate && payroll-ingest process
uv run python scripts/smoke_test.py
```

## Rilascio (Ubuntu -> GitHub -> nodi)

Procedura completa, ruoli, versionamento SemVer e percorso legacy in
[`docs/RELEASE_PROCESS.md`](docs/RELEASE_PROCESS.md) — unica fonte di verità,
non duplicata qui. Riassunto minimo:

```bash
uv run payroll release new vX.Y.Z [-m msg]   # pubblica il tag su GitHub (solo su Ubuntu, role=source). Nessun deploy.
uv run payroll update apply                   # su OGNI nodo (Debian inclusa): si aggiorna da solo all'ultimo tag
uv run payroll rollback vX.Y.Z                # su un nodo: torna a un tag precedente
```

## Risoluzione problemi comuni

Vedi la sezione "Risoluzione problemi noti" in [`INSTALL-INFO.md`](INSTALL-INFO.md#7-risoluzione-problemi-noti)
(plugin Compose mancante, permessi Docker, file di proprietà `root`, credential
helper di Docker Desktop residuo).
