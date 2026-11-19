from pathlib import Path

import pytest

from lineup_lab.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    for var in ("STATS_DB_PATH", "LLM_MODEL", "DAILY_CAP_USD", "RATE_LIMIT_PER_HOUR", "STATIC_DIR"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults():
    s = get_settings()
    assert s.model == "claude-opus-5-5"
    assert s.daily_cap_usd == 5.0
    assert s.rate_limit_per_hour == 20
    assert s.max_question_chars == 500
    assert s.sql_max_attempts == 3
    assert s.sql_max_rows == 50
    assert s.stats_db_path.name == "stats.duckdb"
    assert s.stats_db_path.parent.name == "data"
    assert s.static_dir is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DAILY_CAP_USD", "2.5")
    monkeypatch.setenv("LLM_MODEL", "x")
    monkeypatch.setenv("STATIC_DIR", "/srv/static")
    s = get_settings()
    assert s.daily_cap_usd == 2.5
    assert s.model == "x"
    assert s.static_dir == Path("/srv/static")
