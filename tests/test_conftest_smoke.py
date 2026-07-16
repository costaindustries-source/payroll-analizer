"""Smoke test della fixture db_session: verifica solo che lo schema isolato
si crei/popoli/elimini correttamente, non e' regressione di dominio."""

from sqlalchemy import select, text

from payroll_ingest.models import Company


def test_db_session_roundtrip(db_session):
    company = Company(ragione_sociale="ACME SRL")
    db_session.add(company)
    db_session.flush()

    fetched = db_session.scalar(select(Company).where(Company.ragione_sociale == "ACME SRL"))
    assert fetched is not None
    assert fetched.id == company.id


def test_db_session_search_path_esclude_public(db_session):
    """Guardia contro la regressione scoperta investigando GH #25: se
    search_path include 'public' insieme allo schema di test, e 'public' ha
    gia' le stesse tabelle (dati reali di sviluppo), Base.metadata.create_all
    le trova via search_path e non le ricrea nello schema isolato - ogni
    query successiva (select/insert/delete) ricade silenziosamente su
    'public'. Controllo a runtime (non sul solo testo del fixture) perche'
    e' l'unico modo di verificare il comportamento effettivo della
    connessione, non solo l'intenzione nel codice."""
    search_path = db_session.execute(text("SHOW search_path")).scalar()
    assert "public" not in search_path.lower()
