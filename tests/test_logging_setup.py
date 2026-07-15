import logging
from contextlib import contextmanager

import structlog

from payroll_ingest.logging_setup import configure_logging


@contextmanager
def _reset_root_handlers():
    # pytest re-inserisce il proprio LogCaptureHandler sul root logger a ogni
    # fase di test; logging.basicConfig() (senza force=True, come fa il
    # codice sotto test) e' un no-op se il root ha gia' handler. Rimuovendoli
    # appena dentro il corpo del test (fase "call", dopo che pytest li ha gia'
    # reinstallati) si osserva l'effetto reale di configure_logging.
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    root.handlers = []
    try:
        yield root
    finally:
        for h in root.handlers:
            if h not in saved_handlers:
                h.close()
        root.handlers = saved_handlers
        root.level = saved_level


def test_configure_logging_creates_logs_dir_and_file(tmp_path):
    with _reset_root_handlers():
        logs_dir = tmp_path / "logs"
        configure_logging(logs_dir, run_id="abc123")

        assert logs_dir.is_dir()
        assert (logs_dir / "batch_abc123.log").exists()


def test_configure_logging_sets_stream_and_file_handlers(tmp_path):
    with _reset_root_handlers():
        configure_logging(tmp_path / "logs", run_id="run1")

        root = logging.getLogger()
        handler_types = {type(h) for h in root.handlers}
        assert logging.StreamHandler in handler_types
        assert logging.FileHandler in handler_types
        assert root.level == logging.INFO


def test_configure_logging_writes_records_to_file(tmp_path):
    with _reset_root_handlers():
        logs_dir = tmp_path / "logs"
        configure_logging(logs_dir, run_id="run2")

        logging.getLogger("test").info("messaggio di prova")
        for handler in logging.getLogger().handlers:
            handler.flush()

        content = (logs_dir / "batch_run2.log").read_text(encoding="utf-8")
        assert "messaggio di prova" in content


def test_configure_logging_configures_structlog(tmp_path):
    configure_logging(tmp_path / "logs", run_id="run3")

    config = structlog.get_config()
    assert isinstance(config["logger_factory"], structlog.stdlib.LoggerFactory)
    processor_types = [type(p) for p in config["processors"]]
    assert structlog.processors.TimeStamper in processor_types
    assert structlog.processors.JSONRenderer in processor_types
