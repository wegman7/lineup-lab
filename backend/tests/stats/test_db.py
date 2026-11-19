import pytest

from lineup_lab.stats.db import SqlError, StatsDB


@pytest.fixture
def db(stats_db):
    return StatsDB(stats_db)


def test_select_returns_rows(db):
    r = db.run_sql(
        "SELECT player_name, sum(targets) AS t FROM weekly_stats "
        "WHERE season = 2026 GROUP BY 1 ORDER BY t DESC",
        max_rows=50,
    )
    assert r.columns == ["player_name", "t"]
    assert r.rows[0][0] == "Christian McCaffrey"
    assert r.row_count == 4 and not r.truncated
    assert r.duration_ms >= 0


def test_trailing_semicolon_and_comments_ok(db):
    r = db.run_sql("-- leaders\nSELECT 1 AS x; ", max_rows=5)
    assert r.rows == [[1]]


def test_truncates_large_results(db):
    r = db.run_sql("SELECT player_id FROM weekly_stats WHERE season = 2026 LIMIT 5", max_rows=2)
    assert len(r.rows) == 2
    assert r.row_count == 5
    assert r.truncated


def test_values_are_json_safe(db):
    import json

    r = db.run_sql("SELECT gameday, 1.23456 AS f FROM games LIMIT 1", max_rows=5)
    json.dumps(r.rows)
    assert isinstance(r.rows[0][0], str)
    assert r.rows[0][1] == 1.235


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "COPY weekly_stats TO '/tmp/lineup_x.csv'",
        "ATTACH ':memory:' AS x",
        "SET enable_external_access = true",
        "INSTALL httpfs",
        "SELECT 1; DROP TABLE players",
        "DELETE FROM players",
        "WITH x AS (SELECT 1) SELECT * FROM read_text('/etc/hosts')",
    ],
)
def test_rejects_escape_attempts(db, sql):
    with pytest.raises(SqlError):
        db.run_sql(sql, max_rows=5)
    assert db.run_sql("SELECT count(*) FROM players", max_rows=1).rows == [[4]]


def test_error_message_is_readable(db):
    with pytest.raises(SqlError) as e:
        db.run_sql("SELECT targetz FROM weekly_stats", max_rows=5)
    assert "targetz" in e.value.message


def test_as_of_and_coverage(db):
    assert db.as_of() == (2026, 3)
    c = db.coverage()
    assert c.seasons == [2025, 2026] and c.as_of_week == 3 and c.as_of_season == 2026


def test_players(db):
    names = {p.name for p in db.players()}
    assert names == {"Puka Nacua", "Geno Smith", "DeVonta Smith", "Christian McCaffrey"}


def test_slow_query_is_interrupted(stats_db):
    db = StatsDB(stats_db, timeout_s=0.2)
    with pytest.raises(SqlError) as e:
        db.run_sql("SELECT count(*) FROM range(100000000) a, range(100000) b", max_rows=1)
    assert "too long" in e.value.message


def test_memory_is_capped(db):
    with pytest.raises(SqlError):
        db.run_sql("SELECT length(string_agg(repeat('x', 1000000), '')) FROM range(1000)", 1)


def test_long_strings_are_clipped(db):
    r = db.run_sql("SELECT repeat('x', 5000) AS s", max_rows=1)
    assert len(r.rows[0][0]) <= 1001 and r.rows[0][0].endswith("…")
