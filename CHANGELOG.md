# Changelog

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it/1.0.0/).

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
