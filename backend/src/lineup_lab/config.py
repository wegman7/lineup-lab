"""Every environment variable the app reads, in one place."""

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    stats_db_path: Path
    model: str
    effort_route: str
    effort_sql: str
    effort_answer: str
    daily_cap_usd: float
    rate_limit_per_hour: int
    max_question_chars: int
    sql_max_attempts: int
    sql_max_rows: int
    static_dir: Path | None


@cache
def get_settings() -> Settings:
    env = os.environ.get
    static_dir = env("STATIC_DIR")
    return Settings(
        stats_db_path=Path(env("STATS_DB_PATH", REPO_ROOT / "data" / "stats.duckdb")),
        model=env("LLM_MODEL", "claude-opus-5-5"),
        effort_route=env("EFFORT_ROUTE", "low"),
        effort_sql=env("EFFORT_SQL", "medium"),
        effort_answer=env("EFFORT_ANSWER", "low"),
        daily_cap_usd=float(env("DAILY_CAP_USD", "5.0")),
        rate_limit_per_hour=int(env("RATE_LIMIT_PER_HOUR", "20")),
        max_question_chars=500,
        sql_max_attempts=3,
        sql_max_rows=50,
        static_dir=Path(static_dir) if static_dir else None,
    )
