from payroll_ingest.extraction import RawExtractedDocument
from payroll_ingest.templates._spec import TemplateSpec
from payroll_ingest.templates.copernico import SPEC as COPERNICO
from payroll_ingest.templates.sap_hr import SPEC as SAP_HR
from payroll_ingest.templates.zucchetti import SPEC as ZUCCHETTI

# Ordine di detection: Zucchetti prima, poi Copernico, poi SAP HR. I marker di
# riconoscimento dei tre template sono mutuamente esclusivi sui campioni
# verificati; l'ordine e' solo prudenziale, per preservare il comportamento
# attuale su Zucchetti/Copernico in caso di futura ambiguita'.
TEMPLATES: tuple[TemplateSpec, ...] = (ZUCCHETTI, COPERNICO, SAP_HR)


def find_template(raw: RawExtractedDocument) -> TemplateSpec | None:
    return next((t for t in TEMPLATES if t.detect(raw)), None)
