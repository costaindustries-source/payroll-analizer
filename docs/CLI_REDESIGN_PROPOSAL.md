# Proposta: reingegnerizzazione completa della CLI (`payroll`)

> Stato: **proposta**, non ancora implementata. Obiettivo: eliminare `scripts/release.sh` e
> `scripts/upgrade-postgres.sh` e gestire l'intero ciclo di vita (installazione, aggiornamento,
> manutenzione, rilascio, dominio) da un'unica CLI, su ogni macchina.

## 1. Il problema del modello attuale

| Oggi | Problema |
|---|---|
| CLI `payroll-ingest` (Typer) | Copre solo il dominio (process/export/check-years/delete-document). Vive **dentro il container**: non può gestire git, docker compose, aggiornamenti. |
| `scripts/release.sh` | Modello **push**: Ubuntu spinge il deploy su UNA macchina hardcoded (Debian via `wsl.exe`). Non scala a n macchine, richiede accesso cross-distro, mescola due responsabilità (pubblicare una versione ≠ aggiornare un ambiente). |
| `scripts/upgrade-postgres.sh` | Procedura manuale in due fasi che l'operatore deve ricordarsi di eseguire nel momento giusto rispetto al checkout. Facile sbagliare l'ordine. |
| `docker-compose.override.yml` | Config per-macchina creata a mano (o da release.sh), senza uno schema. |

## 2. Principi del nuovo design

1. **Un solo entrypoint**: `payroll` — installato **sull'host** di ogni macchina, unico comando che l'operatore conosce. I comandi di dominio delegano al container (`docker compose run --rm app payroll-ingest …`); i comandi di ciclo di vita girano nativi sull'host (git, docker, filesystem).
2. **Pull, non push**: Ubuntu (source) **pubblica** una versione (tag su GitHub) e basta. Ogni macchina installata **si aggiorna da sola** con `payroll update`. Sparisce il ponte `wsl.exe` e la dipendenza dalla topologia (n macchine = n `payroll update`, identici).
3. **Ruoli espliciti**: ogni macchina ha un ruolo dichiarato in configurazione — `source` (solo Ubuntu: abilita il gruppo `release`) o `node` (macchina installata: gruppo `release` nascosto/bloccato). Nessuna deduzione implicita.
4. **Una sola fonte di config per macchina**: `payroll.local.toml` (non versionato), scritto da `payroll setup`. Da lì la CLI **genera** `docker-compose.override.yml` — l'operatore non tocca mai YAML a mano.
5. **Le operazioni rischiose sono ordinate dalla CLI, non dall'operatore**: il backup pre-bump-major di Postgres non è più "ricordati di lanciarlo prima del checkout" — è `payroll update` che rileva il cambio volume diffando `docker-compose.yml` tra tag corrente e tag target, e sequenzia backup → checkout → restore da solo.
6. **Sicurezza invariata**: mai cancellare volumi/dati automaticamente, conferme sui passi distruttivi, rollback proposto su smoke test fallito, dry-run di default per `cleanup`.

## 3. Albero comandi proposto

```text
payroll
├── help [comando]              # alias di --help, navigabile per sottocomando
├── version                     # tag git corrente, schema Alembic (current vs head),
│                               # versione Postgres, versione CLI  [= check-project-version]
├── status                      # salute macchina: container db/app, health DB, migrazioni,
│                               # conteggi documenti per stato, file in attesa in input/,
│                               # spazio disco, ultimo update/release, update disponibile
├── setup                       # [= first-configuration] wizard prima installazione:
│   │                           #   doctor prerequisiti (docker, compose, git, spazio)
│   │                           #   → domande (ruolo, porta DB host, retention)
│   │                           #   → scrive payroll.local.toml + override compose generato
│   │                           #   → (nodo) genera deploy key e guida ad autorizzarla su GitHub
│   │                           #   → build immagine, up db, alembic upgrade head, smoke test
│   └── --check                 # solo doctor, nessuna modifica (rieseguibile sempre)
├── update
│   ├── check                   # [= check-project-update] fetch tags, confronta tag locale
│   │                           # vs ultimo remoto, mostra changelog delle versioni in mezzo
│   └── apply [--to vX.Y.Z]     # aggiornamento completo con auto-backup se bump major PG:
│                               #   1. fetch + risoluzione tag target
│                               #   2. diff docker-compose.yml corrente↔target:
│                               #      volume db cambiato? → db backup automatico
│                               #   3. git checkout <tag>
│                               #   4. re-exec della NUOVA CLI con --resume (v. §6)
│                               #   5. db restore (solo se serviva), build, alembic upgrade,
│                               #      smoke test → su fallimento propone rollback al tag prima
├── rollback <tag>              # torna a un tag precedente: checkout + rebuild + smoke test
├── db
│   ├── backup [--output …]     # pg_dump -Fc + verifica TOC + snapshot conteggi (.counts)
│   ├── restore [dump]          # idempotente: no-op se lo schema esiste già (come oggi)
│   ├── migrate                 # alembic upgrade head (esplicito, fuori da update)
│   └── shell                   # psql interattivo nel container db
├── cleanup [--apply]           # default = report (dry-run): work/ residui, logs/ oltre
│   │                           # retention, backup oltre gli ultimi K, immagini docker
│   │                           # dangling del progetto
│   └── (volumi PG vecchi: SOLO elencati con comando suggerito, mai rimossi)
├── release                     # SOLO role=source (Ubuntu)
│   ├── new <vX.Y.Z> [-m msg]   # preflight (main, tree pulito, tag libero) → smoke test
│   │                           # locale → aggiorna CHANGELOG.md → tag annotato → push.
│   │                           # STOP: nessun deploy remoto. I nodi fanno `payroll update`.
│   └── list                    # tag pubblicati + quale gira dove non è più compito suo:
│                               # mostra solo la storia locale/remota dei tag
└── (dominio — delega al container, UX invariata)
    ├── process
    ├── export
    ├── check-years
    └── delete-document [--filename|--sha256|--id]
```

Mapping con i nomi che avevi in mente: `check-project-version` → `payroll version`,
`check-project-update` → `payroll update check`, `first-configuration` → `payroll setup`.

## 4. Architettura pacchetti (uv workspace)

Il punto delicato: la CLI ops deve girare **sull'host** di ogni nodo, ma le dipendenze di
dominio (PyMuPDF, OCRmyPDF, SQLAlchemy…) devono restare **solo nel container**. Split in due
pacchetti con uv workspace:

```text
payroll-analizer/
├── pyproject.toml                  # root workspace (members: packages/*)
├── packages/
│   ├── payroll-ingest/             # ← l'attuale src/payroll_ingest, INVARIATO
│   │   └── pyproject.toml          #    (gira solo nel container, deps pesanti)
│   └── payroll-cli/                # ← NUOVO: ops host
│       ├── pyproject.toml          #    deps minime: typer, rich, tomli-w. Niente DB,
│       └── src/payroll_cli/        #    niente PDF: shell-out a git/docker/gh.
│           ├── main.py             #    app Typer, dispatch ruolo source/node
│           ├── context.py          #    lettura payroll.local.toml, discovery repo root
│           ├── compose.py          #    wrapper docker compose + generazione override
│           ├── git_ops.py          #    fetch/tags/checkout/diff-tra-tag
│           ├── update.py           #    update check/apply, resume, rollback
│           ├── pg_upgrade.py       #    porting 1:1 di upgrade-postgres.sh
│           ├── release.py          #    porting della parte publish di release.sh
│           ├── setup_wizard.py     #    first-configuration + doctor
│           ├── cleanup.py          #    retention e report
│           └── status.py           #    status/version
```

Installazione sull'host (identica su source e nodi):

```bash
# prerequisiti host: git, docker, uv (un solo binario statico, curl -LsSf https://astral.sh/uv/install.sh | sh)
uv tool install --from ~/app/payroll-analizer/packages/payroll-cli payroll-cli
payroll setup
```

`uv tool install` da checkout locale → dopo ogni `payroll update apply` la CLI si
re-installa da sola dal nuovo checkout (passo finale dell'update). In alternativa, ancora più
semplice e senza re-install: alias `payroll` → `uv run --project <repo>/packages/payroll-cli payroll`,
che esegue sempre il codice del checkout corrente (consigliato: zero stato da sincronizzare).

## 5. Configurazione per macchina: `payroll.local.toml`

Scritto da `payroll setup`, mai committato (in `.gitignore`), sostituisce la gestione manuale
di `docker-compose.override.yml` (che diventa un file **generato**, con header "non editare"):

```toml
[machine]
name = "debian-prod"        # etichetta libera, compare in status/log
role = "node"               # "source" (solo Ubuntu) | "node"

[db]
host_port = 5433            # → generato in docker-compose.override.yml

[update]
auto_backup = true          # backup pre-checkout anche senza bump major (paranoia mode)

[cleanup]
logs_retention_days = 90
backups_keep = 5
```

## 6. I tre flussi chiave

### `payroll release new v0.3.0` (solo Ubuntu/source)
1. Preflight: branch `main`, working tree pulito, tag inesistente.
2. Smoke test locale (`scripts/smoke_test.py`, invariato).
3. Messaggio di release (`-m` o prompt) → append a `CHANGELOG.md`, commit.
4. Tag annotato + `git push origin main --follow-tags`.
5. Fine. **Nessun deploy**: la promozione sulle macchine è responsabilità dei nodi
   (`RELEASE_LOG.md` centrale sparisce; ogni nodo tiene il proprio `logs/updates.log`).

### `payroll update apply` (su ogni nodo, Debian inclusa)
1. `git fetch --tags` via deploy key read-only della macchina (v. §7).
2. Risolve il target (ultimo tag SemVer, o `--to`). Se già lì: esce.
3. **Pre-flight major PG**: `git diff <corrente> <target> -- docker-compose.yml`; se il nome
   del volume `db` cambia → `payroll db backup` automatico (con conferma).
4. `git checkout <tag>`.
5. **Re-exec**: la CLI in esecuzione è la versione vecchia → rilancia sé stessa dal nuovo
   checkout con `payroll update apply --resume <tag> [--restore-needed]` (con l'alias
   `uv run` questo è gratis: il re-exec carica già il codice nuovo).
6. (se serviva) `db restore` idempotente → `docker compose build app` → `alembic upgrade head`
   nel container → smoke test nel container.
7. Smoke test fallito → propone `payroll rollback <tag precedente>`. Il volume PG vecchio non
   è mai stato toccato.
8. Append a `logs/updates.log` locale (macchina, da→a, esito, durata).

### `payroll setup` (prima installazione di un nodo nuovo)
1. Doctor: docker + compose plugin, git, uv, spazio disco, UID/GID (warning se ≠1000).
2. Domande: nome macchina, ruolo, porta DB host, retention.
3. Scrive `payroll.local.toml` → genera `docker-compose.override.yml`.
4. Se il repo non è ancora clonato: genera chiave SSH deploy (`~/.ssh/payroll-deploy`),
   stampa la public key da autorizzare su GitHub come deploy key read-only, poi clona.
5. `docker compose build` → `up -d db` → `alembic upgrade head` → smoke test → `status`.

## 7. Accesso a GitHub dai nodi (da decidere)

Oggi il fetch su Debian usa il token `gh` di Ubuntu iniettato al volo (modello push). Col
modello pull ogni nodo deve poter fare `git fetch` dal repo privato da solo. Opzioni:

- **A. Deploy key SSH read-only per macchina (consigliata)** — nativa GitHub, revocabile per
  singola macchina, nessuna scadenza, nessun token in chiaro; `payroll setup` la genera e
  guida l'autorizzazione.
- B. Fine-grained PAT read-only per macchina in `payroll.local.toml` — più semplice ma è un
  secret su disco con scadenza da rinnovare.

## 8. Fine vita degli script

| Script | Destino |
|---|---|
| `scripts/release.sh` | Eliminato. Publish → `payroll release new`; deploy → `payroll update apply` sul nodo; rollback → `payroll rollback`. La logica bootstrap-history/override Debian non serve più (già sanata) o è assorbita da `setup`. |
| `scripts/upgrade-postgres.sh` | Eliminato. `cmd_backup`/`cmd_restore` portati 1:1 in `payroll_cli/pg_upgrade.py` (stessa semantica: idempotenza, verifica TOC, verifica conteggi, mai cancellare volumi), orchestrati da `update apply` e disponibili singolarmente come `payroll db backup/restore`. |
| `scripts/smoke_test.py` | Resta (è il gate di qualità), invocato dalla CLI. |

## 9. Piano di migrazione incrementale

1. **v0.3.0** — workspace uv + pacchetto `payroll-cli` con i comandi *sicuri e read-only*:
   `version`, `status`, `update check`, `help`, `db shell`. Gli script .sh restano funzionanti.
2. **v0.4.0** — `db backup/restore/migrate`, `cleanup`, `setup` (wizard + doctor).
   `upgrade-postgres.sh` deprecato (stampa un avviso e delega alla CLI).
3. **v0.5.0** — `update apply` + `rollback` con re-exec e auto-backup. Primo update reale di
   Debian eseguito **dalla CLI stessa** come collaudo. Deploy key configurata su ogni nodo.
4. **v0.6.0** — `release new/list` su Ubuntu; `release.sh` e `upgrade-postgres.sh` rimossi;
   `docs/RELEASE_PROCESS.md` riscritto attorno al modello pull.

Ogni fase è rilasciabile da sola e collaudabile sul flusso reale prima della successiva
(la 3 è quella delicata: finché non è collaudata, `release.sh --deploy` resta il fallback).

## 10. Punti aperti

1. Metodo di autenticazione dei nodi verso GitHub (§7 — proposta: deploy key SSH).
2. `payroll release new` deve anche creare una GitHub Release (via `gh`) con il changelog,
   così `update check` sui nodi può mostrare le note senza parsare `CHANGELOG.md`? (nice to have)
3. Installazione CLI host: alias `uv run` (sempre coerente col checkout, consigliato) vs
   `uv tool install` (comando globale, ma richiede re-install a ogni update)?
4. Nome comando: `payroll` (proposto) o mantenere `payroll-ingest` anche per l'ops?
