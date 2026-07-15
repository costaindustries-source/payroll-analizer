## Cosa cambia e perche'

<!-- Breve descrizione del cambiamento e della motivazione -->

## Checklist

- [ ] I test passano localmente (`uv run pytest --cov=payroll_ingest --cov=payroll_cli --cov-report=term-missing`)
- [ ] Il gate di coverage per-file e' verde (`uv run python scripts/check_coverage.py`)
- [ ] Il CHANGELOG.md e' stato aggiornato sotto `[Non rilasciato]` (se il cambiamento e' visibile all'utente)
- [ ] Nessun dato reale (cedolini, codici fiscali, importi retributivi) e' incluso nel diff

## Issue collegata

<!-- Closes #123, se applicabile -->
