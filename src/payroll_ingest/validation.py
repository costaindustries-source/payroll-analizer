"""Controlli di quadratura e coerenza sul documento mappato.

Le buste paga reali difficilmente quadrano al centesimo esatto tra
competenze - trattenute e netto (arrotondamenti, TFR, acconti): una piccola
differenza e' normale e non deve bloccare l'elaborazione, solo essere tracciata.
"""

import re
from decimal import Decimal

from payroll_ingest.dto import AnomalyDTO, AnomalySeverity, PayrollDocumentDTO

QUADRATURA_TOLERANCE = Decimal("1.50")
_CF_RE = re.compile(r"^[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]$")
_IBAN_IT_RE = re.compile(r"^IT\d{2}[A-Z]\d{22}$")


def validate(dto: PayrollDocumentDTO) -> list[AnomalyDTO]:
    anomalies: list[AnomalyDTO] = []

    if dto.employee.codice_fiscale and not _CF_RE.match(dto.employee.codice_fiscale):
        anomalies.append(
            AnomalyDTO(
                tipo="formato_non_valido",
                severita=AnomalySeverity.WARNING,
                messaggio=f"Codice fiscale con formato inatteso: {dto.employee.codice_fiscale!r}",
                campo="employee.codice_fiscale",
            )
        )

    if dto.totals and dto.totals.iban and not _IBAN_IT_RE.match(dto.totals.iban):
        anomalies.append(
            AnomalyDTO(
                tipo="formato_non_valido",
                severita=AnomalySeverity.WARNING,
                messaggio=f"IBAN con formato inatteso: {dto.totals.iban!r}",
                campo="totals.iban",
            )
        )

    if not dto.pay_lines:
        anomalies.append(
            AnomalyDTO(
                tipo="nessuna_riga_voce",
                severita=AnomalySeverity.WARNING,
                messaggio="Nessuna riga voce riconosciuta nella sezione variabili del mese",
                campo="pay_lines",
            )
        )

    if dto.totals and dto.totals.totale_competenze is not None and dto.totals.totale_trattenute is not None:
        if dto.totals.netto_mese is not None:
            atteso = dto.totals.totale_competenze - dto.totals.totale_trattenute
            differenza = abs(atteso - dto.totals.netto_mese)
            if differenza > QUADRATURA_TOLERANCE:
                anomalies.append(
                    AnomalyDTO(
                        tipo="quadratura_netto",
                        severita=AnomalySeverity.WARNING,
                        messaggio=(
                            f"Competenze ({dto.totals.totale_competenze}) - trattenute "
                            f"({dto.totals.totale_trattenute}) = {atteso}, ma netto dichiarato e' "
                            f"{dto.totals.netto_mese} (differenza {differenza})"
                        ),
                        campo="totals.netto_mese",
                    )
                )

    return anomalies
