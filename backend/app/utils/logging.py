from __future__ import annotations

from pathlib import Path
import json

LOG_ROOT = Path('logs').resolve()
LOG_ROOT.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record) + '\n')
