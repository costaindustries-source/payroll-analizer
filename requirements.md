# Prompt IA — Piano tecnico Payroll Ingestion

## Ruolo
Agisci come **Principal Software Architect**. Devi produrre **solo un piano tecnico**, non codice.

## Obiettivo
Definisci il piano tecnico per un'applicazione enterprise che importa payroll da PDF, estrae i dati e li salva in un database strutturato.

## Contesto
I payroll saranno PDF/A, PDF testuali o PDF scansionati. Nella cartella `docs` del progetto ci sono tutti gli esempi reali da analizzare prima di definire modello dati e parsing.

Il futuro frontend sarà in:

```text
/home/mcostantini/DEV/VSCode/FrontEnd/costaindustries
```

Per ora ignora il frontend: serve solo progettare ingestion, salvataggio ed export.

## Requisiti principali
- Funzionamento batch.
- Folder input per i PDF.
- Folder log per i log di esecuzione.
- Elaborazione indipendente per documento.
- Un PDF in errore non deve bloccare gli altri.
- Tracciamento dei documenti già caricati tramite hash SHA-256.
- Stato di lavorazione per ogni documento.
- Modello dati granulare per documento, dipendente, azienda, periodo payroll, righe retributive, contributi, tasse, trattenute, rimborsi, benefit, totali, anomalie e dati grezzi.
- Database scelto da te, motivando la scelta.
- Stack tecnologico scelto da te, motivando la scelta.
- Export completo della base dati, versionato e importabile in futuro da altri sistemi.

## Cartelle attese
Proponi o migliora questa struttura:

```text
/docs       -> esempi payroll reali da analizzare
/input      -> PDF da caricare
/processed  -> PDF elaborati correttamente
/error      -> PDF in errore
/logs       -> log batch e per documento
/export     -> export completo database
```

## Analisi obbligatoria dei file in `docs`
Nel piano inserisci una fase dedicata per:

- censire i PDF disponibili;
- distinguere PDF testuali, PDF/A e scansionati;
- estrarre testo campione;
- capire se serve OCR;
- individuare campi ricorrenti e opzionali;
- rilevare layout diversi;
- definire mapping campo documento -> modello dati;
- identificare casi limite e anomalie.

## Output richiesto
Rispondi con queste sezioni, in ordine:

1. **Sintesi della soluzione**
2. **Stack tecnologico consigliato** con motivazione
3. **Architettura logica**
4. **Analisi dei payroll in `docs`**
5. **Struttura cartelle proposta**
6. **Modello dati database**: tabelle principali, relazioni, indici e vincoli
7. **DTO principali** a livello descrittivo
8. **Flusso batch end-to-end**
9. **Strategia parsing/OCR**
10. **Strategia idempotenza tramite hash**
11. **Gestione errori per documento**
12. **Logging e audit**
13. **Export completo database**
14. **Milestone implementative**
15. **Rischi tecnici e mitigazioni**
16. **Criteri di accettazione**

## Regole
- Non generare codice.
- Non creare file di progetto.
- Non implementare classi, migration o test.
- Non inventare campi payroll come certi se non emergono dai PDF in `docs`.
- Distingui dati certi, opzionali, grezzi, non riconosciuti e derivati.
- Se qualcosa è ambiguo, fai massimo 3 domande solo se bloccanti.
- Preferisci una soluzione semplice, solida ed enterprise-ready.
- Dai una sola scelta consigliata per stack e database.
