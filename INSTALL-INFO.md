# Guida installazione — payroll-ingest

Guida per installare ed eseguire l'intero pacchetto (motore database, OCR, dipendenze, applicazione) su **WSL Debian** con Docker. Tutto il software richiesto — sistema operativo, database, librerie Python, motore OCR — è **gratuito e open source**: non serve alcun abbonamento, licenza a pagamento o account esterno. Il dettaglio licenza-per-licenza è nella sezione [Licenze e costi](#licenze-e-costi-nessun-abbonamento-richiesto).

> Nota: questa guida presume che Docker sia già installato e funzionante su WSL Debian (verificato in fase di sviluppo su un ambiente Ubuntu 24.04/Debian equivalente — i comandi sono identici). Se Docker non è ancora installato, vedi [0. Installare Docker](#0-installare-docker-se-non-già-presente).

---

## Cosa viene installato

| Componente | Dove | Come |
|---|---|---|
| PostgreSQL 16 | container Docker (`db`) | immagine ufficiale `postgres:16-alpine`, nessuna installazione sull'host |
| Python 3.12 + tutte le dipendenze (pdfplumber, PyMuPDF, SQLAlchemy, ecc.) | container Docker (`app`) | installate nell'immagine dal `Dockerfile` |
| Tesseract OCR + lingua italiana, Ghostscript, Poppler, unpaper | container Docker (`app`) | installate via `apt` dentro l'immagine |
| Applicazione `payroll-ingest` (CLI) | container Docker (`app`) | pacchetto Python installato nell'immagine |

**Sull'host WSL Debian serve solo Docker** (Engine + plugin Compose). Nessun Python, nessun PostgreSQL, nessun Tesseract da installare manualmente sull'host: tutto vive nei container.

---

## 0. Installare Docker (se non già presente)

Verifica se è già installato:

```bash
docker --version
docker compose version
```

Se manca, installa **Docker Engine** (non "Docker Desktop" — su WSL Debian si usa il motore nativo Linux, gratuito senza alcuna condizione legata a dimensione aziendale):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Dopo `usermod`, esci e rientra nella sessione WSL (o esegui `newgrp docker`) perché il gruppo `docker` sia effettivo senza `sudo`.

---

## 1. Struttura del progetto

Il progetto vive in `repo/payroll-analizer/`. Cartelle rilevanti (create automaticamente se assenti):

```text
docs/           esempi payroll reali (read-only, usati per analisi/regressione)
input/          metti qui i PDF da elaborare
processed/      PDF elaborati correttamente, organizzati per anno/mese
error/          PDF in errore, con file <nome>.error.json a fianco
logs/           log di ogni esecuzione batch (JSON) + riepilogo run
export/         export completi e versionati del database
work/           area temporanea (OCR); non contiene dati definitivi
```

## 2. Primo avvio

Dalla cartella del progetto:

```bash
cd repo/payroll-analizer

# 1. Costruisce l'immagine dell'app (Python + Tesseract + dipendenze)
docker compose build

# 2. Avvia PostgreSQL e attende che sia pronto
docker compose up -d db

# 3. Crea le tabelle nel database (migration Alembic)
docker compose run --rm app alembic upgrade head
```

Al termine, il database è pronto e vuoto (schema creato, zero cedolini caricati).

## 3. Uso quotidiano

```bash
# Copia i PDF da elaborare in input/
cp /percorso/dei/cedolini/*.pdf input/

# Elabora tutto il contenuto di input/ (un file alla volta, isolato)
docker compose run --rm app payroll-ingest process

# Genera un export completo e versionato del database in export/
docker compose run --rm app payroll-ingest export
```

Il comando `process`:
- calcola l'hash SHA-256 di ogni PDF (un file già caricato con successo viene saltato, non duplicato);
- classifica il PDF (testuale vs scansionato) e applica l'OCR solo se serve;
- riconosce il layout ed estrae i dati strutturati;
- salva tutto nel database in una transazione per documento;
- sposta il PDF in `processed/<anno>/<mese>/` (o in `error/` con un file `.error.json` se qualcosa va storto) — **un errore su un file non blocca gli altri**;
- scrive un log JSON in `logs/` per la singola esecuzione (`batch_<run_id>.log`, `run_<run_id>.json`).

Per fermare/riavviare i servizi:

```bash
docker compose stop        # ferma i container (i dati restano)
docker compose up -d db     # riavvia solo il database
docker compose down         # ferma e rimuove i container (il volume dati Postgres NON viene toccato)
```

## 4. Verificare che l'installazione funzioni

```bash
# Copia i PDF di esempio (già presenti nel repo) come primo test
cp docs/payroll-test/*.pdf input/
docker compose run --rm app payroll-ingest process
```

Output atteso: un riepilogo con `6 file, ... ok ...`. Verifica anche via `psql`:

```bash
docker compose exec db psql -U payroll -d payroll -c "select count(*) from payroll_document;"
```

## 5. Accesso diretto al database (opzionale)

```bash
docker compose exec db psql -U payroll -d payroll
```

Oppure da un client SQL sull'host (DBeaver, SQLTools, ecc.), connessione a `localhost:5432`, utente `payroll`, password `payroll`, database `payroll` (porta pubblicata da `docker-compose.yml`; se non serve accesso esterno si può rimuovere la sezione `ports:` del servizio `db`).

## 6. Backup e portabilità dei dati

- **Backup del database**: il volume Docker `db_data` contiene tutti i dati Postgres. Backup rapido: `docker compose exec db pg_dump -U payroll payroll > backup.sql`.
- **Export applicativo**: `docker compose run --rm app payroll-ingest export` produce in `export/<timestamp>_<versione_schema>/` un pacchetto **indipendente da Postgres** (un file `.jsonl` per tabella + `manifest.json` con conteggi e ordine di reimport), pensato per essere leggibile/importabile anche da un sistema diverso in futuro.

## 7. Risoluzione problemi noti

- **`docker: unknown command: docker compose`**: il plugin Compose v2 non è installato o non è nel path dei plugin CLI. Verifica con `docker compose version`; se assente, installa `docker-compose-plugin` (vedi punto 0) oppure usa il binario standalone `docker-compose` (v1, spesso già presente) come fallback: i comandi di questa guida funzionano identici sostituendo `docker compose` con `docker-compose`.
- **Errore di permessi (`docker: permission denied` sul socket)**: l'utente non è nel gruppo `docker`. Esegui `sudo usermod -aG docker "$USER"` e riavvia la sessione WSL.
- **File creati con proprietario `root` nelle cartelle `input/processed/error/logs/export/work`**: non dovrebbe succedere (l'immagine esegue l'app con utente non privilegiato, UID/GID 1000, il default del primo utente su Debian). Se il tuo utente host ha UID/GID diverso da 1000, ricostruisci l'immagine con `docker compose build --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g) app`.
- **Errore "credential helper" durante `docker pull`/`docker compose build`** (es. `docker-credential-desktop.exe not found`): capita se `~/.docker/config.json` referenzia un helper credenziali di Docker Desktop per Windows non presente in WSL puro. Soluzione: rimuovi o correggi la chiave `"credsStore"` nel file `~/.docker/config.json`, oppure esporta temporaneamente `DOCKER_CONFIG` verso una cartella con un `config.json` minimale (`{}`).

---

## Licenze e costi: nessun abbonamento richiesto

**Verdetto sintetico: per l'uso previsto (tool batch interno a Revo Insurance, mai distribuito a terzi, mai esposto come servizio a clienti esterni) tutto lo stack è gratuito, nessun abbonamento né licenza commerciale richiesta.** Verificato componente per componente (fonti ufficiali: PyPI, GitHub, siti dei progetti):

| Componente | Licenza | Gratuito per questo uso? |
|---|---|---|
| Python 3.12 | PSF License v2 (permissiva) | ✅ Sì |
| PostgreSQL 16 | PostgreSQL License (permissiva, tipo BSD/MIT) | ✅ Sì |
| Docker Engine + Compose (nativo, non Docker Desktop) | Apache 2.0 | ✅ Sì |
| Tesseract OCR | Apache 2.0 | ✅ Sì |
| OCRmyPDF | MPL-2.0 | ✅ Sì |
| SQLAlchemy, Alembic | MIT | ✅ Sì |
| psycopg (driver PostgreSQL) | LGPL-3.0 | ✅ Sì (nessun obbligo per uso interno non distribuito) |
| Typer, Pydantic, structlog, pdfplumber, ecc. | MIT / BSD / Apache-2.0 | ✅ Sì |
| PyMuPDF (estrazione PDF) | **Dual: AGPL-3.0 oppure licenza commerciale Artifex** | ✅ Sì, con una condizione (vedi sotto) |
| Ghostscript, Poppler-utils, unpaper (usati da OCRmyPDF) | AGPL-3.0 / GPL-2.0+ | ✅ Sì, con la stessa condizione |
| fpdf2, img2pdf, pi-heif (dipendenze minori) | LGPL-3.0 | ✅ Sì (nessun obbligo per uso interno) |

### L'unica condizione da tenere a mente

**PyMuPDF** e **Ghostscript** sono distribuiti sotto licenza **AGPL-3.0**, con un'alternativa commerciale a pagamento (Artifex Software) per chi non vuole/può rispettare l'AGPL. La differenza pratica:

- **Uso gratuito (AGPL) sufficiente quando**: il tool resta interno all'azienda, non viene distribuito a terzi (clienti, partner esterni) e non viene esposto come servizio via rete a utenti esterni a Revo Insurance. **Questo è esattamente lo scenario di `payroll-ingest`** come progettato: batch interno, container Docker locale, nessuna distribuzione, nessuna API pubblica.
- **Licenza commerciale a pagamento necessaria solo se in futuro**: si distribuisse il software (o un'immagine Docker con dentro PyMuPDF/Ghostscript) a soggetti esterni all'azienda, oppure si esponesse come servizio SaaS/API a clienti esterni, senza voler rilasciare il codice sotto AGPL.

Ghostscript/Poppler/unpaper sono inoltre invocati solo come **processi esterni** (subprocess) da OCRmyPDF, non collegati al codice Python: questo rafforza ulteriormente che non ci sono obblighi di licenza per l'uso descritto in questa guida.

Se in futuro cambiano il perimetro d'uso (distribuzione esterna, SaaS a terzi), va ripetuta questa valutazione — idealmente con il team legal/compliance interno.

---

## Riferimenti

- Piano tecnico completo: `PIANO_TECNICO.md`
- Requisiti originali: `requirements.md`
- Codice applicazione: `packages/payroll-ingest/src/payroll_ingest/`
- CLI operativa (host): `packages/payroll-cli/`
