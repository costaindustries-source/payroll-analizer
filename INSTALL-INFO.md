# Guida installazione — payroll-analizer

Guida passo-passo, pensata per chi non ha mai installato questo progetto prima, per installare ed eseguire l'intero pacchetto (database, OCR, dipendenze, CLI) sia su **Windows** sia su **Linux**. Non serve esperienza pregressa con Docker o Python: ogni comando è spiegato, e ogni passo indica cosa aspettarsi come risultato.

Tempo stimato: 20-30 minuti la prima volta (la maggior parte è download di programmi).

Tutto il software richiesto — sistema operativo dei container, database, librerie Python, motore OCR — è **gratuito e open source**: nessun abbonamento, licenza a pagamento o account esterno a pagamento. Il dettaglio licenza-per-licenza è in fondo, in [Licenze e costi](#licenze-e-costi-nessun-abbonamento-richiesto).

---

## Indice

1. [Cosa stai installando](#1-cosa-stai-installando)
2. [Prerequisiti — Windows](#2a-prerequisiti--windows)
2. [Prerequisiti — Linux](#2b-prerequisiti--linux-debianubuntu-incluso-wsl)
3. [Ottenere il codice](#3-ottenere-il-codice)
4. [Verifica dei prerequisiti](#4-verifica-dei-prerequisiti)
5. [Configurazione guidata (`payroll setup`)](#5-configurazione-guidata-payroll-setup)
6. [Verificare che tutto funzioni](#6-verificare-che-tutto-funzioni)
7. [Uso quotidiano](#7-uso-quotidiano)
8. [Comandi utili da ricordare](#8-comandi-utili-da-ricordare)
9. [Risoluzione problemi](#9-risoluzione-problemi)
10. [Licenze e costi](#licenze-e-costi-nessun-abbonamento-richiesto)

---

## 1. Cosa stai installando

`payroll-analizer` legge cedolini PDF (buste paga Zucchetti), ne estrae i dati strutturati (importi, causali, netto, IBAN...) e li salva in un database PostgreSQL, con un log di ogni elaborazione e uno stato per ogni documento (elaborato correttamente, da rivedere, in errore).

| Componente | Dove gira | Installato da |
|---|---|---|
| PostgreSQL 17 | container Docker (`db`) | immagine ufficiale, nessuna installazione manuale |
| Python 3.14 + tutte le dipendenze (pdfplumber, PyMuPDF, SQLAlchemy...) | container Docker (`app`) | build automatica dell'immagine (`Dockerfile`) |
| Tesseract OCR (+ lingua italiana), Ghostscript, Poppler, unpaper | container Docker (`app`) | build automatica dell'immagine |
| `payroll-ingest` — motore che elabora i PDF | dentro il container `app` | build automatica dell'immagine |
| `payroll` — CLI di comando che usi tu, da terminale | **sul tuo computer** (host), non nel container | `uv` (vedi sotto) |

**Sul tuo computer (host) servono solo 3 programmi**: Docker, Git, `uv`. Nessun Python, PostgreSQL o Tesseract da installare a mano: vivono tutti dentro i container, e `uv` scarica automaticamente la versione di Python che serve per la CLI `payroll`, senza bisogno di installarla tu.

---

## 2a. Prerequisiti — Windows

Questa sezione presume **Windows nativo**, senza dover configurare manualmente una distribuzione Linux (WSL) a parte: userai PowerShell e Docker Desktop così come si installano di default.

### Docker Desktop

1. Scarica Docker Desktop da [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) e avvia l'installer.
2. Durante l'installazione lascia spuntata l'opzione predefinita ("Use WSL 2 instead of Hyper-V"): Docker Desktop configura da sé il necessario, non dovrai mai aprire o gestire tu una distribuzione Linux a mano.
3. Al termine, **riavvia il computer** se richiesto.
4. Avvia Docker Desktop dal menu Start e attendi che l'icona nella barra delle applicazioni indichi che è pronto (icona della balena, stabile, non animata).

Verifica in PowerShell:

```powershell
docker --version
docker compose version
```

Se entrambi rispondono con un numero di versione, sei a posto.

### Git

Scarica e installa [Git for Windows](https://git-scm.com/download/win) (le opzioni di default vanno bene per tutta l'installazione). Verifica:

```powershell
git --version
```

### uv (gestore Python)

In PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Chiudi e riapri PowerShell** dopo l'installazione (serve perché il PATH venga aggiornato). Verifica:

```powershell
uv --version
```

### GitHub CLI (per clonare il repository privato)

Il repository è **privato**: il modo più semplice per autenticarsi senza gestire chiavi SSH a mano è la [GitHub CLI](https://cli.github.com/):

```powershell
winget install --id GitHub.cli
gh auth login
```

`gh auth login` apre il browser per il login: scegli `GitHub.com`, `HTTPS`, poi "Login with a web browser" e segui le istruzioni a schermo.

A questo punto i prerequisiti Windows sono completi: passa al [punto 3](#3-ottenere-il-codice).

---

## 2b. Prerequisiti — Linux (Debian/Ubuntu, incluso WSL)

### Docker Engine + Compose

Verifica se è già installato:

```bash
docker --version
docker compose version
```

Se manca (comandi identici su Debian e Ubuntu, cambia solo l'URL del repository apt indicato nel commento):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
# Su Ubuntu sostituisci "debian" con "ubuntu" in questa riga e nella successiva
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Dopo `usermod`, **esci e rientra nella sessione** (o esegui `newgrp docker`) perché il gruppo `docker` sia effettivo senza `sudo`.

### Git

Quasi certamente già presente. Verifica/installa:

```bash
git --version || sudo apt-get install -y git
```

### uv (gestore Python)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Apri un nuovo terminale** dopo l'installazione (o esegui `source $HOME/.local/bin/env`). Verifica:

```bash
uv --version
```

### GitHub CLI (per clonare il repository privato)

```bash
type -p curl >/dev/null || sudo apt-get install curl -y
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt-get update
sudo apt-get install gh -y
gh auth login
```

A questo punto i prerequisiti Linux sono completi: passa al punto 3.

---

## 3. Ottenere il codice

Da qui in poi i comandi sono **identici** su Windows (PowerShell) e Linux (bash), salvo dove indicato esplicitamente.

Scegli una cartella di lavoro e clona il repository:

```bash
gh repo clone costaindustries-source/payroll-analizer
cd payroll-analizer
```

> Se preferisci non usare `gh` e hai già una chiave SSH configurata su GitHub: `git clone git@github.com:costaindustries-source/payroll-analizer.git`.

---

## 4. Verifica dei prerequisiti

Dalla cartella del progetto:

```bash
uv run payroll setup --check
```

La primissima volta questo comando impiega qualche secondo in più: `uv` scarica in automatico la versione di Python richiesta e installa le dipendenze della CLI (`typer`, `rich`...) in un ambiente virtuale locale (`.venv/`), senza che tu debba fare nulla.

Output atteso: una lista di controlli, tutti con un segno di spunta. I controlli sono:

| Controllo | Bloccante se manca? |
|---|---|
| `docker --version` | Sì |
| `docker compose version` | Sì |
| `git --version` | Sì |
| `uv --version` | No (stai già usando `uv` per lanciare questo comando) |
| Spazio disco libero ≥ 2 GiB | Sì |
| UID/GID utente = 1000:1000 (solo Linux) | No — su Windows non si applica |

Se qualcosa risulta bloccante, il comando te lo segnala chiaramente con il motivo: torna al punto 2 e sistemalo prima di proseguire.

---

## 5. Configurazione guidata (`payroll setup`)

```bash
uv run payroll setup --bootstrap
```

Questo comando fa **tutto in un colpo solo**: rilancia i controlli del punto 4, poi ti fa 4 domande (wizard), scrive un file di configurazione locale, e infine costruisce/avvia l'ambiente. Ecco cosa ti verrà chiesto:

1. **Nome macchina** — un'etichetta libera per riconoscere questo computer nei log (default: il nome host del computer). Premi Invio per accettare il default.
2. **Ruolo — `source` o `node`** — quasi sempre vuoi **`node`**: significa "questa macchina esegue l'app e si aggiorna da sola quando esce una nuova versione". Il ruolo `source` è riservato all'**unica** macchina da cui in futuro pubblicherai nuove versioni (`payroll release new`) — se non sai di cosa si tratta, scegli `node`.
3. **Porta host del database** — default `5432`. Cambiala solo se hai già un altro PostgreSQL in ascolto su quella porta sul tuo computer (in quel caso, ad esempio, `5433`).
4. **Giorni di retention dei log** e **numero di backup da conservare** — i default (90 giorni, 5 backup) vanno bene per iniziare, si possono cambiare in qualsiasi momento rilanciando `payroll setup`.

Se esiste già un file di configurazione (rilanci il comando una seconda volta), ti verrà chiesta conferma prima di sovrascriverlo.

Dopo le domande, il wizard chiede conferma per il **bootstrap** (build immagine + avvio database + creazione tabelle + test di verifica). Rispondi **sì**. Vedrai scorrere:

- il download/build dell'immagine Docker (qualche minuto la prima volta: scarica Python, Tesseract, Ghostscript e tutte le librerie — dai giri successivi è quasi istantaneo grazie alla cache);
- l'avvio di PostgreSQL, con attesa finché non è pronto;
- la creazione delle tabelle nel database (migration);
- un test di verifica automatico (**verrà saltato automaticamente** se non hai i PDF di esempio in `docs/payroll-test/` — è normale su un'installazione nuova, quei file non sono nel repository perché contengono dati retributivi reali).

Al termine, l'ambiente è pronto e il database è vuoto (schema creato, zero cedolini caricati).

---

## 6. Verificare che tutto funzioni

```bash
uv run payroll status
```

Output atteso: un riepilogo con il nome macchina, lo stato del container `db` (`Up ... (healthy)`), `0` documenti nel database, `0` file in coda in `input/`, e lo spazio disco libero.

Se hai a disposizione un PDF di cedolino Zucchetti reale, puoi fare una prova completa: copialo nella cartella `input/` (su Windows puoi anche trascinarlo lì con Esplora File, è una cartella normale sul disco) ed esegui:

```bash
docker compose run --rm app payroll-ingest process
```

Output atteso: un riepilogo tipo `1 file, 1 ok, 0 con anomalie, 0 da rivedere, 0 in errore`. Il PDF sparisce da `input/` e ricompare organizzato in `processed/<anno>/<mese>/`.

---

## 7. Uso quotidiano

```bash
# 1. Copia i PDF da elaborare in input/ (drag&drop da Esplora File su Windows, o cp/mv su Linux)

# 2. Elabora tutto il contenuto di input/, un file alla volta
docker compose run --rm app payroll-ingest process

# 3. (facoltativo) genera un export completo e versionato del database
docker compose run --rm app payroll-ingest export

# 4. (facoltativo) verifica quali anni/mesi sono completamente coperti
docker compose run --rm app payroll-ingest check-years
```

Il comando `process`:
- calcola l'hash di ogni PDF (un file già caricato con successo viene riconosciuto e saltato, mai duplicato);
- capisce se il PDF è testuale o scansionato e applica l'OCR solo se serve;
- riconosce il layout del cedolino ed estrae i dati;
- salva tutto nel database;
- sposta il PDF in `processed/<anno>/<mese>/` (oppure in `error/`, con un file `.json` a fianco che spiega cosa è andato storto — **un errore su un file non blocca gli altri**);
- scrive un log dettagliato in `logs/` per ogni esecuzione.

Per fermare/riavviare i servizi Docker:

```bash
docker compose stop        # ferma i container (i dati restano)
docker compose up -d db     # riavvia solo il database
docker compose down         # ferma e rimuove i container (il volume dati del database NON viene toccato)
```

---

## 8. Comandi utili da ricordare

| Comando | Cosa fa |
|---|---|
| `uv run payroll status` | Panoramica rapida: container, documenti per stato, coda `input/`, spazio disco |
| `uv run payroll version` | Versione installata (tag/commit), stato migration, versione Postgres |
| `docker compose run --rm app payroll-ingest process` | Elabora tutti i PDF in `input/` |
| `docker compose run --rm app payroll-ingest export` | Export completo del database in `export/` |
| `docker compose run --rm app payroll-ingest check-years` | Copertura per anno/mese, elenco anomalie |
| `uv run payroll db shell` | Apre una shell `psql` interattiva sul database |
| `uv run payroll db backup` | Backup verificato del database in `backups/` |
| `uv run payroll cleanup` | Mostra cosa si potrebbe ripulire (log/backup vecchi) senza cancellare nulla |
| `uv run payroll cleanup --apply` | Applica la pulizia sopra, con conferma |
| `uv run payroll update check` | Controlla se è disponibile una versione più recente |
| `uv run payroll update apply` | Aggiorna questa installazione all'ultima versione pubblicata |
| `uv run payroll help <comando>` | Guida dettagliata su un comando specifico |

Accesso diretto al database da un client SQL esterno (DBeaver, SQLTools, ecc.): host `localhost`, porta `5432` (o quella scelta nel wizard), utente/password/database `payroll`.

---

## 9. Risoluzione problemi

### Comuni a Windows e Linux

- **Il primo `uv run payroll ...` è lento**: normale, `uv` sta scaricando Python e le dipendenze. Dalle esecuzioni successive è quasi istantaneo.
- **`docker compose run --rm app ...` fallisce con un errore di connessione al database**: il container `db` non è ancora pronto o non è avviato. Esegui `docker compose up -d db` e attendi qualche secondo (verifica con `docker compose ps`, la colonna `STATUS` deve mostrare `healthy`).
- **Voglio ripartire da zero (cancellare tutti i dati e ricominciare)**: `docker compose down -v` (il flag `-v` cancella anche il volume dati — irreversibile, usalo solo se sei sicuro), poi rifai i punti 5-6.

### Solo Windows

- **Docker Desktop non parte / resta bloccato sull'icona animata**: verifica che la virtualizzazione sia abilitata nel BIOS/UEFI (di solito lo è già di default sui PC moderni) e che Windows sia aggiornato. Riavvia il computer.
- **"WSL 2 installation is incomplete" durante l'installazione di Docker Desktop**: Docker Desktop propone da solo un link per scaricare l'aggiornamento del kernel Linux di WSL2; segui il link, installa, riavvia Docker Desktop. Non serve configurare nessuna distribuzione Linux manualmente, resta tutto dietro le quinte.
- **PowerShell non riconosce `uv` o `gh` subito dopo l'installazione**: chiudi e riapri la finestra di PowerShell (il PATH viene aggiornato solo per le nuove sessioni).
- **Antivirus/Windows Defender rallenta molto le build Docker**: capita con alcuni antivirus di terze parti che scansionano ogni file scritto dal motore Docker. Se la build è insolitamente lenta (minuti invece di secondi dopo la prima volta), verifica le esclusioni consigliate da Docker Desktop in Impostazioni → Risorse.

### Solo Linux

- **`docker: unknown command: docker compose`**: il plugin Compose v2 non è installato. Verifica con `docker compose version`; se assente, installa `docker-compose-plugin` (vedi punto 2b) oppure usa il binario standalone `docker-compose` (v1) sostituendolo a `docker compose` in tutti i comandi di questa guida.
- **Errore di permessi (`docker: permission denied` sul socket)**: il tuo utente non è nel gruppo `docker`. Esegui `sudo usermod -aG docker "$USER"` e riavvia la sessione.
- **File creati con proprietario `root` nelle cartelle `input/processed/error/logs/export/work`**: non dovrebbe succedere (l'immagine esegue l'app con utente non privilegiato, UID/GID 1000, il default del primo utente su Debian/Ubuntu). Se il tuo utente ha UID/GID diverso, ricostruisci l'immagine con `docker compose build --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g) app`.
- **Errore "credential helper" durante `docker pull`/`docker compose build`** (es. `docker-credential-desktop.exe not found`): capita se `~/.docker/config.json` referenzia un helper credenziali di Docker Desktop per Windows non presente in un ambiente Linux puro (tipico se questa macchina è una WSL con un vecchio profilo condiviso). Soluzione: rimuovi o correggi la chiave `"credsStore"` in `~/.docker/config.json`.

---

## Licenze e costi: nessun abbonamento richiesto

**Verdetto sintetico: per l'uso previsto (tool personale/interno, mai distribuito a terzi, mai esposto come servizio a clienti esterni) tutto lo stack è gratuito, nessun abbonamento né licenza commerciale richiesta.** Verificato componente per componente (fonti ufficiali: PyPI, GitHub, siti dei progetti):

| Componente | Licenza | Gratuito per questo uso? |
|---|---|---|
| Python 3.14 | PSF License v2 (permissiva) | ✅ Sì |
| PostgreSQL 17 | PostgreSQL License (permissiva, tipo BSD/MIT) | ✅ Sì |
| Docker Engine + Compose (Linux) / Docker Desktop (Windows, uso personale) | Apache 2.0 / EULA Docker Desktop gratuita per uso personale | ✅ Sì |
| Tesseract OCR | Apache 2.0 | ✅ Sì |
| OCRmyPDF | MPL-2.0 | ✅ Sì |
| SQLAlchemy, Alembic | MIT | ✅ Sì |
| psycopg (driver PostgreSQL) | LGPL-3.0 | ✅ Sì (nessun obbligo per uso interno non distribuito) |
| Typer, Rich, Pydantic, structlog, pdfplumber, ecc. | MIT / BSD / Apache-2.0 | ✅ Sì |
| PyMuPDF (estrazione PDF) | **Dual: AGPL-3.0 oppure licenza commerciale Artifex** | ✅ Sì, con una condizione (vedi sotto) |
| Ghostscript, Poppler-utils, unpaper (usati da OCRmyPDF) | AGPL-3.0 / GPL-2.0+ | ✅ Sì, con la stessa condizione |
| fpdf2, img2pdf, pi-heif (dipendenze minori) | LGPL-3.0 | ✅ Sì (nessun obbligo per uso interno) |

### L'unica condizione da tenere a mente

**PyMuPDF** e **Ghostscript** sono distribuiti sotto licenza **AGPL-3.0**, con un'alternativa commerciale a pagamento (Artifex Software) per chi non vuole/può rispettare l'AGPL. La differenza pratica:

- **Uso gratuito (AGPL) sufficiente quando**: il tool resta per uso personale/interno, non viene distribuito a terzi e non viene esposto come servizio via rete a utenti esterni. **Questo è esattamente lo scenario di `payroll-analizer`**: batch personale, container Docker locale, nessuna distribuzione, nessuna API pubblica.
- **Licenza commerciale a pagamento necessaria solo se in futuro**: si distribuisse il software (o un'immagine Docker con dentro PyMuPDF/Ghostscript) a soggetti terzi, oppure lo si esponesse come servizio SaaS/API a utenti esterni, senza voler rilasciare il codice sotto AGPL.

Ghostscript/Poppler/unpaper sono inoltre invocati solo come **processi esterni** (subprocess) da OCRmyPDF, non collegati al codice Python: questo rafforza ulteriormente che non ci sono obblighi di licenza per l'uso descritto in questa guida.

**Docker Desktop** (solo Windows) è gratuito per uso personale, per piccole imprese (meno di 250 dipendenti e meno di 10 milioni di dollari di fatturato annuo) e per scopi educativi/open source; richiede un abbonamento a pagamento solo per l'uso professionale in aziende più grandi — verifica la propria situazione sui [termini ufficiali Docker](https://www.docker.com/pricing/) se rilevante.

Se in futuro cambia il perimetro d'uso (distribuzione esterna, SaaS a terzi), va ripetuta questa valutazione.

---

## Riferimenti

- Riferimento rapido comandi (per chi ha già installato tutto): [`README.md`](README.md)
- Piano tecnico completo: [`PIANO_TECNICO.md`](PIANO_TECNICO.md)
- Processo di rilascio (per chi pubblica nuove versioni, ruolo `source`): [`docs/RELEASE_PROCESS.md`](docs/RELEASE_PROCESS.md)
- Codice applicazione: `packages/payroll-ingest/src/payroll_ingest/`
- Codice CLI operativa: `packages/payroll-cli/src/`
