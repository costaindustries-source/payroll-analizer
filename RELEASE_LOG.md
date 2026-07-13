# Release log

Voci append-only, scritte automaticamente da `scripts/release.sh` a ogni
rilascio riuscito su Debian. Non modificare a mano le voci passate.

## v0.1.2 — 2026-07-13T13:02:15Z

fix: smoke test nell immagine Docker (mount ad-hoc non funzionava)

- Tag precedente su Debian: v0.1.1
- Smoke test post-deploy: OK

## v0.1.3 — 2026-07-13T14:05:26Z

fix(zucchetti): recupera pay_lines e importi su cedolini con corruzione estesa del font (chiude #3)

- Tag precedente su Debian: v0.1.2
- Smoke test post-deploy: OK

## v0.2.0 — 2026-07-13T14:38:03Z

feat(cli): comando delete-document per rielaborare documenti gia' processati

- Tag precedente su Debian: v0.1.3
- Smoke test post-deploy: OK

## v0.3.0 — 2026-07-13T15:37:51Z

Fix glitch font Zucchetti (Z->2 su codici causale, O->0 su IBAN, issue #4) + comando CLI check-years per verifica copertura annuale

- Tag precedente su Debian: v0.2.0
- Smoke test post-deploy: OK
