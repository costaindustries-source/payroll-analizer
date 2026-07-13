# Piano tecnico — Payroll Ingestion (cedolini PDF → DB strutturato)

## Context

Serve un'applicazione enterprise **batch** che importa buste paga in PDF, ne estrae i dati e li salva in un database strutturato, con tracciamento idempotente (hash SHA-256), stato di lavorazione per documento, elaborazione indipendente per file e export completo/versionato della base dati. Il progetto vive in `repo/payroll-analizer/`. Il frontend futuro (`FrontEnd/costaindustries`) è **fuori scope**: qui si progetta solo ingestion, salvataggio ed export.

Il piano è **fondato sull'analisi dei PDF reali** presenti in `doc/payroll-test/` (il requirements cita `docs`, ma la cartella reale è `doc/` — vedi §5). Nessun campo payroll è inventato: il modello dati deriva da ciò che è realmente emerso dai 6 cedolini analizzati.

> Nota metodo: i PDF usano un font subset con encoding a offset; l'estrazione grezza via zlib+regex ha permesso di leggere le **label** (struttura) ma non i **valori numerici** in modo affidabile. Questo è un input di design chiave (§9): serve estrazione **layout-aware con ToUnicode CMap**, non lettura lineare del testo.

---

## 1. Sintesi della soluzione

Pipeline batch a step, un documento alla volta e indipendente, resiliente ai fallimenti:

`/input` → **hash SHA-256 + dedup** → **classificazione PDF** (testuale / PDF-A / scansionato) → **estrazione** (layer testo posizionale; OCR solo se manca il layer) → **parsing per template** (riconoscimento datore/layout Zucchetti) → **mapping campo→modello dati** con classificazione del dato (certo / opzionale / derivato / grezzo / non riconosciuto) → **validazione + quadrature** → **persistenza transazionale** su PostgreSQL (incluso raw JSONB) → spostamento file in `/processed` o `/error` → **export versionato**.

Ogni documento è una unità di lavoro isolata con macchina a stati; un PDF in errore viene isolato in `/error` senza bloccare gli altri. Tutto ciò che viene riconosciuto è tipizzato in tabelle; tutto ciò che non è riconosciuto viene comunque conservato come dato grezzo per rianalisi futura (nessuna perdita di informazione).

## 2. Stack tecnologico consigliato (scelta unica + motivazione)

**Scelta: Python 3.12.**

- L'ecosistema PDF/OCR di Python è nettamente il più maturo per questo dominio: `pdfplumber` (estrazione **posizionale** parole+coordinate, ideale per la griglia label/valore dei cedolini Zucchetti), `PyMuPDF` (fitz) come motore veloce e per rilevare la presenza del text-layer, `OCRmyPDF`+`Tesseract` (lingua `ita`) per i soli PDF scansionati.
- Coerenza col monorepo: PostgreSQL + **Alembic** per le migration sono già standard di workspace (progetti Java e Python), riducendo attrito operativo e di competenze.
- Batch semplice e robusto: CLI con `Typer`/`argparse`, orchestrazione con codice esplicito (nessun framework pesante necessario).

Componenti consigliati:

| Ambito | Scelta |
|---|---|
| Linguaggio/runtime | Python 3.12 |
| PDF testo | `pdfplumber` (primario, posizionale) + `PyMuPDF` (detect layer + fallback) |
| OCR (solo scansionati) | `OCRmyPDF` + `Tesseract` (`ita`) |
| DB access / ORM | `SQLAlchemy 2.x` |
| Migration | `Alembic` (standard workspace) |
| CLI batch | `Typer` |
| Validazione DTO | `Pydantic v2` |
| Logging | `structlog` (JSON strutturato) |
| Dipendenze/packaging | `uv` (o Poetry) |
| Container | Docker (immagine con Tesseract `ita` preinstallato) |

## 3. Architettura logica

Struttura a moduli con responsabilità nette (una direzione di dipendenza: orchestratore → servizi → repository → DB):

- **CLI / Runner batch** — punto d'ingresso, scansione `/input`, ciclo per-documento, exit code aggregato.
- **Hashing & Dedup** — SHA-256 sui byte del file; consulta il registro documenti.
- **PDF Classifier** — testuale vs PDF/A vs scansionato (presenza/qualità text-layer).
- **Extractor** — testo posizionale (parole + bbox) o OCR; produce un "documento estratto" intermedio (testo + coordinate + metadati).
- **Template Recognizer** — identifica emittente/layout (es. cedolino Zucchetti REVO vs ELBA) e seleziona il profilo di mapping.
- **Parser / Field Mapper** — dal testo posizionale ai campi tipizzati, con classificazione del dato.
- **Validator** — controlli di quadratura e coerenza; genera anomalie.
- **Persistence (Repository)** — scrittura transazionale sul modello dati + raw.
- **File Mover** — sposta il PDF in `/processed` o `/error`.
- **Exporter** — dump completo versionato della base dati.
- **Logging/Audit** — log batch + log per documento + tabella di audit.

## 4. Analisi dei payroll in `doc/`

Fase obbligatoria, già avviata su 6 campioni reali. Esito dell'analisi campione e attività da consolidare in implementazione:

**Censimento (fatto sui campioni):** `202112.pdf`, `202208.pdf`, `202313.pdf`, `202409.pdf`, `04.pdf`, `05.pdf` — tutti PDF 1.4, 1 pagina, ~50 KB, stream deflate.

**Tipologia:** tutti **testuali/vettoriali** con font subset embedded (encoding a offset, ToUnicode necessario). **Nessuno scansionato** nei campioni → **OCR non richiesto** per questi file; va comunque implementato per il caso generale.

**Testo campione estratto:** confermata leggibilità delle label; i valori numerici richiedono estrazione via CMap/posizionale (vedi §9).

**Campi ricorrenti individuati (tutti i cedolini):** datore (ragione sociale, sede, INAIL Aut/Del/Sede/Nr posizione), dipendente (cognome+nome, codice fiscale, qualifica `IMPF`/`Business L`, `CLASSE`, `STIPENDIO`), periodo (mese/anno), voci retributive con `GG`/`ORE`, `Contributo IVS`, `Imponibile IRPEF`, `IRPEF lorda`, `Detrazioni lav dip`, `Ritenute IRPEF`, `Addizionale regionale` (con regione, es. VENETO), blocco **TFR** (Retribuzione utile TFR, Quota TFR a Fondi, Rivalutaz, Imp rival, Quota anno, Anticipi), imponibili riepilogo (`Imp INPS`, `Imp INAIL`, `Imp IRPEF`), ratei ferie/permessi (Maturato/Goduto/Residuo/Residuo AP), banca+`IBAN`, domicilio/residenza, "Prossimo passaggio in classe".

**Campi opzionali (solo alcuni mesi):** Anticipo Festività, Ferie Godute, Ticket elettronico, Polizza RSMO, Spese carta di credito, Malattia ditta, Premi, Vendita Azioni, Mensilità aggiuntiva/13ª (`202313`), `F.do sostegno reddito`, `Contributo Previp`/`Previp C Ditta`, `Ctr prev compl deducib`.

**Layout diversi rilevati:** stesso template Zucchetti ma (a) **due datori** nel tempo — ELBA (Milano) fino al 2022, REVO (Verona) dal 2023; (b) **cedolino ordinario vs mensilità aggiuntiva** (`202313` = 13ª/AGG) con set di righe differente; (c) numero e tipo di righe variabili di mese in mese.

**Mapping campo→modello dati:** definito come profilo per "famiglia Zucchetti" (§6/§7); le voci retributive vanno gestite come righe dinamiche a dizionario di causali, non come colonne fisse.

**Casi limite/anomalie da gestire:** cambio datore per lo stesso dipendente; mensilità aggiuntiva; righe/causali non mappate; regione addizionale variabile; assenza di alcune sezioni; PDF futuri potenzialmente scansionati o di altro emittente; mancata quadratura netto/imponibili.

> Attività da eseguire in implementazione (non solo sui 6 campioni): script diagnostico che per ogni PDF logga tipo, presenza text-layer, font/encoding, n. parole estratte, template riconosciuto, campi mappati vs non mappati — output in `/logs` come inventario CSV.

## 5. Struttura cartelle proposta

Migliorata rispetto a quella indicata. **Attenzione**: la cartella reale con gli esempi è `doc/` (non `docs/`); allineare a `docs/` o mantenere `doc/` in modo esplicito nella config.

```text
/docs        -> esempi payroll reali (attuale: doc/payroll-test/) — read-only, per analisi/regressione
/input       -> PDF da elaborare
/work        -> area temporanea per-documento durante l'elaborazione (evita elaborazioni parziali visibili)
/processed   -> PDF elaborati correttamente (sottocartelle per anno/mese)
/error       -> PDF in errore (accanto: <file>.error.json con causa)
/logs        -> log batch (run) + log per documento
/export      -> export completo DB, versionato (una sottocartella per export)
/config      -> profili di template/mapping e configurazione batch
```

## 6. Modello dati database

DB: **PostgreSQL 16** (vedi §2). Principio: dati **certi** tipizzati in colonne; **grezzi** in JSONB; **derivati** calcolati e marcati; **non riconosciuti** conservati. Ogni valore riconosciuto porta un flag di classificazione.

Tabelle principali (nomi indicativi):

- **company** — datore: ragione sciale, sede/indirizzo, INAIL (autorizzazione n., del, sede, posizione), P.IVA/CF se presente. *(ELBA, REVO)*
- **employee** — dipendente: cognome, nome, codice fiscale (naturale key), qualifica, classe/livello. Anagrafica indipendente dal datore.
- **employment** — rapporto dipendente↔azienda con validità temporale (gestisce il cambio ELBA→REVO).
- **payroll_document** — un cedolino: `sha256` (UNIQUE), nome file originale, path processed/error, `status`, template riconosciuto, timestamp, fk employee/company/period, checksum pagine, versione parser.
- **payroll_period** — mese/anno, tipo (`ordinario` | `mensilita_aggiuntiva`/13ª | `conguaglio`), mese variabili.
- **pay_line** — righe retributive (dinamiche): codice/descrizione causale, `GG`, `ORE`, base/quota, competenza, trattenuta, segno, `is_recognized`, categoria (retribuzione/assenza/rimborso/benefit/altro). Cardinalità N per documento.
- **contribution** — contributi (IVS, Previp, Previp C Ditta, F.do sostegno reddito, ctr prev compl deducib): tipo, imponibile, aliquota, importo, carico (dipendente/ditta).
- **tax** — fiscale: imponibile IRPEF, IRPEF lorda, detrazioni lav dip, ritenute, addizionale regionale (regione), addizionale comunale, IRPEF pagata.
- **deduction** — trattenute non contributive/non fiscali.
- **reimbursement** — rimborsi (es. spese carta di credito, ticket se a rimborso).
- **benefit** — benefit/fringe (es. Polizza RSMO, ticket, azioni), con valore e imponibilità.
- **tfr** — blocco TFR: retribuzione utile, quota a fondi, rivalutazione, imponibile rival, quota anno, anticipi, residuo.
- **leave_balance** — ratei ferie/permessi/ex festività: maturato, goduto, residuo, residuo AP, ORE/GG.
- **payroll_totals** — totali/derivati: imponibile INPS, INAIL, IRPEF, totale competenze, totale trattenute, **netto in busta**, arrotondamenti, IBAN/banca di accredito.
- **anomaly** — anomalie per documento: tipo, severità, messaggio, campo coinvolto, valori attesi/rilevati.
- **raw_extraction** — grezzo: testo completo, parole+bbox (JSONB), righe non mappate, metadati font/encoding, esito OCR.
- **processing_log / audit_event** — audit append-only per documento (vedi §12).
- **schema_version / export_manifest** — versionamento schema ed export (§13).

**Relazioni:** `payroll_document` è l'aggregato centrale (1→N verso pay_line/contribution/tax/deduction/reimbursement/benefit/anomaly, 1→1 verso tfr/payroll_totals/raw_extraction; N→1 verso employee, company, period). `employment` lega employee↔company nel tempo.

**Indici/vincoli:**
- `payroll_document.sha256` **UNIQUE** (idempotenza, §10).
- UNIQUE logico `(employee_id, company_id, period, tipo)` per intercettare duplicati "semantici" (stesso cedolino re-inviato con altro nome file) → come vincolo o come anomalia.
- `employee.codice_fiscale` UNIQUE.
- Indici su `payroll_document.status`, `period`, FK.
- CHECK su `status` (enum), su segni/importi coerenti; NOT NULL solo sui campi realmente sempre presenti (certi).
- GIN su colonne JSONB grezze.

## 7. DTO principali (descrittivi)

- **RawExtractedDocument** — output dell'extractor: pagine, parole con bbox, testo completo, flag OCR, font/encoding, metriche qualità.
- **RecognizedTemplate** — emittente/layout riconosciuto + profilo di mapping selezionato.
- **PayrollDocumentDTO** — aggregato mappato: header (azienda, dipendente, periodo), liste (righe, contributi, tasse, trattenute, rimborsi, benefit), TFR, ratei, totali, anomalie, riferimento al raw.
- **FieldValue<T>** — wrapper con: valore tipizzato, `classification` (certo | opzionale | derivato | grezzo | non_riconosciuto), sorgente (bbox/label), confidence.
- **ProcessingResult** — esito per documento: stato finale, anomalie, destinazione file, tempi.
- **ExportManifest** — descrittore export (§13).

Tutti validati con Pydantic v2; la classificazione del dato è di primo livello nel DTO, non un dettaglio.

## 8. Flusso batch end-to-end

1. **Avvio run**: crea `run_id`, apre log di run in `/logs`, elenca i PDF in `/input`.
2. **Per ogni documento (isolato, try/except individuale):**
   a. Calcola **SHA-256**; se già presente con stato terminale → skip (dedup) e log.
   b. Registra `payroll_document` in stato `RECEIVED`; sposta in `/work`.
   c. **Classifica** PDF; se scansionato → OCR.
   d. **Estrai** testo posizionale → `RawExtractedDocument`; salva sempre il raw.
   e. **Riconosci template**; se ignoto → stato `NEEDS_REVIEW` + anomalia, ma prosegui con best-effort.
   f. **Mappa** campi → `PayrollDocumentDTO` con classificazione dato.
   g. **Valida/quadra**; registra anomalie (non necessariamente bloccanti).
   h. **Persisti** in transazione unica (aggregato + raw + anomalie).
   i. Sposta PDF in `/processed/AAAA/MM`; stato `PROCESSED` (o `PROCESSED_WITH_ANOMALIES`).
3. **In caso di errore** sul singolo: rollback DB del documento, sposta in `/error` con sidecar `<file>.error.json`, stato `FAILED`, log dedicato; **il ciclo continua**.
4. **Chiusura run**: riepilogo (totali/ok/anomalie/errori/skip) nel log di run; exit code non-zero se ci sono errori, senza mai aver interrotto gli altri.
5. **Export** (§13) eseguibile come comando separato on-demand o a fine run.

## 9. Strategia parsing/OCR

- **Detect layer testo**: via PyMuPDF conta caratteri/parole estraibili per pagina. Se sopra soglia → **percorso testuale**; se ~0 → **scansionato → OCR**.
- **Percorso testuale (caso dei campioni)**: estrazione **posizionale** con `pdfplumber` (parole + bbox), usando la **ToUnicode CMap** del font per la decodifica corretta (i campioni hanno font con encoding a offset: la lettura lineare sballa i numeri — confermato in analisi). Ricostruzione della griglia label→valore per **colonna/coordinate**, non per ordine di flusso.
- **PDF/A**: trattato come testuale (ha layer testo); nessuna gestione speciale oltre ai metadati.
- **OCR (solo se manca il layer)**: `OCRmyPDF` con `Tesseract` lingua `ita`; genera un PDF con layer testo e si rientra nel percorso testuale posizionale. Marcare il documento come `source=OCR` (confidence inferiore).
- **Template-driven mapping**: un profilo per famiglia (Zucchetti) definisce ancore/etichette e la posizione relativa dei valori; il recognizer sceglie il profilo dal contenuto (ragione sociale/marcatori). Profili in `/config`, versionati.
- **Righe dinamiche**: le voci retributive sono estratte come lista aperta (causale + GG/ORE/importi); quelle non nel dizionario causali → `is_recognized=false` ma persistite.

## 10. Strategia idempotenza tramite hash

- **SHA-256 sui byte del file** calcolato all'ingresso; salvato in `payroll_document.sha256` con **vincolo UNIQUE**.
- Prima di elaborare: lookup per hash. Se esiste con stato **terminale positivo** (`PROCESSED`) → skip idempotente. Se esiste in `FAILED` → riprocessa (reprocess consentito) tracciando il tentativo.
- **Dedup semantico** aggiuntivo: chiave logica `(codice_fiscale, azienda, periodo, tipo)` per intercettare lo **stesso cedolino con nome file diverso** → gestito come anomalia/decisione, non silenziosamente.
- La UNIQUE su hash rende l'intera pipeline **rieseguibile** senza doppioni: re-run della stessa `/input` non crea duplicati.

## 11. Gestione errori per documento

- **Isolamento totale**: ogni documento in un blocco protetto; un'eccezione non propaga al batch.
- **Transazione per documento**: persistenza atomica; su errore, rollback del solo documento.
- **Classificazione errori**: estrazione, OCR, template ignoto, mapping, validazione, DB. I "soft" (template ignoto, quadratura mancata) → `NEEDS_REVIEW`/anomalia + persistenza best-effort; gli "hard" (file corrotto, PDF illeggibile) → `FAILED` in `/error`.
- **Sidecar in `/error`**: `<file>.error.json` con tipo errore, stacktrace sintetico, fase, `run_id`, hash.
- **Nessuna perdita**: anche in fallimento parziale si salva il `raw_extraction` quando disponibile.
- **Reprocessing**: i file in `/error` possono essere reintrodotti in `/input`; l'hash evita doppioni sui già andati a buon fine.

## 12. Logging e audit

- **Log strutturato JSON** (`structlog`) con `run_id`, `document_id`, `sha256`, fase, esito.
- **Due livelli di file in `/logs`**: log di **run** (riepilogo batch) e log **per documento**.
- **Audit DB** (`audit_event`, append-only): transizioni di stato, versione parser/template usati, chi/quando (batch user), export eseguiti. Serve tracciabilità enterprise e ricostruzione storica.
- **Metriche di run**: n. processati/anomalie/errori/skip, tempi per fase — nel log di chiusura run.
- Niente dati sensibili in chiaro oltre il necessario; log a livello appropriato (CF/IBAN mascherati nei log applicativi, integrali solo in DB).

## 13. Export completo database

- **Obiettivo**: export completo, **versionato** e **reimportabile** da altri sistemi in futuro.
- **Formato primario portabile**: bundle in `/export/<timestamp>_<schema_version>/` contenente:
  - dati in **JSONL per tabella** (portabile, indipendente dal motore) + opzionale **CSV** per consumo umano;
  - `manifest.json`: `schema_version`, versione app/parser, data, conteggi per tabella, hash del contenuto, ordine di reimport (rispetto FK);
  - opzionale **dump logico PostgreSQL** (`pg_dump`) per ripristino tecnico rapido.
- **Versionamento schema**: tabella `schema_version` allineata alle migration Alembic; ogni export dichiara la versione → reimport futuro sa quali trasformazioni applicare.
- **Reimportabilità**: l'ordine e le chiavi naturali (hash documento, CF) nel manifest consentono un import idempotente in un altro sistema.
- **Grezzo incluso**: l'export contiene anche `raw_extraction`, così un futuro sistema può rifare il parsing senza i PDF.

## 14. Milestone implementative

1. **M1 — Scaffolding & DB**: struttura cartelle, config, modello dati + migration Alembic iniziale, registro documenti + hashing/dedup.
2. **M2 — Estrazione testuale**: classifier PDF, extractor posizionale (pdfplumber+PyMuPDF, ToUnicode), `raw_extraction`, inventario diagnostico su `/docs`.
3. **M3 — Riconoscimento & mapping Zucchetti**: profili template (ELBA/REVO), mapping campi→DTO con classificazione, righe dinamiche.
4. **M4 — Validazione & anomalie**: quadrature (competenze−trattenute=netto, imponibili), gestione mensilità aggiuntiva e cambio datore.
5. **M5 — Batch resiliente**: orchestratore per-documento, macchina a stati, `/processed`/`/error`, logging strutturato + audit.
6. **M6 — OCR fallback**: OCRmyPDF/Tesseract `ita` per scansionati, marcatura source/confidence.
7. **M7 — Export versionato**: bundle JSONL/CSV + manifest + schema_version, verifica reimport.
8. **M8 — Hardening**: Docker (Tesseract `ita`), test su regressione `/docs`, documentazione operativa.

## 15. Rischi tecnici e mitigazioni

| Rischio | Impatto | Mitigazione |
|---|---|---|
| Font subset con encoding non standard (numeri sballati) | Valori errati | Estrazione via ToUnicode + posizionale; test di quadratura obbligatori |
| Layout variabili / nuovi emittenti | Mapping incompleto | Profili template versionati + stato `NEEDS_REVIEW` + raw sempre salvato |
| PDF scansionati di bassa qualità | OCR impreciso | Confidence su source OCR + anomalie + revisione manuale |
| Duplicati con nome file diverso | Doppioni | Dedup semantico `(CF, azienda, periodo, tipo)` oltre all'hash |
| Cambio datore stesso dipendente | Anagrafica errata | Modello `employment` con validità temporale |
| Mensilità aggiuntiva/conguagli | Quadrature che "non tornano" | Tipo periodo esplicito + regole di quadratura per tipo |
| Evoluzione schema vs export | Reimport rotto | `schema_version` nel manifest + ordine reimport |
| Dati sensibili (CF/IBAN) | Compliance | Masking nei log, integrali solo in DB, accesso controllato |

## 16. Criteri di accettazione

- Il batch elabora `/input` **un documento alla volta**; un PDF in errore finisce in `/error` **senza interrompere** gli altri.
- Ogni documento ha **SHA-256** salvato e **UNIQUE**: re-run della stessa cartella **non crea duplicati**.
- Ogni documento ha uno **stato** tracciato (`RECEIVED`→`PROCESSED`/`FAILED`/`NEEDS_REVIEW`).
- I 6 cedolini di `/docs` vengono riconosciuti (ELBA e REVO), mappati sui campi **realmente presenti**, con righe variabili gestite dinamicamente; i valori chiave **quadrano** (o generano anomalia tracciata).
- I dati sono **classificati** (certo/opzionale/derivato/grezzo/non riconosciuto); nulla di non riconosciuto viene perso (finisce in `raw_extraction`).
- `/logs` contiene log di run e per-documento; l'audit DB registra le transizioni di stato.
- L'**export** produce un bundle **versionato** con manifest reimportabile; un reimport di prova ricostruisce i conteggi per tabella.

## 17. Limitazioni note

**Font Zucchetti corrotto su alcuni cedolini (07.pdf, 08.pdf, 202201.pdf — verificato 2026-07-13).** Il glitch di encoding già noto (spazio decodificato come lettera `s` nell'header, gestito da `normalize_label`, v. §9) su questi 3 documenti è più estesa: non solo la riga "Codice Azienda Ragione Sociale" ma anche la riga di intestazione colonne (quella con "TRATTENUTE"/"COMPETENZE" che delimita l'inizio delle righe voce in `_extract_causale_rows`) decodifica in modo illeggibile e non recuperabile con la normalizzazione esistente.

- **Fix applicato** (`is_zucchetti_document` in `templates/zucchetti.py`): se la riga header esatta non matcha, fallback sul pattern `_COMPANY_CODE_ROW_RE` (codice azienda a 6 cifre + ragione sociale), già usato in `_parse_header` e verificato leggibile su questi 3 file. Il documento viene quindi riconosciuto come `zucchetti_standard` e azienda/dipendente/periodo/CF vengono estratti correttamente.
- **Non risolto deliberatamente**: le righe voce/contributi/TFR/totali di questi 3 documenti restano vuote (0 pay_lines), perché il marcatore che ne delimita l'inizio è tra le righe corrotte. Il documento viene quindi salvato con stato `PROCESSED_WITH_ANOMALIES` e anomalia esplicita `nessuna_riga_voce` (warning) — **nessun importo viene inventato o dedotto da testo corrotto**: il rischio di leggere un valore finanziario sbagliato e trattarlo come corretto è stato considerato inaccettabile per questo dominio. Il testo grezzo integrale resta comunque in `raw_extraction` per un'eventuale rilettura manuale o un parser dedicato futuro.
- Se in futuro si vuole recuperare anche le righe voce di questi documenti, serve un'euristica di fallback per l'inizio/fine della sezione voci (es. prima riga che matcha un codice causale `_CODE_RE` dopo il blocco header, invece del testo di intestazione) — va validata a mano riga per riga prima di fidarsi degli importi estratti.

---

## Verifica (come dimostrare che funziona)

Trattandosi di **piano tecnico** (nessun codice da eseguire), la verifica del piano stesso è:

1. **Confronto col reale**: tutte le entità del modello dati (§6) sono rintracciabili nelle label emerse dai PDF in `doc/payroll-test/` (verificabile ri-eseguendo l'estrazione diagnostica).
2. **Copertura requisiti**: le 16 sezioni richieste dal prompt sono presenti e le regole rispettate (nessun codice, nessun file di progetto, nessun campo inventato, distinzione certi/opzionali/derivati/grezzi/non riconosciuti, scelta unica di stack e DB motivata).
3. **In fase implementativa** (fuori da questo piano), la verifica end-to-end sarà: eseguire il batch sui 6 PDF di `/docs`, controllare stati/anomalie in DB, rieseguire per confermare l'idempotenza (0 nuovi record), generare l'export e reimportarlo verificando i conteggi.
