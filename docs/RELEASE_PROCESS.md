# Processo di rilascio

## Modello degli ambienti

| Ambiente | Ruolo | Dove | Come esegue |
|---|---|---|---|
| **Ubuntu** (questa distro WSL) | Sviluppo/dev | `~/DEV/VSCode/repo/payroll-analizer` | `.venv` locale + Docker |
| **GitHub** (`costaindustries-source/payroll-analizer`, privato) | Fonte di verità del codice | remote `origin` | — |
| **Debian** (altra distro WSL) | Produzione reale (unico ambiente che elabora i cedolini veri) | `~/app/payroll-analizer` | solo Docker (nessun Python/Postgres sull'host) |

Le due distro WSL **non condividono il filesystem**: si raggiungono da Ubuntu
con `/mnt/c/Windows/System32/wsl.exe -d Debian -- <comando>` (richiede
autorizzazione esplicita per ogni sessione — non è un'azione da automatizzare
di iniziativa). Condividono invece la rete locale (`127.0.0.1`), ma questo
processo non ne ha bisogno: la promozione del codice passa sempre da GitHub.

**Regola cardine**: Debian esegue sempre un **tag annotato**, mai un commit
sciolto o un branch in movimento — stesso principio del rilascio PROD di
bp-revo-parametric (deploy da tag, non da branch).

## Dati reali: mai su GitHub

`docs/payroll-test/*.pdf` (6 cedolini reali usati come fixture di
regressione, con CF e importi retributivi veri) e qualunque file in
`input/processed/error/logs/export/work/.env` sono in `.gitignore` e non
vanno **mai** committati. Se un giorno un `git status` li mostra come "nuovo
file", fermarsi e capire perché prima di fare `git add`.

## Configurazione specifica per ambiente

`docker-compose.yml` è identico su ogni ambiente e va in git. Qualunque
override locale (es. porta host del DB diversa per evitare collisioni con
altri Postgres sulla stessa macchina) va in `docker-compose.override.yml`
(non versionato — v. `docker-compose.override.yml.example`), mai modificato
direttamente in `docker-compose.yml`: altrimenti un `git checkout` di un tag
successivo lo sovrascrive silenziosamente (scoperto proprio così su Debian,
porta 5433 vs 5432 di git, durante il primo bootstrap di questo processo —
impatto limitato perché l'app si connette al DB via rete Docker interna
(`db:5432`), non tramite la porta pubblicata sull'host, ma rompe comunque
client esterni come DBeaver/SQLTools se non corretto).

## Versionamento

Tag SemVer (`vX.Y.Z`) sul branch `main`:
- **patch** (`v0.1.1`): fix di bug/parsing, nessuna modifica a schema DB o comportamento osservabile.
- **minor** (`v0.2.0`): nuove funzionalità (nuovo template, nuovo comando CLI, ecc.).
- **major** (`v1.0.0`): riservato a un cambio di schema DB non retrocompatibile (richiede una migration Alembic).

## Procedura standard: `scripts/release.sh <versione>`

1. **Preflight** — working tree pulito, branch `main`.
2. **Smoke test locale** (`scripts/smoke_test.py`) sui 6 campioni di
   `docs/payroll-test/` — deve passare prima di poter taggare.
3. **Tag + push** — crea il tag annotato e lo pusha su GitHub insieme a `main`.
4. **Gate di conferma** — chiede esplicitamente se procedere al deploy su
   Debian. Rispondere "no" lascia il tag su GitHub senza toccare l'ambiente
   reale (utile per rilasci "pronti ma non ancora promossi").
5. **Deploy su Debian** — `git fetch --tags && git checkout <tag>` seguito da
   `docker compose build app`.
6. **Smoke test post-deploy** — stesso script, eseguito dentro il container
   appena ricostruito su Debian, contro i campioni reali montati in `/data/docs`.
   Se fallisce, propone rollback automatico al tag precedente.
7. **Log** — appende una voce a `RELEASE_LOG.md` e la committa/pusha.

## Rollback manuale

```bash
scripts/release.sh --rollback v0.1.0
```
Riporta Debian al tag indicato e ricostruisce l'immagine. Non tocca GitHub
(il tag "difettoso" resta nella storia, semplicemente non più deployato).

## Checklist pre-rilascio (da tenere a mente, non solo automatizzata)

- [ ] Ho verificato la modifica anche sui campioni **non ufficiali** rilevanti (es. cedolini che avevano fallito prima), non solo sui 6 di regressione?
- [ ] Se la modifica tocca l'estrazione di importi, ho controllato a mano almeno un caso reale prima di considerarla affidabile?
- [ ] Il messaggio di release spiega il *perché*, non solo il *cosa* (finisce in `CHANGELOG.md`/`RELEASE_LOG.md`, letto a distanza di mesi)?
- [ ] Se cambia lo schema DB, la migration Alembic è nel commit ed è stata testata con `alembic upgrade head` su un DB pulito?
- [ ] Se cambia la *major version* di Postgres in `docker-compose.yml` (cambia anche il nome del volume dati), ogni ambiente deve eseguire `scripts/upgrade-postgres.sh backup` **prima** di aggiornare il checkout e `... restore` **dopo** — v. sezione README "Aggiornamento major version di PostgreSQL". Un patch/minor bump (es. 17.5 -> 17.6, stesso volume) non ne ha bisogno.
