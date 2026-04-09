"""
applog — lightweight dual-sink logger for comprehensity.

Log levels (lowest → highest):
    TRACE  DEBUG  INFO  SUMMARY  WARN  ERROR  FATAL  NONE (disabled)

SUMMARY lines use greppable emoji prefixes:
    ✅  success / completed
    ❌  error / fatal failure
    ⚠️  warning (non-fatal)
    🔍  scan / start

Configuration (highest precedence wins):
    CLI args  >  env vars  >  hard-coded defaults

Env vars:
    APP_CONSOLE_LEVEL   stdout level   (default: SUMMARY)
    APP_FILE_LEVEL      file level     (default: NONE)
    APP_OUTPUT_FILE     log file path  (default: output/last.log)

Rules applied in configure():
    • -o given without --file  →  file_level = DEBUG
    • file_level ≠ NONE without a path  →  path = output/last.log
"""
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# ── level constants ───────────────────────────────────────────────────────────
TRACE   = 5
DEBUG   = logging.DEBUG    # 10
INFO    = logging.INFO     # 20
SUMMARY = 25
WARN    = logging.WARNING  # 30
WARNING = WARN
ERROR   = logging.ERROR    # 40
FATAL   = logging.CRITICAL # 50
NONE    = 999              # sentinel — disables the sink

_LEVELS: dict = {
    "TRACE":   TRACE,
    "DEBUG":   DEBUG,
    "INFO":    INFO,
    "SUMMARY": SUMMARY,
    "WARN":    WARN,
    "WARNING": WARN,
    "ERROR":   ERROR,
    "FATAL":   FATAL,
    "NONE":    NONE,
}

DEFAULT_LOG_FILE = "output/last.log"

# Register custom level names so log records display them correctly.
logging.addLevelName(TRACE,   "TRACE")
logging.addLevelName(SUMMARY, "SUMMARY")
logging.addLevelName(FATAL,   "FATAL")

# ── internal logger ───────────────────────────────────────────────────────────
_log = logging.getLogger("comprehensity")
_log.setLevel(TRACE)   # pass everything; handlers filter independently
_log.propagate = False  # don't bubble to the root logger


class _MinLevel(logging.Filter):
    def __init__(self, level: int) -> None:
        super().__init__()
        self._level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self._level


def _console_fmt() -> logging.Formatter:
    return logging.Formatter("%(message)s")


def _file_fmt() -> logging.Formatter:
    return logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


# ── public API ────────────────────────────────────────────────────────────────

def get_level(name: str) -> int:
    """Convert a level name (case-insensitive) to its integer value."""
    key = name.strip().upper()
    if key not in _LEVELS:
        raise ValueError(
            f"Unknown log level {name!r}. Choose from: {', '.join(_LEVELS)}"
        )
    return _LEVELS[key]


def configure(
    console_level: Optional[str] = None,
    file_level:    Optional[str] = None,
    log_file:      Optional[str] = None,
    output_given:  bool = False,
) -> None:
    """Set up (or reconfigure) the dual-sink logger.

    Args:
        console_level:  Level name for stdout.  None → env var or "SUMMARY".
        file_level:     Level name for log file. None → env var or "NONE".
        log_file:       Log file path.  None → env var or DEFAULT_LOG_FILE.
        output_given:   True when the CLI's -o flag was explicitly provided.
                        Implies file_level=DEBUG when no file_level is set.
    """
    # Resolve: explicit arg > env var > hard-coded default
    eff_console = console_level or os.environ.get("APP_CONSOLE_LEVEL") or "SUMMARY"
    eff_file    = file_level    or os.environ.get("APP_FILE_LEVEL")    or "NONE"
    eff_path    = log_file      or os.environ.get("APP_OUTPUT_FILE")

    # -o given without --file → enable file logging at DEBUG
    if output_given and file_level is None and not os.environ.get("APP_FILE_LEVEL"):
        eff_file = "DEBUG"

    # active file sink without a path → use default
    if eff_file.upper() != "NONE" and not eff_path:
        eff_path = DEFAULT_LOG_FILE

    console_int = get_level(eff_console)
    file_int    = get_level(eff_file)

    # Tear down existing handlers
    for h in list(_log.handlers):
        _log.removeHandler(h)
        h.close()

    # Console sink
    if console_int < NONE:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(_console_fmt())
        ch.addFilter(_MinLevel(console_int))
        _log.addHandler(ch)

    # File sink
    if file_int < NONE and eff_path:
        Path(eff_path).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(eff_path, encoding="utf-8")
        fh.setFormatter(_file_fmt())
        fh.addFilter(_MinLevel(file_int))
        _log.addHandler(fh)


# ── emit helpers ──────────────────────────────────────────────────────────────

def trace(msg: str, *args: object) -> None:
    _log.log(TRACE, msg, *args)

def debug(msg: str, *args: object) -> None:
    _log.debug(msg, *args)

def info(msg: str, *args: object) -> None:
    _log.info(msg, *args)

def summary(msg: str, *args: object) -> None:
    _log.log(SUMMARY, msg, *args)

def warn(msg: str, *args: object) -> None:
    _log.warning(msg, *args)

def error(msg: str, *args: object) -> None:
    _log.error(msg, *args)

def fatal(msg: str, *args: object) -> None:
    _log.critical(msg, *args)


# Apply defaults at import time so code that never calls configure() still
# gets sensible output (env vars are honoured; hard-coded default is SUMMARY).
configure()
