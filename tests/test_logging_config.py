import logging
from logging.handlers import RotatingFileHandler

from app.logging_config import configure_file_logging


def test_configure_file_logging_creates_backend_log_handler(tmp_path):
    log_file = tmp_path / "logs" / "backend.log"
    logger_name = "tests.file_logging"
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.propagate = False

    configure_file_logging(log_file=log_file, logger_names=[logger_name])
    configure_file_logging(log_file=log_file, logger_names=[logger_name])

    handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(log_file)
    ]
    assert len(handlers) == 1

    logger.warning("file logging works")
    handlers[0].flush()

    assert log_file.exists()
    assert "file logging works" in log_file.read_text()


def test_configure_file_logging_does_not_duplicate_propagated_child_logs(tmp_path):
    log_file = tmp_path / "logs" / "backend.log"
    parent_logger = logging.getLogger()
    child_logger = logging.getLogger("tests.file_logging.child")
    original_root_handlers = parent_logger.handlers[:]
    original_child_handlers = child_logger.handlers[:]
    original_child_propagate = child_logger.propagate
    try:
        parent_logger.handlers.clear()
        child_logger.handlers.clear()
        child_logger.propagate = True

        configure_file_logging(log_file=log_file, logger_names=["", "tests.file_logging.child"])
        child_logger.warning("one line only")
        for handler in parent_logger.handlers + child_logger.handlers:
            handler.flush()

        assert log_file.read_text().count("one line only") == 1
    finally:
        parent_logger.handlers[:] = original_root_handlers
        child_logger.handlers[:] = original_child_handlers
        child_logger.propagate = original_child_propagate
