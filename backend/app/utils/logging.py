from __future__ import annotations

from pathlib import Path
import json
import logging
import logging.handlers
import os

LOG_ROOT = Path('logs').resolve()
LOG_ROOT.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record) + '\n')


def setup_logging() -> None:
    """Configure root logging per environment variables.
    Env:
      LOG_LEVEL: DEBUG|INFO|WARNING|ERROR (default INFO)
      LOG_TO_CONSOLE: 1|0 (default 1)
      LOG_FILE: path to log file (default logs/backend_app.log)
      LOG_MAX_BYTES: rotate size (default 5_000_000)
      LOG_BACKUP_COUNT: number of rotated files (default 3)
    """
    level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)
    to_console = os.getenv('LOG_TO_CONSOLE', '1') == '1'
    log_file = os.getenv('LOG_FILE') or str(LOG_ROOT / 'backend_app.log')
    max_bytes = int(os.getenv('LOG_MAX_BYTES', '5000000'))
    backup_count = int(os.getenv('LOG_BACKUP_COUNT', '3'))

    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid dupes on reload
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s - %(message)s')

    # File (rotating)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    # Console
    if to_console:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        console.setLevel(level)
        root.addHandler(console)

    logging.getLogger(__name__).info(
        "Logging initialized level=%s file=%s console=%s", level_name, log_file, to_console
    )
