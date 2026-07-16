"""Test per payroll_ingest.db: creazione engine/sessionmaker e session_scope
(commit su successo, rollback su eccezione, chiusura sessione in ogni caso)."""

from sqlalchemy import text

from payroll_ingest.config import Settings
from payroll_ingest.db import make_engine, make_session_factory, session_scope
from payroll_ingest.models import Company


def _settings_for(db_engine) -> Settings:
    # Un nuovo engine puntato alla stessa URL del Postgres di test: non serve
    # passare per lo schema isolato (make_engine non crea/legge tabelle, solo
    # una connessione), quindi non c'e' rischio di toccare dati reali.
    # render_as_string(hide_password=False) e' necessario perche' str(url) in
    # SQLAlchemy 2.x maschera la password con '***', causando un errore di
    # autenticazione quando si crea un nuovo engine con questo URL.
    return Settings(database_url=db_engine.url.render_as_string(hide_password=False))


def test_make_engine_returns_working_connection(db_engine):
    settings = _settings_for(db_engine)
    engine = make_engine(settings)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()


def test_make_engine_has_pool_pre_ping(db_engine):
    settings = _settings_for(db_engine)
    engine = make_engine(settings)
    try:
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_make_session_factory_produces_working_session(db_engine):
    settings = _settings_for(db_engine)
    factory = make_session_factory(settings)
    session = factory()
    try:
        assert session.execute(text("SELECT 1")).scalar() == 1
    finally:
        session.close()


def test_session_scope_commits_on_success(db_session_factory):
    with session_scope(db_session_factory) as session:
        session.add(Company(ragione_sociale="DB SCOPE COMMIT SRL"))

    # Nuova sessione indipendente: se non fosse stato commitato, non la vedrebbe.
    verify = db_session_factory()
    try:
        from sqlalchemy import select

        found = verify.scalar(select(Company).where(Company.ragione_sociale == "DB SCOPE COMMIT SRL"))
        assert found is not None
    finally:
        verify.rollback()
        verify.close()


def test_session_scope_rolls_back_on_exception(db_session_factory):
    class _Boom(Exception):
        pass

    try:
        with session_scope(db_session_factory) as session:
            session.add(Company(ragione_sociale="DB SCOPE ROLLBACK SRL"))
            session.flush()
            raise _Boom("errore simulato dopo il flush")
    except _Boom:
        pass
    else:
        raise AssertionError("session_scope doveva ripropagare l'eccezione")

    verify = db_session_factory()
    try:
        from sqlalchemy import select

        found = verify.scalar(select(Company).where(Company.ragione_sociale == "DB SCOPE ROLLBACK SRL"))
        assert found is None
    finally:
        verify.rollback()
        verify.close()


def test_session_scope_always_closes_session(db_session_factory):
    captured = {}

    def spying_factory():
        session = db_session_factory()
        original_close = session.close

        def spy_close():
            captured["closed"] = True
            original_close()

        session.close = spy_close
        return session

    with session_scope(spying_factory) as session:
        captured["session"] = session

    assert captured.get("closed") is True


def test_session_scope_closes_session_even_on_exception(db_session_factory):
    captured = {}

    def spying_factory():
        session = db_session_factory()
        original_close = session.close

        def spy_close():
            captured["closed"] = True
            original_close()

        session.close = spy_close
        return session

    try:
        with session_scope(spying_factory):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert captured.get("closed") is True
