# Piano tecnico — Supporto nuovi template cedolini 2016-2020

> Stato: **proposta, da revisionare** — nessuna implementazione ancora avviata.
> Ambito: estensione di `payroll-ingest` ai 57 cedolini in `docs/new-templates/`.
> Riferimenti: architettura generale in `PIANO_TECNICO.md` (radice), processo release in `docs/RELEASE_PROCESS.md`.

---

## 1. Scopo e inventario

Obiettivo: estendere il parser (oggi limitato al template `zucchetti_standard`) ai cedolini del datore precedente (Accenture), periodo settembre 2016 → tredicesima 2020, presenti in `docs/new-templates/{2016..2020}/YYYYMM.pdf` (MM=13 = tredicesima).

Censimento dei 57 PDF (analisi via pdfplumber, sola lettura):

| Gruppo | Periodi | File | Producer PDF | Note |
|---|---|---|---|---|
| Layout A "pulito" | 2016-09 → 2018-02 | 20 | PDFsharp 1.31 | 1 pagina, estrazione corrente perfetta |
| Layout A "scrambled" | 2018-03 → 2019-01 | 12 | Win2PDF 7.6 | **testo anagrammato** (v. §3); `201811.pdf` ha 2 pagine |
| Layout B | 2019-02 → 2020-13 | 25 | iText 2.1.7 | 1 pagina, estrazione corrente perfetta |

Tutti i PDF sono **testuali nativi**: nessuno richiede OCR (`classify_pdf` li classifica `TEXTUAL`). Da 2019-02 in poi è presente 1 immagine per file (logo), irrilevante per l'estrazione.

Nessuno dei due layout è riconosciuto da `is_zucchetti_document()`: l'header "Codice Azienda Ragione Sociale" non esiste e il fallback `_COMPANY_CODE_ROW_RE` (codice azienda a 6 cifre) non matcha (Layout A ha `ATS/ ##/ VR`, Layout B non ha righe simili in testa). Servono **due nuovi template**.

## 2. Caratterizzazione dei layout

> Nota privacy: i PDF contengono dati personali reali. Questo documento riporta solo etichette, marker, struttura e coordinate — mai nomi, codici fiscali, IBAN o importi.

### 2.1 Layout A — "CopernicoPaghe" (2016-09 → 2019-01, 32 file)

Marker di riconoscimento, in ordine di affidabilità:

1. Footer con `CopernicoPaghe S.r.l.` (+ codice `CPLUACC1`), top ~805
2. Header a due righe separate: `Codice Azienda/Filiale/Stabil` e `Ragione Sociale Azienda` (top < 30)
3. Legenda footer `F=VALORE ESCLUSIVAMENTE FIGURATIVO...`

Struttura (coordinate misurate sui campioni):

- **Header anagrafico** (top 22-148): griglia label/valore. Codice azienda nel formato `ATS/ ##/ VR`; ragione sociale (ACCENTURE TECHNOLOGY SOLUTIONS SRL) nella riga sotto l'header; matricola in `Dip./Dip. Mecc.`; CF e date (nascita/assunzione, formato `##/##/####` con `/`) nella riga sotto `Comune Residenza Fiscale ...`.
- **Periodo** (top ~148): valore sotto `Periodo Competenza`, **senza spazio** tra mese e anno: `Gennaio2018`; tredicesima = `13-esima2016`.
- **Corpo voci** (da riga intestazione `Cod. Descrizione Ore/GG % Dato Base Ritenute Competenze`, top ~255, fino a `Totale Ritenute Sociali`): codici voce numerici a 4 cifre (`0001`, `1542`, `0061`...) più codici sezione fiscale (`####IM`, `####RM`, `DETRFI`, `IRPeF`, `CvL###`, `RfVE##`). Colonne per soglia x0 (indicative, da calibrare): Ore/GG ~239-278, Dato Base ~354, Ritenute ~434-500, Competenze ~503-570. Flag `F` (valore esclusivamente figurativo) come ultima parola della riga.
- **Totali**: label `Totale Ritenute Totale Competenze` (top ~563) con valori nella riga sotto (top ~572); `NETTO A PAGARE` con valore a top ~619.
- **IBAN scomposto** sulla riga `Paese IT Cin Eur ## CIN <lettera> ABI ##### CAB ##### C/C ############` (top ~594.7).
- **TFR** (top 623-737): `Retribuz. Utile TFR`, `TFR al 31/12 A.P.`, `Accant.TFR AC`, `Anticipazioni AP`.
- **Ferie/permessi** (top 645-692): tabella `Ferie | Rol/Ex-Festività | Banca Ore Riposi` × righe `AP2/AP/AC` × (Spettanti/Godute/Residue).
- **Tredicesima**: stesso layout, periodo `13-esima<anno>` e voce `0061 TREDICESIMA MENSILITA'`; dati presenza (Ore/GG) vuoti.
- **Multipagina**: `201811.pdf` ha 2 pagine per overflow di righe voci; pagina 2 ha stessa struttura e footer. Il parser deve concatenare le sezioni voci delle pagine.

Il cambio di producer (PDFsharp → Win2PDF a 2018-03) **non** cambia il layout testuale: è lo stesso template, ma i file Win2PDF hanno il problema descritto in §3.

### 2.2 Layout B — "SAP HR / iText" (2019-02 → 2020-13, 25 file)

Marker di riconoscimento:

1. Riga intestazione `VOCI RETRIBUTIVE` con `TRATTENUTE`/`COMPETENZE` a destra (top ~302)
2. Campi anagrafici `SAP Nr.:`, `Codice:`, `Num. Progressivo:`
3. (conferma, non primario) producer `iText 2.1.7 by 1T3XT`

**Non usare la ragione sociale come marker**: cambia da ACCENTURE TECHNOLOGY SOLUTIONS a ACCENTURE FINANCIAL ADVANCED SOLUTIONS & TECHNOLOGY S.R.L. nel 2020.

Struttura (coordinate misurate):

- **Header anagrafico** (top < 230): `Nominativo:`, `SAP Nr.:` (matricola), `Codice:`; CF persona nella riga sotto `Data Nascita Codice Fiscale...` (top ~129.7 — attenzione: a top ~146 c'è anche il CF azienda a 11 cifre, il regex CF persona non lo matcha); ragione sociale a top ~90 tra `LIBRO UNICO...` e la riga indirizzo; ulteriori label: `Matricola Inps`, `Cod./Posizione INAIL`, `Contratto`/`Tipo Contratto`.
- **Periodo**: label `Periodo Competenza` a top ~259.7, valore a top ~272.1 nel formato standard `Gennaio 2020`; tredicesima = `Dicembre 2020` + etichetta `Tredicesima` sulla stessa riga.
- **Corpo voci** in 3 sezioni con la stessa meccanica: `VOCI RETRIBUTIVE` (top ~302) → `TRATTENUTE PREVIDENZIALI` (~400) → `CTB. DED.` (~429) → `ADDIZIONALI` (~449, con regione/comune — es. VENETO/VERONA — su riga di continuazione). Codici voce alfanumerici (`ESPP06`, `FEHG`, `W1100`, `R90017`...) a x0 ~21-26; descrizione x0 < ~236; colonne per fascia x0 dalle intestazioni: ORE/GIORNI ~236-280, IMPORTO UNITARIO ~284-344, IMPONIBILI ~263-293 (sezione previdenziale), ALIQUOTE, IMPORTI FIGURATI ~369-424, TRATTENUTE ~460-500, COMPETENZE ~505-570.
- **Box footer** a coppie label-row/value-row: totali (`Totale Trattenute`/`Totale Competenze`, label top ~588.4, valori top ~617.1), `Totale Detrazioni`, IBAN come **stringa unica** 27 caratteri (top ~634.8), TFR (`Retr. Utile TFR`, `Acc.TFR 31/12 AP`, `Accant. TFR AC`, `TFR a Tesoreria AC`, label ~655.5 / valori ~665.7), detrazioni (`Imposta Lorda`, `Detr. Lav. Dip.`, `Imposta Netta`, label ~685 / valori ~690.8), progressivi (~708-734), ferie `FERIE | R.O.L. | B.ORE` (righe ~757-777) con colonne dalla label-row `Maturate Godute Residue AP Residue AP2 Saldo` (~750.2).
- **Punto critico — NETTO fuori riga**: la label `NETTO` è a top ~641.6 (x 483.9-517.9), ma il valore è a top ~666.6 (x0 ~493.7) e il clustering per righe lo aggrega alla riga dei valori TFR. Va estratto **per coordinate** (importo sotto la label con x-range sovrapposto), non per riga.
- **Estrazione in reading-order inutilizzabile per i box**: `extract_text()` raggruppa tutte le label in testa e tutti i valori in coda. Il clustering per `top` di `extraction.py` (`Row`) ricompone invece correttamente le righe del corpo voci (verificato su `202001.pdf`); i box del footer richiedono comunque matching label→valore per coordinate x.

### 2.3 Differenze chiave rispetto a `zucchetti_standard`

| Aspetto | Zucchetti | Layout A | Layout B |
|---|---|---|---|
| Header | `Codice Azienda Ragione Sociale` (1 riga) | 2 righe separate | `SAP Nr.:` / `Codice:` |
| Colonne voci | IMPORTO BASE / RIFERIMENTO / TRATTENUTE / COMPETENZE | Ore/GG / % / Dato Base / Ritenute / Competenze | ORE/GIORNI / IMPORTO UNITARIO / ALIQUOTE / IMPONIBILI / TRATTENUTE / COMPETENZE |
| Netto | `NETTO DEL MESE` | `NETTO A PAGARE` | `NETTO` (valore fuori riga) |
| IBAN | stringa unica | scomposto in 6 campi | stringa unica |
| Tredicesima | periodo "AGG." | `13-esima<anno>` (senza spazio) | `Dicembre <anno>` + label `Tredicesima` |

## 3. Criticità: file Win2PDF con font a avanzamento zero (12 file)

I 12 file 2018-03 → 2019-01 hanno font privi di FontBBox/width (warning pdfplumber `Could not get FontBBox`): tutti i frammenti di una parola condividono lo stesso `x0` (± ~0.3pt). L'ordinamento per posizione di `extraction.py` produce **anagrammi** ("Dsecriienoz" per "Descrizione") — e il problema colpisce **anche le cifre degli importi**: parsare questi file con l'estrazione attuale produrrebbe **importi silenziosamente sbagliati**. Il recupero è quindi **obbligatorio**, non opzionale.

Evidenza e soluzione verificata: con `page.extract_words(use_text_flow=True)` l'ordine di stream è corretto ("De"+"scriz"+"io"+"n"+"e") e l'`x0` del primo frammento di ogni parola resta affidabile per l'assegnazione a colonna.

Design del recupero in `packages/payroll-ingest/src/payroll_ingest/extraction.py`:

1. **Rilevatore geometrico di pagina corrotta** (strutturale, indipendente dal template): frazione elevata (soglia proposta > 20%) di coppie di caratteri consecutivi nello stream che condividono lo stesso `x0` (± 0.5pt) pur essendo caratteri distinti.
2. Se corrotta: ri-estrazione con `use_text_flow=True` e **ricostruzione delle parole in ordine di stream** — nuovo `Word` quando cambia il cluster di `top` o quando l'`x0` del frammento dista più di ~3pt dal precedente (i frammenti della stessa parola condividono l'x0 di inizio parola); testo = concatenazione in ordine di stream; `x0` = minimo dei frammenti. Poi filtro sidebar e `_cluster_rows` invariati (solo l'ordine *intra-parola* era rotto; l'ordinamento per `x0` delle parole resta valido).
3. Nuovo flag `RawPage.recovered_from_scramble: bool = False`, così il template può emettere un'`AnomalyDTO` WARNING informativa ("testo ricostruito dall'ordine di stream, verificare gli importi"). La quadratura del netto in `validation.py` funge da check incrociato: se un file ricostruito non quadra, finisce in review umana.

Effetti collaterali noti da gestire: possibile perdita di spazi intra-riga nella ricostruzione ("RETRIBUZIONEORDIN ARIA" — confronti label da fare via `normalize_label`); caratteri accentati resi come `(cid:###)` ("Ex-Festività") — stesso rimedio.

## 4. Design: registry di template

Oggi la selezione del template è cablata in `orchestrator.py` (righe ~137-143):

```python
if is_zucchetti_document(raw):
    dto = map_document(raw)
else:
    dto = _unrecognized_dto("Layout non riconosciuto come cedolino Zucchetti")
```

e il `parser_version` passato a `save_document` (riga ~155) è la costante globale di Zucchetti. Con tre template serve un dispatch esplicito.

**Nuovo contenuto di `packages/payroll-ingest/src/payroll_ingest/templates/__init__.py`** (oggi vuoto):

```python
@dataclass(frozen=True)
class TemplateSpec:
    name: str
    parser_version: str
    detect: Callable[[RawExtractedDocument], bool]
    map: Callable[[RawExtractedDocument], PayrollDocumentDTO]

TEMPLATES: tuple[TemplateSpec, ...] = (ZUCCHETTI, COPERNICO, SAP_HR)

def find_template(raw: RawExtractedDocument) -> TemplateSpec | None:
    return next((t for t in TEMPLATES if t.detect(raw)), None)
```

- Ogni modulo template espone `TEMPLATE_NAME`, `PARSER_VERSION`, `is_*_document`, `map_document` e una costante `SPEC = TemplateSpec(...)`; il registry importa e ordina.
- **Ordine di detection**: Zucchetti → Copernico → SAP HR. I marker sono mutuamente esclusivi (verificato sui campioni), l'ordine è solo prudenziale per preservare il comportamento attuale.
- **Orchestrator**: `spec = find_template(raw)`; se trovato `dto = spec.map(raw)` con `parser_version=spec.parser_version`; altrimenti `_unrecognized_dto("Layout non riconosciuto da nessun template registrato")` con `parser_version="0.0.0"`. Micro-cambiamento: oggi i non riconosciuti salvano la versione Zucchetti `1.0.0`; il valore neutro è più corretto — da annotare nel CHANGELOG.
- `models.PayrollDocument.template_name` è `String(64)`: i nuovi nomi ci stanno → **nessuna migration**.

## 5. Design: `templates/copernico.py` (Layout A)

`TEMPLATE_NAME = "copernico_paghe"`, `PARSER_VERSION = "1.0.0"`. Strategia **a righe** (stile `zucchetti.py`: regex di riga + soglie x per colonna), stessa struttura del modulo esistente.

- **Detection** `is_copernico_document(doc)`: riga header top < 30 che normalizza a "Codice Azienda/Filiale/Stabil Ragione Sociale Azienda" **oppure** riga in fondo pagina contenente `CopernicoPaghe` (leggibile anche sui Win2PDF dopo il recupero §3). Doppio marker per robustezza.
- **Header**: ragione sociale dalla riga sotto l'header (dopo il prefisso `ATS/ ##/ VR` → `codice_azienda`); CF con regex standard; nominativo dalla riga `####/######## NOME ...` (matricola = `Dip./Dip. Mecc.`); `hire_date` da `Data Assunz.` — le date usano `/`, il parser condiviso accetta solo `-` → regex locale al template (non toccare `normalize.py`).
- **Periodo**: regex dedicate — `(Gennaio|...|Dicembre)\s*(\d{4})` per l'ordinario (il valore è senza spazio), `13[- ]?esima\s*(\d{4})` per la tredicesima → `mese=12`, `tipo=MENSILITA_AGGIUNTIVA` (coerente con la convenzione Zucchetti: destinazione `processed/<anno>/12/`, nessuna collisione di filename perché i file si chiamano `YYYY13.pdf`).
- **Corpo voci**: righe tra l'intestazione colonne e `Totale Ritenute Sociali`; colonne per soglia x0 (§2.1, da calibrare su 2-3 campioni). **Flag `F` figurativo**: se ultima parola della riga è `F` → `PayLineDTO.note = "valore esclusivamente figurativo (non concorre al netto)"`, colonna comunque valorizzata; nessun campo DTO nuovo.
- **Tax**: `####IM Imponibile Fiscale Mese` → `imponibile_irpef`; `####RM ... Lorda` → `irpef_lorda`; `DETRFI` → `detrazioni_lav_dip`; `IRPeF ... Netta` → `ritenute_irpef`; `CvL###`/`CvL### AC acconto` → `addizionale_comunale`/`acconto_addizionale_comunale`; `RfVE##` → `addizionale_regionale` (+ regione dai 2 caratteri del codice).
- **Totali**: due importi distinti per x0 nella riga sotto `Totale Ritenute Totale Competenze`; `NETTO A PAGARE` → importo a top ~619. **IBAN ricomposto**: `IT + cin_eur(2) + cin(1) + abi(5) + cab(5) + cc(12)` = 27 caratteri, validato con il checksum mod-97 — **estrarre l'helper IBAN da `zucchetti.py` in un modulo condiviso `templates/_common.py`** invece di duplicarlo (candidati alla condivisione anche `normalize_label` e i parser importi).
- **TFR**: `Retribuz. Utile TFR` → `retribuzione_utile_tfr`; `Accant.TFR AC` → `quota_anno`; `Anticipazioni AP` → `anticipi`; `TFR al 31/12 A.P.` non ha campo dedicato → fuori dai DTO (opzionali) o anomalia INFO. Pattern label-row/value-row con matching x0, stile `_extract_tfr`.
- **Ferie**: 3 `LeaveBalanceDTO` (`tipo` = `ferie`, `rol_ex_festivita`, `banca_ore_riposi`) con maturato/goduto/residuo dalla riga AC e `residuo_ap` dalla riga AP; residuo AP2 se ≠ 0 → entry separata (`ferie_ap2`, ...). Attenzione: su alcuni file la riga AP2 appare come `AP#`.
- **Multipagina** (`201811.pdf`): sezioni "a scansione" (totali, TFR, ferie, tax) su tutte le righe di tutte le pagine; corpo voci = **concatenazione delle sezioni voci di ogni pagina** (delimitate per pagina da intestazione → `Totale Ritenute Sociali`/fine tabella), perché l'overflow su pagina 2 è reale.
- **Anomalie**: pattern di zucchetti (`totali_mancanti` ERROR se netto/IBAN assenti, `header_incompleto`, `periodo_non_riconosciuto`) + WARNING `testo_ricostruito` se `recovered_from_scramble`.

## 6. Design: `templates/sap_hr.py` (Layout B)

`TEMPLATE_NAME = "sap_hr"`, `PARSER_VERSION = "1.0.0"`. Strategia **ibrida**: righe clusterizzate per il corpo voci (verificate funzionanti), lookup per coordinate per i box del footer.

- **Detection**: riga `VOCI RETRIBUTIVE` con `TRATTENUTE`/`COMPETENZE` a destra **e** presenza di `SAP Nr.:`. Mai la ragione sociale (§2.2).
- **Header**: `Nominativo:` → `cognome_nome`; `SAP Nr.:` → `matricola`; `Codice:` → `codice_azienda`; CF via regex persona (il CF azienda a 11 cifre non matcha); ragione sociale ancorata tra `LIBRO UNICO...` e la riga indirizzo (non hardcodare "ACCENTURE"); data assunzione dalla riga sotto `Data Ass. Conv. Data Assunzione...`.
- **Periodo**: parole sotto la label `Periodo Competenza` (matching x-window), formato standard → `parse_italian_month_year`; se sulla riga compare `Tredicesima` → `tipo=MENSILITA_AGGIUNTIVA`, `label_originale` = testo completo. Il file `202013.pdf` ha periodo interno 12/2020 → destinazione `processed/2020/12/`, coerente con la convenzione esistente.
- **Corpo voci** (3 sezioni, stessa meccanica): righe tra `VOCI RETRIBUTIVE` e `TRATTENUTE PREVIDENZIALI`; tra questa e `ADDIZIONALI`; addizionali fino al box `Descrizione Imponibile Fiscale...`. Codice = prima parola (alfanumerica); descrizione = parole con x0 < ~236; importi per fascia x0 (§2.2): ORE/GIORNI → `quantita`, IMPORTO UNITARIO/IMPONIBILI → `importo_base`, ALIQUOTE → `aliquota`, IMPORTI FIGURATI → nota figurativo, TRATTENUTE → `trattenuta`, COMPETENZE → `competenza`. Le righe `VENETO`/`VERONA` sotto le addizionali sono continuazioni → `addizionale_regionale_regione` / nota comune.
- **Tax**: sezione ADDIZIONALI → `addizionale_regionale`/`addizionale_comunale` (+ acconto se etichettato); box detrazioni (matching per colonna x): `Imposta Lorda` → `irpef_lorda`, `Detr. Lav. Dip.` → `detrazioni_lav_dip`, `Imposta Netta` → `ritenute_irpef`; `Imponibile Fiscale` dalla riga `Emolumenti correnti` → `imponibile_irpef`.
- **Totali e NETTO**: box `Totale Trattenute / Totale Competenze` per sovrapposizione x-range tra label-row e value-row. Per il NETTO (valore fuori riga, §2.2) implementare un helper generico `_amount_below_label(words, label_words, x_pad, max_dy)` che lavora sui `Word`, non sulle `Row`. IBAN = parola che matcha `IT\d{2}[A-Z]\d{22}`.
- **TFR**: `Retr. Utile TFR` (nel box progressivi) → `retribuzione_utile_tfr`; `Accant. TFR AC` → `quota_anno`; `TFR a Tesoreria AC` → `quota_tfr_fondi`; `Anticipazioni AC` → `anticipi`; `Acc.TFR 31/12 AP` senza campo dedicato → fuori (come Layout A).
- **Ferie**: righe `FERIE`/`R.O.L.`/`B.ORE` con colonne dalla label-row `Maturate Godute Residue AP Residue AP2 Saldo` via matching x → mapping: `Maturate` → `maturato`, `Godute` → `goduto`, `Residue AP` → `residuo_ap`, **`Saldo` → `residuo`** (qui "Residue" sono i residui anni precedenti e "Saldo" è il residuo corrente).
- **Anomalie**: come Copernico (netto/IBAN mancanti = ERROR, ecc.).

## 7. Compatibilità DTO / DB / validazione (esito verifica)

- **Nessuna migration Alembic necessaria**: tutti i dati nuovi mappano su campi esistenti di `dto.py` (inclusi `PayLineDTO.note` per il flag figurativo, `addizionale_regionale_regione`, `residuo_ap`). I dati senza campo dedicato (saldo TFR anni precedenti, contratto/qualifica del Layout B) restano fuori dai DTO opzionali, eventualmente tracciati come anomalia INFO o in `unrecognized_row_texts`. `template_name String(64)` ok.
- **`validation.py` invariata**: nessuna regola Zucchetti-specifica — CF, IBAN (sia il ricomposto A sia la stringa B sono 27 caratteri IT → passano), `nessuna_riga_voce`, quadratura netto. La tolleranza di quadratura (1.50) è da collaudare empiricamente col batch sui 57 file: se il Layout B sforasse sistematicamente (detrazioni/arrotondamenti), la formula per quel template va decisa **sui dati**, non a priori.
- **`_destination_path` / orchestrator**: gli anni 2016-2020 funzionano senza modifiche (`processed/<anno>/<mese>/`); tredicesime → mese 12 come da convenzione. `_detect_period_type` è interno a `zucchetti.py`: ogni template ha il suo.
- **`normalize.py` invariato**: le peculiarità ("Gennaio2018", "13-esima2016", date con `/`) si gestiscono con regex locali ai template, per non toccare il comportamento Zucchetti.
- **`SIDEBAR_MAX_X1 = 25.0` in `extraction.py` è sicuro per i nuovi layout** (verificato): il Layout B non ha parole con `x1 ≤ 25`; il Layout A perde solo la "I" iniziale di una legenda boilerplate (innocuo) e sui Win2PDF esclude correttamente una sidebar ruotata. Nessuna modifica; documentare nel commento della costante.

## 8. Piano test

1. **Estensione di `scripts/smoke_test.py`**: rifattorizzare `EXPECTED_SAMPLES` in una lista di casi `(samples_dir, filename, template_atteso, check extra)` usando `find_template` del registry. Campioni proposti (restano non versionati, in `docs/new-templates/`):
   - Layout A: `2016/201610.pdf` (ordinario PDFsharp), `2016/201613.pdf` (tredicesima: `tipo==MENSILITA_AGGIUNTIVA` + voce TREDICESIMA), `2018/201804.pdf` (scrambled Win2PDF, 1 pagina), `2018/201811.pdf` (scrambled + 2 pagine: soglia minima di pay_lines a prova della concatenazione).
   - Layout B: `2019/201902.pdf` (primo del layout), `2020/202001.pdf` (ordinario, ragione sociale 2020), `2020/202013.pdf` (tredicesima).
   - Check per campione: template giusto, `ragione_sociale`, `codice_fiscale`, periodo esatto (mese+anno hardcoded), `netto_mese is not None`, IBAN valido, `len(pay_lines) >= 1`.
   - Totale: 6 campioni Zucchetti esistenti + 7 nuovi = **13 campioni**.
2. **Nuovo `scripts/verify_new_templates.py`** (versionato): itera tutti i PDF di `docs/new-templates/**/*.pdf` e stampa una tabella per file (template, periodo, tipo, n. voci, netto presente, IBAN valido, n. anomalie per severità) **senza valori personali**; exit 1 se un file non è riconosciuto o manca un campo essenziale. È il gate di accettazione dei 57 file.
3. **Run end-to-end facoltativo**: copiare 2-3 campioni in `input/` e lanciare la pipeline reale (`payroll-ingest process`) per verificare salvataggio DB e spostamento in `processed/2016/10/` ecc.

## 9. Fasi di lavoro incrementali

| # | Attività | File coinvolti | Criterio di verifica |
|---|---|---|---|
| 1 | Registry `TemplateSpec` + migrazione Zucchetti + dispatch in orchestrator | `templates/__init__.py`, `orchestrator.py` | `python scripts/smoke_test.py` → 6/6 OK; run manuale su un cedolino Zucchetti con esito identico (status, n. anomalie) |
| 2 | Recupero testo scrambled | `extraction.py` | smoke 6/6 (i PDF Zucchetti non attivano l'euristica) + righe leggibili su `201811.pdf` ("Cod. Descrizione", "CopernicoPaghe", "Novembre 2018") |
| 3 | `copernico.py` — prima i 20 PDFsharp, poi i 12 Win2PDF | `templates/copernico.py`, registry | `verify_new_templates.py` OK sui 32 file A (periodo 32/32, netto e IBAN valorizzati, quadratura in tolleranza) |
| 4 | `sap_hr.py` | `templates/sap_hr.py`, registry | verify OK sui 25 file B, incluso `202013` con `tipo=mensilita_aggiuntiva` |
| 5 | Estensione smoke test + script batch definitivi | `scripts/smoke_test.py`, `scripts/verify_new_templates.py` | smoke 13/13, verify 57/57 |
| 6 | CHANGELOG + release | `CHANGELOG.md` | bump **minor** SemVer (nuovi template, v. `docs/RELEASE_PROCESS.md`), processo release standard |

## 10. Rischi e punti aperti

- **File Win2PDF (12/57)**: il recupero stream-order è la parte più delicata; le cifre permutate rendono il recupero obbligatorio (rischio importi sbagliati silenziosi). Mitigazioni: anomalia WARNING sui documenti ricostruiti + quadratura netto come check incrociato → i file che non quadrano finiscono in review umana.
- **Perdita di spazi intra-riga nella ricostruzione**: la segmentazione per salto di `x0` va calibrata; i confronti label dei template devono passare da `normalize_label` (tollera anche i `(cid:###)` delle accentate).
- **Soglie x hardcoded**: misurate su pochi campioni; il batch sui 57 file è il collaudo vero. Varianti intra-layout non campionate (mesi con sezioni assenti, conguagli di fine rapporto 2020) possono emergere solo lì.
- **Valori figurativi** (flag `F` Layout A, colonna IMPORTI FIGURATI Layout B): non concorrono ai totali del cedolino; mapparli con nota e verificare che nessuna logica a valle (exporter, quadratura) li sommi.
- **NETTO Layout B fuori riga**: usare l'helper per coordinate; non fidarsi delle `Row` per i box footer.
- **Micro-cambiamento comportamentale**: il `parser_version` dei documenti non riconosciuti passa da `1.0.0` (costante Zucchetti) a `0.0.0` — documentare nel CHANGELOG.
