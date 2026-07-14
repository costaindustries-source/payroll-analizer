# Changelog

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it/1.0.0/).

## [Non rilasciato]

### Modificato
- Python 3.12 -> 3.14 (`.python-version`, `pyproject.toml`, immagine base Dockerfile).
- Postgres 16 -> 17.6 in `docker-compose.yml` (allineato alla versione
  dell'istanza Supabase usata come riferimento). Cambio di major version:
  richiede la procedura in due fasi di backup/restore su ogni ambiente (v.
  README) — vedi sotto per `scripts/upgrade-postgres.sh` -> `payroll db`.
- Repo riorganizzato come **workspace uv** (`packages/payroll-ingest`,
  `packages/payroll-cli`): `src/`, `alembic/`, `alembic.ini` spostati in
  `packages/payroll-ingest/`. Il `Dockerfile` e l'immagine `app` sono
  invariati nel comportamento (stessi comandi `docker compose run --rm app
  payroll-ingest ...` / `alembic ...`).
- `scripts/upgrade-postgres.sh` **deprecato**: la logica di backup/restore
  (idempotenza, verifica TOC, verifica conteggi righe, mai cancella un
  volume) si è spostata in `payroll_cli/db.py`; lo script resta come thin
  shim che delega a `payroll db backup`/`payroll db restore` (stessa
  interfaccia, nessuna logica duplicata). `scripts/release.sh` resta
  invariato per il deploy su Debian (`--deploy`/`--rollback`): la sua parte
  di pubblicazione tag è ora coperta da `payroll release new`, ma il deploy
  vero e proprio resta lì finché `payroll update apply` non è stato
  collaudato su un aggiornamento reale.

### Aggiunto
- CLI operativa **host** `payroll` (`packages/payroll-cli`), reingegnerizzazione
  descritta in `docs/CLI_REDESIGN_PROPOSAL.md`:
  - fase 1 (read-only): `version`, `status`, `update check`, `help` (annidato).
  - fase 2: `setup` (doctor prerequisiti + wizard config per-macchina in
    `payroll.local.toml` + generazione `docker-compose.override.yml` solo se
    serve + bootstrap build/avvio/migration/smoke test), `db backup/restore`,
    `db migrate`, `db shell` (psql interattivo), `cleanup` (report dry-run di
    default + `--apply`: residui in `work/`, log oltre retention, backup
    oltre il numero da conservare; le immagini Docker dangling sono solo
    riportate, mai rimosse automaticamente).
  - fase 3: `update apply` (modello pull — v. `docs/CLI_REDESIGN_PROPOSAL.md`
    §6: blocca su working tree sporco, backup automatico se il bump cambia il
    volume Postgres rilevato via diff di `docker-compose.yml` tra tag, resume
    post-checkout eseguito dal codice del *nuovo* tag — non da quello ancora
    in memoria nel processo che ha avviato l'update — build/restore/
    migration/smoke test, propone rollback automatico su fallimento) e
    `rollback <tag>` (checkout + rebuild immagine, non tocca mai dati/volumi).
    Traccia gli esiti in `logs/updates.log` locale.
  - fase 4: `release new <vX.Y.Z> [-m msg]` (solo macchina `role=source`):
    preflight (branch `main`, working tree pulito, tag non esistente) ->
    smoke test locale **obbligatorio** (a differenza di `setup`/`update
    apply`, qui non viene mai saltato) -> promuove `## [Non rilasciato]` di
    `CHANGELOG.md` a `## [vX.Y.Z] - <data>` e la committa -> conferma
    esplicita -> tag annotato + push. Nessun deploy: la promozione resta
    compito di ogni nodo con `update apply`. `release list` mostra la storia
    dei tag pubblicati (locale + verifica su origin). Dopo il push, crea
    anche una GitHub Release via `gh` con le note del changelog appena
    promosso (non bloccante: un fallimento logga solo un avviso).
  - chiusura punti aperti (`docs/CLI_REDESIGN_PROPOSAL.md` §10): autenticazione
    dei nodi verso GitHub via **deploy key SSH read-only**
    (`payroll_cli/deploy_key.py` + `payroll setup --deploy-key`, solo
    `role=node`: genera la coppia ed25519 in `~/.ssh/payroll-deploy` se non
    esiste già, stampa la chiave pubblica da autorizzare a mano su GitHub,
    converte il remote a SSH su richiesta, imposta `core.sshCommand` scoped
    al solo repo locale); installazione CLI host confermata via `uv run`
    (non `uv tool install`); nome comando confermato `payroll`.

## [v0.3.0] - 2026-07-13

### Fix
- Glitch di font Zucchetti (issue #4), due manifestazioni su `07.pdf`/`08.pdf`/`202201.pdf`:
  - Codici causale `Z`->`2`: quando il codice risultante e' grammaticalmente
    impossibile (es. `2P9960`, digit seguito da lettera) viene corretto in
    automatico (`ZP9960`) con anomalia esplicita `codice_causale_corretto_automaticamente`
    invece di perdere la riga. Quando invece combacia per caso con il formato
    codice valido (es. `200020`, tutto numerico) il valore *non* viene alterato
    (nessun checksum disponibile per validarlo): viene solo segnalato come
    sospetto (`codice_causale_sospetto`) se nello stesso documento la
    corruzione e' gia' confermata altrove.
  - IBAN `O`->`0` sul CIN (5° carattere): corretto solo se la sostituzione
    supera il checksum standard IBAN (ISO 7064 mod 97-10), con anomalia
    esplicita `iban_corretto_automaticamente` — mai una correzione indovinata.

### Aggiunto
- Comando CLI `check-years`: per ogni annualita' mostra quanti documenti sono
  completamente caricati (status `PROCESSED`, zero anomalie) e, per quelli che
  non lo sono, il file e le anomalie che lo riguardano. Utile per verificare a
  colpo d'occhio se un'annualita' ha documenti mancanti o da rivedere.

## [v0.1.1] - 2026-07-13

### Fix
- `is_zucchetti_document`: fallback sul pattern del codice azienda
  (`_COMPANY_CODE_ROW_RE`) quando la riga di intestazione esatta è illeggibile
  per un glitch di font più severo del solito. Risolve il `NEEDS_REVIEW` di
  `07.pdf`, `08.pdf`, `202201.pdf` — ora riconosciuti come `zucchetti_standard`
  con azienda/dipendente/periodo/CF correttamente estratti.
- Documentata in `PIANO_TECNICO.md` §17 la limitazione nota: su questi 3 file
  le righe voce/contributi/totali restano vuote (marcatore di sezione anch'esso
  corrotto) — nessun importo viene inventato, il documento risulta
  `PROCESSED_WITH_ANOMALIES` con anomalia esplicita `nessuna_riga_voce`.

### Aggiunto
- `scripts/smoke_test.py` — regressione automatica sui 6 cedolini di riferimento.
- `scripts/release.sh` — processo di rilascio Ubuntu (dev) -> GitHub -> Debian (prod), con gate di conferma, smoke test pre/post deploy e rollback.
- `docs/RELEASE_PROCESS.md`, `RELEASE_LOG.md`.

## [v0.1.0] - 2026-07-13

Baseline: snapshot del codice effettivamente in esecuzione su Debian
(`~/app/payroll-analizer`) al momento del primo audit strutturato. Punto di
partenza per il processo di rilascio Ubuntu (dev) -> GitHub -> Debian (prod).
