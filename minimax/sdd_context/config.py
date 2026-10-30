"""Runtime configuration for the SDD context module.

All paths are resolved relative to this package so the module can be started
from any working directory.  Environment variables are intentionally simple:

* ``SEEKDB_DSN``       mysql://user:password@host:port/database
* ``SEEKDB_PATH``      embedded seekdb data directory (Linux, pylibseekdb)
* ``SDD_STATE_DB``     PowerContext SQLite database path
* ``SDD_RUNTIME_DIR``  directory for generated runtime state
* ``SDD_RECORDS_DIR``  directory for generated usage records
"""

from __future__ import annotations

import json
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
MINIMAX_DIR = PACKAGE_DIR.parent
DEFAULT_PROJECT_ROOT = MINIMAX_DIR / "demo_project"
DEFAULT_RUNTIME_DIR = MINIMAX_DIR / ".runtime"
DEFAULT_RECORDS_DIR = MINIMAX_DIR / "records"


def runtime_dir() -> Path:
    return Path(os.environ.get("SDD_RUNTIME_DIR", DEFAULT_RUNTIME_DIR)).resolve()


def records_dir() -> Path:
    return Path(os.environ.get("SDD_RECORDS_DIR", DEFAULT_RECORDS_DIR)).resolve()


def state_db_path() -> Path:
    return Path(os.environ.get("SDD_STATE_DB", runtime_dir() / "powercontext.db")).resolve()


def project_root(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    return Path(os.environ.get("SDD_PROJECT_ROOT", DEFAULT_PROJECT_ROOT)).resolve()


def _load_dotenv() -> None:
    """Load a local ``minimax/.env`` without requiring python-dotenv."""

    path = MINIMAX_DIR / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def seekdb_dsn() -> str | None:
    """Return an explicitly configured DSN or the one bootstrapped on disk."""

    _load_dotenv()
    explicit = os.environ.get("SEEKDB_DSN") or os.environ.get("SDD_SEEKDB_DSN")
    if explicit:
        return explicit.strip()
    instance_file = runtime_dir() / "seekdb.json"
    if instance_file.exists():
        try:
            payload = json.loads(instance_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(payload, dict):
            value = payload.get("connection") or payload.get("dsn")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def seekdb_path() -> Path | None:
    value = os.environ.get("SEEKDB_PATH")
    return Path(value).resolve() if value else None


def ensure_runtime_dirs() -> None:
    runtime_dir().mkdir(parents=True, exist_ok=True)
    records_dir().mkdir(parents=True, exist_ok=True)
