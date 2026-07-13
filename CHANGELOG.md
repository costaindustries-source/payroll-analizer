# Changelog

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it/1.0.0/).

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
