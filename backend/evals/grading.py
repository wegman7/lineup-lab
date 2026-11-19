"""Execution-match grading for SQL evals, and reading a run's outcome from its events.

A result passes when the row counts match and every reference column's values (sorted, numbers
rounded to 1 decimal, text casefolded) equal some column of the actual result. Extra columns are
fine; column names and row order don't matter.
Known limitation: values are compared column by column, so row alignment isn't checked.
"""

from typing import Any

from lineup_lab.agent.events import DoneEvent, ErrorEvent, StepEvent
from lineup_lab.stats.db import SqlResult


def _norm(v: Any) -> tuple:
    if isinstance(v, bool):
        return (1, str(v))
    if isinstance(v, int | float):
        return (0, round(float(v), 1))
    if v is None:
        return (2, "")
    return (1, str(v).casefold().strip())


def _column(result: SqlResult, i: int) -> list[tuple]:
    return sorted(_norm(row[i]) for row in result.rows)


def grade(reference: SqlResult, actual: SqlResult | None) -> bool:
    if actual is None or actual.row_count != reference.row_count:
        return False
    actual_cols = [_column(actual, i) for i in range(len(actual.columns))]
    return all(_column(reference, i) in actual_cols for i in range(len(reference.columns)))


def outcome_from_events(events: list) -> dict:
    """outcome is the route taken, except a name that couldn't be pinned down counts as
    'ambiguous' (asking the user is the right behavior there)."""
    outcome, final_sql, attempts, error = None, None, 0, None
    done = None
    for e in events:
        if isinstance(e, StepEvent):
            if e.kind == "route" and e.status == "done":
                outcome = e.detail["route"]
            elif e.kind == "resolve" and any(
                r["status"] in ("ambiguous", "unknown") for r in e.detail["resolutions"]
            ):
                outcome = "ambiguous"
            elif e.kind == "sql" and e.status in ("done", "failed"):
                attempts += 1
                if e.status == "done":
                    final_sql = e.detail["sql"]
        elif isinstance(e, DoneEvent):
            done = e
        elif isinstance(e, ErrorEvent):
            error = e.message
    return {
        "outcome": outcome,
        "final_sql": final_sql,
        "attempts": attempts,
        "cost_usd": done.cost_usd if done else None,
        "ttft_ms": done.ttft_ms if done else None,
        "total_ms": done.total_ms if done else None,
        "error": error,
    }
