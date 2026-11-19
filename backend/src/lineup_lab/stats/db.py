"""The only module that talks to DuckDB.

Model-written SQL is untrusted, so three layers protect the file and the machine:
1. the connection is read-only, with external access (files, network, extensions) off and
   configuration locked, so the SQL can't turn it back on;
2. DuckDB's own parser must see exactly one SELECT statement;
3. a timer interrupts queries that run too long, and a memory cap stops queries that would
   otherwise take the whole container down (DuckDB defaults to 80% of host RAM).
Long text cells are clipped so one value can't bloat the stream or the prompt.
"""

import datetime as dt
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

MEMORY_LIMIT = "256MB"
THREADS = 2
MAX_CELL_CHARS = 1000


class SqlError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class SqlResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int


@dataclass
class Coverage:
    seasons: list[int]
    as_of_season: int
    as_of_week: int


@dataclass
class PlayerRow:
    player_id: str
    name: str
    position: str
    team: str
    ppr_points: float


def _json_safe(v: Any) -> Any:
    if isinstance(v, dt.date | dt.datetime | dt.time):
        return v.isoformat()
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, str) and len(v) > MAX_CELL_CHARS:
        return v[:MAX_CELL_CHARS] + "…"
    return v


class StatsDB:
    def __init__(self, path: Path, timeout_s: float = 10.0):
        self._timeout_s = timeout_s
        self._con = duckdb.connect(
            str(path),
            read_only=True,
            config={
                "enable_external_access": False,
                "memory_limit": MEMORY_LIMIT,
                "threads": THREADS,
                "lock_configuration": True,
            },
        )

    def _single_select(self, sql: str) -> str:
        try:
            statements = self._con.extract_statements(sql)
        except duckdb.Error as e:
            raise SqlError(str(e)) from e
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise SqlError("Only a single SELECT statement is allowed")
        return statements[0].query.strip().rstrip(";").strip()

    def run_sql(self, sql: str, max_rows: int) -> SqlResult:
        query = self._single_select(sql)
        cur = self._con.cursor()
        timer = threading.Timer(self._timeout_s, cur.interrupt)
        start = time.perf_counter()
        timer.start()
        try:
            cur.execute(query)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            if truncated:
                # The newlines keep a trailing "-- comment" from swallowing the paren.
                row_count = cur.execute(f"SELECT count(*) FROM (\n{query}\n)").fetchone()[0]
            else:
                row_count = len(rows)
        except duckdb.InterruptException as e:
            raise SqlError(f"Query took too long (over {self._timeout_s:g}s)") from e
        except duckdb.Error as e:
            raise SqlError(str(e)) from e
        finally:
            timer.cancel()
            cur.close()
        return SqlResult(
            columns=columns,
            rows=[[_json_safe(v) for v in r] for r in rows[:max_rows]],
            row_count=row_count,
            truncated=truncated,
            duration_ms=round((time.perf_counter() - start) * 1000),
        )

    def _meta(self) -> dict[str, str]:
        return dict(self._con.cursor().execute("SELECT key, value FROM meta").fetchall())

    def as_of(self) -> tuple[int, int]:
        m = self._meta()
        return int(m["as_of_season"]), int(m["as_of_week"])

    def coverage(self) -> Coverage:
        m = self._meta()
        return Coverage(
            seasons=[int(s) for s in m["seasons"].split(",")],
            as_of_season=int(m["as_of_season"]),
            as_of_week=int(m["as_of_week"]),
        )

    def players(self) -> list[PlayerRow]:
        rows = (
            self._con.cursor()
            .execute("SELECT player_id, name, position, team, ppr_points FROM players")
            .fetchall()
        )
        return [PlayerRow(*r) for r in rows]

    def columns(self) -> list[tuple[str, str, str, str | None]]:
        """(table, column, type, comment) for the schema prompt, in a stable order."""
        return (
            self._con.cursor()
            .execute(
                "SELECT table_name, column_name, data_type, comment FROM duckdb_columns() "
                "WHERE table_name IN ('players','weekly_stats','snap_counts','games') "
                "ORDER BY table_name, column_index"
            )
            .fetchall()
        )
