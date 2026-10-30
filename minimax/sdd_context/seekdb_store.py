"""seekdb / OceanBase-backed engineering material index.

The store keeps the inverted index in ordinary SQL tables so it works on
seekdb Server, OceanBase MySQL mode and seekdb embedded mode.  Retrieval is a
single SQL query over ``sdd_terms``; Python only re-ranks the candidates.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from .config import records_dir, seekdb_dsn, seekdb_path
from .models import Chunk
from .tokenization import raw_tokens

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS sdd_chunks (
        chunk_id VARCHAR(64) PRIMARY KEY,
        kind VARCHAR(16) NOT NULL,
        source_path VARCHAR(512) NOT NULL,
        symbol VARCHAR(255) NOT NULL,
        title VARCHAR(512) NOT NULL,
        content MEDIUMTEXT NOT NULL,
        start_line INT NOT NULL,
        end_line INT NOT NULL,
        metadata TEXT NOT NULL
    ) DEFAULT CHARSET = utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sdd_terms (
        term VARCHAR(64) NOT NULL,
        chunk_id VARCHAR(64) NOT NULL,
        tf INT NOT NULL,
        PRIMARY KEY (term, chunk_id),
        KEY idx_sdd_term (term)
    ) DEFAULT CHARSET = utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sdd_imports (
        import_id VARCHAR(64) PRIMARY KEY,
        source_hash VARCHAR(64) NOT NULL,
        imported_at VARCHAR(64) NOT NULL,
        chunk_count INT NOT NULL
    ) DEFAULT CHARSET = utf8mb4
    """,
)


@dataclass
class SearchRow:
    chunk: Chunk
    matched_terms: int
    term_hits: int
    sql_score: float


def _parse_dsn(dsn: str) -> dict[str, Any]:
    if dsn.startswith(("mysql://", "mysql+pymysql://")):
        parsed = urlparse(dsn)
        database = (parsed.path or "/").lstrip("/") or "test"
        return {
            "host": parsed.hostname or "127.0.0.1",
            "port": parsed.port or 2881,
            "user": unquote(parsed.username or "root"),
            "password": unquote(parsed.password or ""),
            "database": database,
        }
    # key=value;key=value form
    values: dict[str, str] = {}
    for part in dsn.replace(",", ";").split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            values[key.strip().lower()] = value.strip()
    return {
        "host": values.get("host", "127.0.0.1"),
        "port": int(values.get("port", "2881")),
        "user": values.get("user", "root"),
        "password": values.get("password", ""),
        "database": values.get("database", values.get("db", "test")),
    }


class SeekDBMaterialStore:
    """A thin, dependency-light client for seekdb in server or embedded mode."""

    def __init__(
        self,
        *,
        dsn: str | None = None,
        embedded_path: Path | None = None,
        query_log: Path | None = None,
    ) -> None:
        self.dsn = dsn if dsn is not None else seekdb_dsn()
        self.embedded_path = embedded_path if embedded_path is not None else seekdb_path()
        self.query_log = query_log
        self._conn: Any = None
        self._mode = "unconnected"
        self._pyseekdb_client: Any = None

    # ------------------------------------------------------------------ conn
    def connect(self) -> None:
        if self._conn is not None:
            return
        if self.dsn:
            import pymysql
            from pymysql.cursors import DictCursor

            config = _parse_dsn(self.dsn)
            kwargs: dict[str, Any] = {}
            if config["host"] not in {"127.0.0.1", "localhost"}:
                kwargs["ssl"] = {}
            self._conn = pymysql.connect(
                host=config["host"],
                port=config["port"],
                user=config["user"],
                password=config["password"],
                database=config["database"],
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=True,
                **kwargs,
            )
            self._mode = f"seekdb-server:{config['host']}:{config['port']}/{config['database']}"
            return
        if self.embedded_path:
            try:
                import pyseekdb
            except ImportError as error:  # pragma: no cover - platform dependent
                raise RuntimeError(
                    "pyseekdb is not installed. Install requirements.txt or set SEEKDB_DSN."
                ) from error
            try:
                self._pyseekdb_client = pyseekdb.Client(path=str(self.embedded_path), database="test")
                self._conn = self._pyseekdb_client._server.get_raw_connection()
            except RuntimeError as error:  # pylibseekdb missing on Windows
                raise RuntimeError(
                    "Embedded seekdb is unavailable (pylibseekdb is Linux/macOS only). "
                    "Set SEEKDB_DSN to a seekdb/OceanBase server instead."
                ) from error
            self._mode = f"seekdb-embedded:{self.embedded_path}"
            return
        raise RuntimeError(
            "No seekdb configured. Run scripts/bootstrap_seekdb.py, set SEEKDB_DSN, "
            "or set SEEKDB_PATH on a platform with pylibseekdb."
        )

    @property
    def mode(self) -> str:
        return self._mode

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None

    def __enter__(self) -> "SeekDBMaterialStore":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ SQL
    def _execute(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        self.connect()
        cursor = self._conn.cursor()
        try:
            cursor.execute(sql, tuple(params))
            if cursor.description is None:
                return []
            rows = cursor.fetchall()
            normalised: list[dict[str, Any]] = []
            for row in rows:
                if isinstance(row, dict):
                    normalised.append(dict(row))
                else:
                    normalised.append(dict(zip([column[0] for column in cursor.description], row)))
            return normalised
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    def ensure_schema(self) -> None:
        for statement in _SCHEMA:
            self._execute(statement)

    def reset(self) -> None:
        for table in ("sdd_terms", "sdd_chunks", "sdd_imports"):
            self._execute(f"DROP TABLE IF EXISTS {table}")
        self.ensure_schema()

    # --------------------------------------------------------------- import
    def import_chunks(self, chunks: list[Chunk]) -> dict[str, Any]:
        self.ensure_schema()
        started = time.perf_counter()
        self._execute("DELETE FROM sdd_terms")
        self._execute("DELETE FROM sdd_chunks")
        self._execute("DELETE FROM sdd_imports")

        for chunk in chunks:
            self._execute(
                """
                INSERT INTO sdd_chunks
                    (chunk_id, kind, source_path, symbol, title, content, start_line, end_line, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    chunk.chunk_id,
                    chunk.kind,
                    chunk.source_path,
                    chunk.symbol,
                    chunk.title,
                    chunk.content,
                    chunk.start_line,
                    chunk.end_line,
                    json.dumps(chunk.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )

        term_rows: list[tuple[str, str, int]] = []
        for chunk in chunks:
            counts: dict[str, int] = {}
            for token in raw_tokens(chunk.title + "\n" + chunk.content):
                counts[token] = counts.get(token, 0) + 1
            term_rows.extend((term, chunk.chunk_id, count) for term, count in counts.items())

        if term_rows:
            cursor = self._conn.cursor()
            try:
                cursor.executemany(
                    "INSERT INTO sdd_terms (term, chunk_id, tf) VALUES (%s, %s, %s)",
                    term_rows,
                )
            finally:
                cursor.close()

        import_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        source_hash = _hash_chunks(chunks)
        self._execute(
            "INSERT INTO sdd_imports (import_id, source_hash, imported_at, chunk_count) VALUES (%s, %s, %s, %s)",
            (import_id, source_hash, datetime.now(UTC).isoformat(), len(chunks)),
        )
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "import_id": import_id,
            "source_hash": source_hash,
            "chunks": len(chunks),
            "terms": len(term_rows),
            "elapsed_ms": round(elapsed, 2),
            "mode": self._mode,
        }

    # --------------------------------------------------------------- search
    def search(self, terms: list[str], *, limit: int = 300, task: str = "") -> list[SearchRow]:
        if not terms:
            return []
        placeholders = ", ".join(["%s"] * len(terms))
        sql = f"""
            SELECT c.chunk_id, c.kind, c.source_path, c.symbol, c.title, c.content,
                   c.start_line, c.end_line, c.metadata,
                   agg.matched_terms, agg.term_hits
            FROM (
                SELECT chunk_id, COUNT(DISTINCT term) AS matched_terms, SUM(tf) AS term_hits
                FROM sdd_terms
                WHERE term IN ({placeholders})
                GROUP BY chunk_id
            ) AS agg
            JOIN sdd_chunks AS c ON c.chunk_id = agg.chunk_id
            ORDER BY agg.matched_terms DESC, agg.term_hits DESC
            LIMIT %s
        """
        started = time.perf_counter()
        rows = self._execute(sql, [*terms, limit])
        elapsed = (time.perf_counter() - started) * 1000
        self._log_query(
            operation="search",
            sql=sql,
            params=[*terms, limit],
            row_count=len(rows),
            elapsed_ms=elapsed,
            task=task,
            sample=[f"{row['kind']}:{row['symbol']}" for row in rows[:8]],
        )
        results: list[SearchRow] = []
        for row in rows:
            results.append(
                SearchRow(
                    chunk=Chunk(
                        chunk_id=row["chunk_id"],
                        kind=row["kind"],
                        source_path=row["source_path"],
                        symbol=row["symbol"],
                        title=row["title"],
                        content=row["content"],
                        start_line=int(row["start_line"]),
                        end_line=int(row["end_line"]),
                        metadata=json.loads(row["metadata"] or "{}"),
                    ),
                    matched_terms=int(row["matched_terms"]),
                    term_hits=int(row["term_hits"]),
                    sql_score=float(row["matched_terms"]) + 0.01 * float(row["term_hits"]),
                )
            )
        return results

    def fetch_all(self) -> list[Chunk]:
        rows = self._execute(
            "SELECT chunk_id, kind, source_path, symbol, title, content, start_line, end_line, metadata FROM sdd_chunks"
        )
        return [
            Chunk(
                chunk_id=row["chunk_id"],
                kind=row["kind"],
                source_path=row["source_path"],
                symbol=row["symbol"],
                title=row["title"],
                content=row["content"],
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                metadata=json.loads(row["metadata"] or "{}"),
            )
            for row in rows
        ]

    def stats(self) -> dict[str, Any]:
        chunks = self._execute(
            "SELECT kind, COUNT(*) AS count FROM sdd_chunks GROUP BY kind ORDER BY kind"
        )
        imports = self._execute("SELECT * FROM sdd_imports ORDER BY imported_at DESC LIMIT 1")
        return {
            "mode": self._mode,
            "chunks": {row["kind"]: int(row["count"]) for row in chunks},
            "last_import": imports[0] if imports else None,
        }

    # ---------------------------------------------------------------- logging
    def _log_query(
        self,
        *,
        operation: str,
        sql: str,
        params: list[Any],
        row_count: int,
        elapsed_ms: float,
        task: str,
        sample: list[str],
    ) -> None:
        if not self.query_log:
            return
        self.query_log.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "operation": operation,
            "mode": self._mode,
            "sql": " ".join(sql.split()),
            "params": params,
            "row_count": row_count,
            "elapsed_ms": round(elapsed_ms, 2),
            "task": task,
            "sample": sample,
        }
        with self.query_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _hash_chunks(chunks: list[Chunk]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda item: item.chunk_id):
        digest.update(chunk.chunk_id.encode("utf-8"))
        digest.update(chunk.content.encode("utf-8"))
    return digest.hexdigest()


def default_query_log() -> Path:
    return records_dir() / "db_query_record.jsonl"
