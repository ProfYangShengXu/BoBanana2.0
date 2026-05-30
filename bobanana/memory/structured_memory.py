"""Structured memory for precise retrieval.

SQLite-backed store of high-value, structured facts: tracked files, code
symbols/snippets, and key/value facts. Lookups here are
exact (by path, key, or category).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import List, Optional, Tuple


class StructuredMemory:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                path        TEXT PRIMARY KEY,
                summary     TEXT,
                lines       INTEGER,
                updated_at  REAL
            );
            CREATE TABLE IF NOT EXISTS code_symbols (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                path        TEXT,
                symbol      TEXT,
                kind        TEXT,
                snippet     TEXT,
                updated_at  REAL
            );
            CREATE TABLE IF NOT EXISTS facts (
                key         TEXT PRIMARY KEY,
                value       TEXT,
                category    TEXT,
                created_at  REAL
            );
            CREATE TABLE IF NOT EXISTS exploration (
                key         TEXT PRIMARY KEY,
                tool        TEXT,
                args        TEXT,
                result      TEXT,
                created_at  REAL
            );
            CREATE INDEX IF NOT EXISTS idx_symbols_path ON code_symbols(path);
            CREATE INDEX IF NOT EXISTS idx_facts_cat ON facts(category);
            """
        )
        self._conn.commit()

    # ----- files -----
    def upsert_file(self, path: str, summary: str = "", lines: int = 0) -> None:
        self._conn.execute(
            """INSERT INTO files(path, summary, lines, updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET
                 summary=excluded.summary, lines=excluded.lines, updated_at=excluded.updated_at""",
            (path, summary, lines, time.time()),
        )
        self._conn.commit()

    def get_file(self, path: str) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM files WHERE path=?", (path,))
        return cur.fetchone()

    def list_files(self) -> List[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM files ORDER BY updated_at DESC")
        return cur.fetchall()

    # ----- code symbols -----
    def add_symbol(self, path: str, symbol: str, kind: str, snippet: str) -> None:
        self._conn.execute(
            "INSERT INTO code_symbols(path, symbol, kind, snippet, updated_at) VALUES(?,?,?,?,?)",
            (path, symbol, kind, snippet, time.time()),
        )
        self._conn.commit()

    def find_symbols(self, query: str, limit: int = 10) -> List[sqlite3.Row]:
        like = f"%{query}%"
        cur = self._conn.execute(
            "SELECT * FROM code_symbols WHERE symbol LIKE ? OR snippet LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (like, like, limit),
        )
        return cur.fetchall()

    # ----- facts -----
    def set_fact(self, key: str, value: str, category: str = "general") -> None:
        self._conn.execute(
            """INSERT INTO facts(key, value, category, created_at) VALUES(?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, category=excluded.category""",
            (key, value, category, time.time()),
        )
        self._conn.commit()

    def get_fact(self, key: str) -> Optional[str]:
        cur = self._conn.execute("SELECT value FROM facts WHERE key=?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def facts_by_category(self, category: str) -> List[Tuple[str, str]]:
        cur = self._conn.execute(
            "SELECT key, value FROM facts WHERE category=? ORDER BY created_at DESC", (category,)
        )
        return [(r["key"], r["value"]) for r in cur.fetchall()]

    def all_facts(self) -> List[Tuple[str, str, str]]:
        cur = self._conn.execute("SELECT key, value, category FROM facts ORDER BY created_at DESC")
        return [(r["key"], r["value"], r["category"]) for r in cur.fetchall()]

    # ----- exploration cache (read_file / list_dir / read-only shell) -----
    def get_exploration(self, key: str) -> Optional[str]:
        cur = self._conn.execute("SELECT result FROM exploration WHERE key=?", (key,))
        row = cur.fetchone()
        return row["result"] if row else None

    def save_exploration(self, key: str, tool: str, args: str, result: str) -> None:
        self._conn.execute(
            """INSERT INTO exploration(key, tool, args, result, created_at) VALUES(?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET result=excluded.result, created_at=excluded.created_at""",
            (key, tool, args, result, time.time()),
        )
        self._conn.commit()

    def clear_facts_categories(self, categories: tuple[str, ...]) -> int:
        """Remove facts whose category is in *categories*. Returns rows deleted."""
        if not categories:
            return 0
        placeholders = ",".join("?" for _ in categories)
        cur = self._conn.execute(
            f"SELECT COUNT(*) AS n FROM facts WHERE category IN ({placeholders})",
            categories,
        )
        n = cur.fetchone()["n"]
        self._conn.execute(
            f"DELETE FROM facts WHERE category IN ({placeholders})",
            categories,
        )
        self._conn.commit()
        return n

    def clear_exploration(self) -> int:
        """Invalidate the whole exploration cache (after a write side-effect).

        Returns the number of cached entries removed."""
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM exploration")
        n = cur.fetchone()["n"]
        self._conn.execute("DELETE FROM exploration")
        self._conn.commit()
        return n

    def close(self) -> None:
        self._conn.close()
