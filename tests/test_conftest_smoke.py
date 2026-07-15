"""Smoke test della fixture db_session: verifica solo che lo schema isolato
si crei/popoli/elimini correttamente, non e' regressione di dominio."""

from sqlalchemy import select

from payroll_ingest.models import Company


def test_db_session_roundtrip(db_session):
    company = Company(ragione_sociale="ACME SRL")
    db_session.add(company)
    db_session.flush()

    fetched = db_session.scalar(select(Company).where(Company.ragione_sociale == "ACME SRL"))
    assert fetched is not None
    assert fetched.id == company.id
