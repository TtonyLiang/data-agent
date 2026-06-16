import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_FILE = PROJECT_ROOT / "logs" / "backend.log"
DEFAULT_LOGGERS = ("", "app", "uvicorn", "uvicorn.error", "uvicorn.access")


def configure_file_logging(
    log_file: Path = DEFAULT_LOG_FILE,
    logger_names: list[str] | tuple[str, ...] = DEFAULT_LOGGERS,
) -> Path:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )

    for logger_name in logger_names:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        if _has_file_handler(logger, log_file) or _inherits_file_handler(logger, log_file):
            continue
        handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return log_file


def _has_file_handler(logger: logging.Logger, log_file: Path) -> bool:
    return any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename) == log_file
        for handler in logger.handlers
    )


def _inherits_file_handler(logger: logging.Logger, log_file: Path) -> bool:
    if not logger.propagate:
        return False
    parent = logger.parent
    while parent:
        if _has_file_handler(parent, log_file):
            return True
        if not parent.propagate:
            return False
        parent = parent.parent
    return False
