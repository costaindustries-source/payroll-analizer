# Assessment issue da aprire manualmente

Data assessment: 2026-07-15

## Contesto
Richiesta: preparare un assessment in formato Markdown delle issue individuate, da creare poi manualmente su GitHub.

## Evidenze raccolte
- Nel repository non e' presente una cartella `.github/workflows/` (nessuna CI configurata nel repo).
- Sono presenti script di verifica ad-hoc:
  - `scripts/test_issue2_destination_path.py`
  - `scripts/test_issue4_font_corruption.py`
- I commenti nel codice fanno riferimento a una serie di anomalie storiche (`issue GH #2` ... `#13`) soprattutto in `packages/payroll-ingest/src/payroll_ingest/templates/zucchetti.py`.

## Verifiche eseguite in sandbox
- `uv sync --all-packages` -> fallita: `uv: command not found`
- `python3 scripts/test_issue2_destination_path.py` -> fallita: `ModuleNotFoundError: No module named 'pydantic'`
- `python3 scripts/test_issue4_font_corruption.py` -> fallita: `ModuleNotFoundError: No module named 'pdfplumber'`

## Issue candidate da creare

### 1) Assenza pipeline CI per regressioni parser/ingestion
**Priorita'**: Alta  
**Impatto**: Le regressioni non vengono intercettate automaticamente prima del merge/release.  
**Evidenza**: Nessun workflow trovato in `.github/workflows/`; esistono test ad-hoc non orchestrati da CI.

### 2) Test regressione non integrati in una suite standard (pytest)
**Priorita'**: Media-Alta  
**Impatto**: I controlli sono manuali e non facilmente riutilizzabili su ambienti diversi.  
**Evidenza**: Script standalone in `scripts/` (`test_issue2_destination_path.py`, `test_issue4_font_corruption.py`) senza integrazione test runner.

### 3) Onboarding ambiente locale fragile (dipendenza da tool non garantiti)
**Priorita'**: Media  
**Impatto**: Difficolta' a eseguire verifiche in ambienti puliti/sandbox, rallentando validazione e debugging.  
**Evidenza**: `uv` assente in sandbox; esecuzione script bloccata anche per dipendenze Python mancanti (`pydantic`, `pdfplumber`).

## Note operative
- Prima di aprire nuove issue, verificare su GitHub se gli ID citati nel codice (`#2`-`#13`) esistono gia' per evitare duplicati.
- Se alcune issue storiche risultano gia' risolte, creare solo issue di hardening del processo (CI/test/onboarding).
