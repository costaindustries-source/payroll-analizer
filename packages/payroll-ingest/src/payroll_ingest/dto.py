from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class DataClassification(str, Enum):
    CERTO = "certo"
    OPZIONALE = "opzionale"
    DERIVATO = "derivato"
    GREZZO = "grezzo"
    NON_RICONOSCIUTO = "non_riconosciuto"


class PayLineCategory(str, Enum):
    RETRIBUZIONE = "retribuzione"
    ASSENZA = "assenza"
    CONTRIBUTO = "contributo"
    BENEFIT = "benefit"
    RIMBORSO = "rimborso"
    ALTRO = "altro"
    NON_RICONOSCIUTO = "non_riconosciuto"


class PeriodType(str, Enum):
    ORDINARIO = "ordinario"
    MENSILITA_AGGIUNTIVA = "mensilita_aggiuntiva"
    CONGUAGLIO = "conguaglio"


class DocumentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    PROCESSED_WITH_ANOMALIES = "PROCESSED_WITH_ANOMALIES"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class AnomalySeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class CompanyDTO:
    ragione_sociale: str
    indirizzo: str | None = None
    codice_azienda: str | None = None
    inail_aut: str | None = None
    inail_del: str | None = None
    inail_sede: str | None = None
    posizione_inps: str | None = None
    pat_inail: str | None = None
    classification: DataClassification = DataClassification.CERTO


@dataclass
class EmployeeDTO:
    cognome_nome: str
    codice_fiscale: str
    matricola: str | None = None
    classification: DataClassification = DataClassification.CERTO


@dataclass
class PeriodDTO:
    mese: int
    anno: int
    tipo: PeriodType
    label_originale: str
    classification: DataClassification = DataClassification.CERTO


@dataclass
class PayLineDTO:
    codice: str | None
    descrizione: str
    categoria: PayLineCategory
    is_recognized: bool
    importo_base: Decimal | None = None
    quantita: Decimal | None = None
    unita: str | None = None
    aliquota: Decimal | None = None
    trattenuta: Decimal | None = None
    competenza: Decimal | None = None
    raw_text: str = ""
    note: str | None = None
    classification: DataClassification = DataClassification.CERTO


@dataclass
class TaxDTO:
    imponibile_irpef: Decimal | None = None
    irpef_lorda: Decimal | None = None
    detrazioni_lav_dip: Decimal | None = None
    ritenute_irpef: Decimal | None = None
    addizionale_regionale: Decimal | None = None
    addizionale_regionale_regione: str | None = None
    addizionale_comunale: Decimal | None = None
    acconto_addizionale_comunale: Decimal | None = None
    classification: DataClassification = DataClassification.OPZIONALE


@dataclass
class TfrDTO:
    retribuzione_utile_tfr: Decimal | None = None
    quota_tfr_fondi: Decimal | None = None
    rivalutazione: Decimal | None = None
    imponibile_rivalutazione: Decimal | None = None
    quota_anno: Decimal | None = None
    anticipi: Decimal | None = None
    classification: DataClassification = DataClassification.OPZIONALE


@dataclass
class LeaveBalanceDTO:
    tipo: str
    maturato: Decimal | None = None
    goduto: Decimal | None = None
    residuo: Decimal | None = None
    residuo_ap: Decimal | None = None
    classification: DataClassification = DataClassification.OPZIONALE


@dataclass
class PayrollTotalsDTO:
    imponibile_inps: Decimal | None = None
    imponibile_inail: Decimal | None = None
    imponibile_irpef: Decimal | None = None
    totale_competenze: Decimal | None = None
    totale_trattenute: Decimal | None = None
    netto_mese: Decimal | None = None
    iban: str | None = None
    banca: str | None = None
    classification: DataClassification = DataClassification.DERIVATO


@dataclass
class AnomalyDTO:
    tipo: str
    severita: AnomalySeverity
    messaggio: str
    campo: str | None = None


@dataclass
class PayrollDocumentDTO:
    company: CompanyDTO
    employee: EmployeeDTO
    period: PeriodDTO
    pay_lines: list[PayLineDTO] = field(default_factory=list)
    tax: TaxDTO | None = None
    tfr: TfrDTO | None = None
    leave_balances: list[LeaveBalanceDTO] = field(default_factory=list)
    totals: PayrollTotalsDTO | None = None
    anomalies: list[AnomalyDTO] = field(default_factory=list)
    unrecognized_row_texts: list[str] = field(default_factory=list)
    template_name: str = "unknown"
    hire_date: date | None = None
