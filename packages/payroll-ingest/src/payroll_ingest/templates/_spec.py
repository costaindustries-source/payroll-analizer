"""Definizione di TemplateSpec, isolata dal registry (__init__.py) per evitare
un import circolare: ogni modulo template (zucchetti.py, ...) deve poter
costruire il proprio SPEC senza importare il pacchetto templates stesso."""

from collections.abc import Callable
from dataclasses import dataclass

from payroll_ingest.dto import PayrollDocumentDTO
from payroll_ingest.extraction import RawExtractedDocument


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    parser_version: str
    detect: Callable[[RawExtractedDocument], bool]
    map: Callable[[RawExtractedDocument], PayrollDocumentDTO]
