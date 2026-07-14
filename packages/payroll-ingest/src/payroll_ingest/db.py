from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from payroll_ingest.config import Settings


def make_engine(settings: Settings):
    # pool_pre_ping: un batch con OCR puo' restare per minuti tra una connessione e
    # l'altra del pool; senza ping preventivo, una connessione droppata dal server
    # (restart, timeout di rete) farebbe fallire il documento successivo con un
    # errore di connessione invece di essere trasparentemente rimpiazzata.
    return create_engine(settings.database_url, future=True, pool_pre_ping=True)


def make_session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = make_engine(settings)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
