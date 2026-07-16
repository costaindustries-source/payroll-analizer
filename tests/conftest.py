"""Fixture condivise per la suite pytest.

`db_engine`/`db_session_factory`/`db_session` danno accesso a un Postgres
reale (necessario: i modelli usano tipi dialect-specific `JSONB`/`UUID`, non
compatibili con SQLite) senza mai toccare lo schema 'public' dove vivono i
dati reali di sviluppo: ogni sessione di test crea uno schema Postgres
isolato e usa-e-getta (nome random), lo popola con `Base.metadata.create_all`
e lo elimina a fine sessione. Se Postgres non e' raggiungibile, i test che
dipendono da queste fixture vengono skippati invece di fallire l'intera
suite (comportamento voluto sia in locale senza `docker compose up -d db`,
sia in CI se il service container Postgres non e' configurato)."""

import os
import uuid as uuid_module

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from payroll_ingest.models import Base

_DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://payroll:payroll@localhost:5432/payroll"


def _base_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DATABASE_URL)


@pytest.fixture(scope="session")
def db_engine():
    base_url = _base_database_url()
    schema = f"test_{uuid_module.uuid4().hex[:12]}"

    try:
        admin_engine = create_engine(base_url, future=True)
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.commit()
        admin_engine.dispose()
    except Exception as exc:
        pytest.skip(f"Postgres non raggiungibile ({base_url}): {exc}")

    engine = create_engine(base_url, future=True)

    # SOLO lo schema di test, senza 'public' come fallback: se 'public' ha
    # gia' le stesse tabelle (dati reali di sviluppo), Base.metadata.create_all
    # le trova via search_path e non le ricrea nello schema isolato - ogni
    # query successiva ricade quindi silenziosamente su 'public' (issue #25,
    # scoperta investigando un batch che sembrava corrompere dati reali). Le
    # tabelle non dipendono da nessuna estensione/funzione definita solo in
    # public (UUID generati Python-side, created_at con NOW() built-in), quindi
    # rimuoverlo dal search_path e' sicuro.
    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}"')
        cursor.close()

    Base.metadata.create_all(engine)

    yield engine

    engine.dispose()
    cleanup_engine = create_engine(base_url, future=True)
    with cleanup_engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        conn.commit()
    cleanup_engine.dispose()


@pytest.fixture
def db_session_factory(db_engine) -> sessionmaker:
    return sessionmaker(bind=db_engine, expire_on_commit=False, future=True)


@pytest.fixture
def db_session(db_session_factory):
    session = db_session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
