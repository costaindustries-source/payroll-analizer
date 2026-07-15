from decimal import Decimal

from payroll_ingest.dto import (
    AnomalySeverity,
    CompanyDTO,
    EmployeeDTO,
    PayLineCategory,
    PayLineDTO,
    PayrollDocumentDTO,
    PayrollTotalsDTO,
    PeriodDTO,
    PeriodType,
)
from payroll_ingest.validation import QUADRATURA_TOLERANCE, validate

_CF_VALIDO = "RSSMRA80A01H501U"
_IBAN_VALIDO = "IT" + "60" + "X" + "0" * 22


def _base_dto(**overrides) -> PayrollDocumentDTO:
    defaults = dict(
        company=CompanyDTO(ragione_sociale="Acme SpA"),
        employee=EmployeeDTO(cognome_nome="Mario Rossi", codice_fiscale=_CF_VALIDO),
        period=PeriodDTO(mese=7, anno=2025, tipo=PeriodType.ORDINARIO, label_originale="Luglio 2025"),
        pay_lines=[
            PayLineDTO(
                codice="ZP0001",
                descrizione="Retribuzione",
                categoria=PayLineCategory.RETRIBUZIONE,
                is_recognized=True,
            )
        ],
    )
    defaults.update(overrides)
    return PayrollDocumentDTO(**defaults)


def test_validate_no_anomalies_on_clean_document():
    dto = _base_dto()
    assert validate(dto) == []


def test_validate_invalid_codice_fiscale_produces_warning():
    dto = _base_dto(employee=EmployeeDTO(cognome_nome="Mario Rossi", codice_fiscale="NONVALIDO"))
    anomalies = validate(dto)
    assert len(anomalies) == 1
    assert anomalies[0].tipo == "formato_non_valido"
    assert anomalies[0].severita == AnomalySeverity.WARNING
    assert anomalies[0].campo == "employee.codice_fiscale"
    assert "NONVALIDO" in anomalies[0].messaggio


def test_validate_empty_codice_fiscale_not_checked():
    # stringa vuota e' falsy: il controllo di formato viene saltato (nessun CF noto)
    dto = _base_dto(employee=EmployeeDTO(cognome_nome="Ignoto", codice_fiscale=""))
    assert validate(dto) == []


def test_validate_invalid_iban_produces_warning():
    dto = _base_dto(totals=PayrollTotalsDTO(iban="FR7630006000011234567890189"))
    anomalies = validate(dto)
    assert len(anomalies) == 1
    assert anomalies[0].campo == "totals.iban"
    assert anomalies[0].severita == AnomalySeverity.WARNING


def test_validate_valid_iban_no_anomaly():
    dto = _base_dto(totals=PayrollTotalsDTO(iban=_IBAN_VALIDO))
    assert validate(dto) == []


def test_validate_no_totals_skips_iban_check():
    dto = _base_dto(totals=None)
    assert validate(dto) == []


def test_validate_empty_pay_lines_produces_warning():
    dto = _base_dto(pay_lines=[])
    anomalies = validate(dto)
    assert len(anomalies) == 1
    assert anomalies[0].tipo == "nessuna_riga_voce"
    assert anomalies[0].campo == "pay_lines"


def test_validate_quadratura_within_tolerance_no_anomaly():
    totals = PayrollTotalsDTO(
        totale_competenze=Decimal("1000.00"),
        totale_trattenute=Decimal("300.00"),
        netto_mese=Decimal("700.00") + QUADRATURA_TOLERANCE,
    )
    dto = _base_dto(totals=totals)
    assert validate(dto) == []


def test_validate_quadratura_beyond_tolerance_produces_anomaly():
    totals = PayrollTotalsDTO(
        totale_competenze=Decimal("1000.00"),
        totale_trattenute=Decimal("300.00"),
        netto_mese=Decimal("650.00"),
    )
    dto = _base_dto(totals=totals)
    anomalies = validate(dto)
    assert len(anomalies) == 1
    assert anomalies[0].tipo == "quadratura_netto"
    assert anomalies[0].campo == "totals.netto_mese"
    assert "1000.00" in anomalies[0].messaggio
    assert "300.00" in anomalies[0].messaggio


def test_validate_quadratura_skipped_when_netto_mese_missing():
    totals = PayrollTotalsDTO(totale_competenze=Decimal("1000.00"), totale_trattenute=Decimal("300.00"))
    dto = _base_dto(totals=totals)
    assert validate(dto) == []


def test_validate_quadratura_skipped_when_competenze_or_trattenute_missing():
    totals = PayrollTotalsDTO(totale_competenze=Decimal("1000.00"), netto_mese=Decimal("1.00"))
    dto = _base_dto(totals=totals)
    assert validate(dto) == []


def test_validate_accumulates_multiple_anomalies():
    dto = _base_dto(
        employee=EmployeeDTO(cognome_nome="Ignoto", codice_fiscale="XXX"),
        pay_lines=[],
        totals=PayrollTotalsDTO(
            iban="BADIBAN",
            totale_competenze=Decimal("1000.00"),
            totale_trattenute=Decimal("300.00"),
            netto_mese=Decimal("1.00"),
        ),
    )
    anomalies = validate(dto)
    tipi = {a.tipo for a in anomalies}
    assert tipi == {"formato_non_valido", "nessuna_riga_voce", "quadratura_netto"}
    # formato_non_valido compare due volte: CF e IBAN
    assert len([a for a in anomalies if a.tipo == "formato_non_valido"]) == 2
