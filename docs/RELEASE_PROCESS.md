# Processo di rilascio

Fonte di verità unica per come si pubblica e si distribuisce una versione.
Ogni altro documento (`README.md`, `RELEASE_LOG.md`,
`docs/CLI_REDESIGN_PROPOSAL.md`) rimanda qui invece di ripetere la procedura.

## Modello degli ambienti

| Ambiente | Ruolo | Dove | Come esegue |
|---|---|---|---|
| **Ubuntu** (questa distro WSL) | `source`: unica macchina che pubblica | `~/DEV/VSCode/repo/payroll-analizer` | `.venv` locale + Docker |
| **GitHub** (`costaindustries-source/payroll-analizer`, privato) | Fonte di verità del codice | remote `origin` | — |
| **Debian** (altra distro WSL) | `node`: produzione reale, unico ambiente che elabora i cedolini veri | `~/app/payroll-analizer` | solo Docker (nessun Python/Postgres sull'host) |

Le due distro WSL **non condividono il filesystem**: si raggiungono da Ubuntu
con `/mnt/c/Windows/System32/wsl.exe -d Debian -- <comando>` (richiede
autorizzazione esplicita per ogni sessione — non è un'azione da automatizzare
di iniziativa). Ogni macchina si aggiorna da sé via `git`/GitHub: non serve
condividere rete o filesystem tra le distro per rilasciare.

**Regola cardine**: ogni nodo esegue sempre un **tag annotato**, mai un
commit sciolto o un branch in movimento (`payroll update apply` lo impone:
lavora solo su tag SemVer, mai su un commit di `main` — stesso principio del
rilascio PROD di bp-revo-parametric, deploy da tag non da branch).

## Dati reali: mai su GitHub

`docs/payroll-test/*.pdf` (6 cedolini reali usati come fixture di
regressione, con CF e importi retributivi veri), `docs/new-templates/*.pdf`
(cedolini reali di riferimento per nuovi template) e qualunque file in
`input/processed/error/logs/export/work/.env` sono in `.gitignore` e non
vanno **mai** committati. Se un giorno un `git status` li mostra come "nuovo
file", fermarsi e capire perché prima di fare `git add`.

## Configurazione specifica per ambiente

`docker-compose.yml` è identico su ogni ambiente e va in git. Qualunque
override locale (es. porta host del DB diversa per evitare collisioni con
altri Postgres sulla stessa macchina) va in `docker-compose.override.yml`
(non versionato). `payroll setup` lo genera da solo in base alla porta scelta
durante il wizard e non lo tocca mai se esiste già; va scritto a mano solo in
casi non coperti dal wizard (v. `docker-compose.override.yml.example`). Mai
modificare `docker-compose.yml` direttamente per un bisogno locale: un
`update apply`/checkout di un tag successivo lo sovrascriverebbe
silenziosamente. Le liste (`ports`, `volumes`, ...) vanno sempre con il
merge-tag `!override`, perché docker compose le concatena tra i due file
invece di sostituirle di default (issue #14).

## Versionamento

Tag SemVer (`vX.Y.Z`) sul branch `main`. **Regola cardine: ogni fix deve
essere installabile con `payroll update apply`**, che lavora solo su tag
locali (mai su un commit sciolto di `main`) — quindi ogni bug chiuso richiede
una nuova release, non solo un commit+push.

- **patch** (`v0.1.1`): zero impatto osservabile — solo documentazione/commenti,
  refactor verificato a diff zero, bump di dipendenze senza cambio di
  comportamento.
- **minor** (`v0.2.0`): **ogni bug fix chiuso** (regola esplicita, non lo
  standard SemVer) + funzionalità retrocompatibili (nuovo template, nuovo
  comando CLI, migration puramente additiva).
- **major** (`vX.0.0`): riservato a cambi che `update apply` non può gestire
  da solo in sicurezza — migration non retrocompatibile, cambio schema di
  `payroll.local.toml`, modifiche a `updater.py`/`releaser.py` stessi,
  comando/flag CLI rimosso o con semantica cambiata.

L'unica eccezione è stata una tantum: il salto da `0.y.z` a `1.0.0`
(`v1.0.0`, 2026-07-15) ha usato il marcatore SemVer standard di "primo
rilascio stabile" invece di una minor, perché quella release rendeva il
progetto installabile in modo pulito su un nodo reale (issue #14) dopo che
l'app era già in produzione su dati veri da tempo. Non si ripete: da qui in
avanti vale solo lo schema sopra.

## 1. Pubblicare una release (`payroll release new`, solo su Ubuntu/`role=source`)

```bash
uv run payroll release new vX.Y.Z -m "messaggio"
```

1. Preflight: branch `main`, working tree pulito, tag non esistente.
2. Smoke test locale sui 6 campioni di `docs/payroll-test/` — **obbligatorio**,
   a differenza di `setup`/`update apply` qui non viene mai saltato.
3. Promuove `## [Non rilasciato]` di `CHANGELOG.md` a `## [vX.Y.Z] - <data>`
   (lasciandone una vuota in cima per il prossimo giro) e la committa.
4. Chiede conferma esplicita.
5. Crea il tag annotato e pusha `main` + il tag su GitHub.
6. Crea anche una GitHub Release con le note del changelog appena promosso
   (via `gh`, non bloccante: se fallisce logga solo un avviso).

**Non deploya nulla.** La promozione sulle macchine è compito di ciascun nodo
con `payroll update apply` (punto 2). `payroll release list` mostra la storia
dei tag pubblicati (locale + verifica su origin).

## 2. Aggiornare un nodo (`payroll update apply`, su ogni macchina `role=node`)

```bash
uv run payroll update check          # confronta il tag locale con l'ultimo pubblicato
uv run payroll update apply [--to vX.Y.Z]
```

1. `git fetch --tags`, risolve il target (ultimo tag SemVer, o `--to`). Se
   già lì: esce senza fare nulla.
2. Blocca se il working tree non è pulito. Chiede sempre conferma esplicita
   prima del checkout.
3. Diff di `docker-compose.yml` tra tag corrente e target: se cambia il nome
   del volume dati Postgres, esegue da solo un `db backup` prima del checkout.
4. `git checkout <tag>`.
5. Il resto della sequenza (build immagine, eventuale `db restore`, `alembic
   upgrade head`, smoke test) gira col codice del *nuovo* tag appena
   installato, non con quello del processo che ha avviato l'aggiornamento.
6. Se lo smoke test fallisce, propone il rollback automatico al tag
   precedente. Il volume Postgres precedente non viene mai cancellato
   automaticamente.
7. Traccia l'esito in `logs/updates.log` (locale alla macchina, non
   versionato).

## 3. Rollback (`payroll rollback <tag>`)

Checkout del tag indicato + rebuild immagine. Non tocca mai dati o volumi.

## Nuovo nodo

`payroll setup` (wizard prerequisiti + config + bootstrap) — procedura
completa in [`INSTALL-INFO.md`](../INSTALL-INFO.md), non ripetuta qui.

## Percorso legacy: `scripts/release.sh`, `RELEASE_LOG.md`

`scripts/release.sh` (modello push, Ubuntu spinge il deploy su Debian via
`wsl.exe`) e `RELEASE_LOG.md` (log scritto solo da quello script) precedono
la CLI `payroll` e oggi duplicano quanto sopra. Restano nel repo **solo**
come rete di sicurezza finché `payroll update apply` non ha eseguito con
successo un aggiornamento reale di Debian a partire da un tag effettivamente
più vecchio (non un `git pull` manuale come per il fix di #14/v1.0.0, dove
Debian era già allineato prima che il tag esistesse). Raggiunto quel
collaudo, vanno rimossi (v. `docs/CLI_REDESIGN_PROPOSAL.md` §8) e questa
sezione va cancellata: non usarli per nuove release, non aggiungerci logica.

## Checklist pre-rilascio (da tenere a mente, non solo automatizzata)

- [ ] Ho verificato la modifica anche sui campioni **non ufficiali** rilevanti (es. cedolini che avevano fallito prima), non solo sui 6 di regressione?
- [ ] Se la modifica tocca l'estrazione di importi, ho controllato a mano almeno un caso reale prima di considerarla affidabile?
- [ ] Il messaggio di release spiega il *perché*, non solo il *cosa* (finisce in `CHANGELOG.md`, letto a distanza di mesi)?
- [ ] Se cambia lo schema DB, la migration Alembic è nel commit ed è stata testata con `alembic upgrade head` su un DB pulito?
- [ ] Se cambia la *major version* di Postgres in `docker-compose.yml` (cambia anche il nome del volume dati), `payroll update apply` lo rileva da solo e fa il backup prima del checkout — verificare comunque che `payroll db backup` sia stato eseguito con successo prima di considerare il rilascio concluso. Un patch/minor bump (es. 17.5 -> 17.6, stesso volume) non ne ha bisogno.
