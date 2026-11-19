import duckdb
import pytest

from lineup_lab.ingest.stats import WEEKLY_COLUMNS, build_stats_db
from tests.factories import make_frames

EXPECTED = {
    "players": ["player_id", "name", "position", "team", "ppr_points"],
    "weekly_stats": WEEKLY_COLUMNS,
    "snap_counts": [
        "player_id",
        "player_name",
        "team",
        "season",
        "week",
        "offense_snaps",
        "offense_pct",
    ],
    "games": [
        "game_id",
        "season",
        "week",
        "game_type",
        "gameday",
        "away_team",
        "home_team",
        "away_score",
        "home_score",
    ],
    "meta": ["key", "value"],
}


def _columns(con, table):
    return [
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ? "
            "ORDER BY ordinal_position",
            [table],
        ).fetchall()
    ]


def test_tables_and_columns(stats_db):
    con = duckdb.connect(str(stats_db), read_only=True)
    for table, cols in EXPECTED.items():
        assert _columns(con, table) == cols, table


def test_as_of_week(tmp_path):
    report = build_stats_db(make_frames(), tmp_path / "s.duckdb")
    assert (report.as_of_season, report.as_of_week) == (2026, 3)
    con = duckdb.connect(str(tmp_path / "s.duckdb"), read_only=True)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    assert meta["as_of_season"] == "2026" and meta["as_of_week"] == "3"
    assert meta["seasons"] == "2025,2026"


def test_snap_counts_mapped_to_player_id(stats_db):
    con = duckdb.connect(str(stats_db), read_only=True)
    ids = {r[0] for r in con.execute("SELECT DISTINCT player_id FROM snap_counts").fetchall()}
    assert ids == {"00-0001", "00-0002", "00-0003", "00-0004"}  # unmatched pfr id dropped


def test_players_only_with_stats(stats_db):
    con = duckdb.connect(str(stats_db), read_only=True)
    names = {r[0] for r in con.execute("SELECT name FROM players").fetchall()}
    assert "Old Timer" not in names and "Puka Nacua" in names
    pts = con.execute("SELECT ppr_points FROM players WHERE name = 'Puka Nacua'").fetchone()[0]
    assert pts == pytest.approx(sum(10 + w for w in (1, 2, 19, 1, 2, 3)))


def test_column_comments_present(stats_db):
    con = duckdb.connect(str(stats_db), read_only=True)
    comments = dict(
        con.execute(
            "SELECT column_name, comment FROM duckdb_columns() WHERE table_name = 'weekly_stats'"
        ).fetchall()
    )
    for col in ("targets", "target_share", "season_type"):
        assert comments[col], col


def test_build_is_atomic(tmp_path):
    path = tmp_path / "s.duckdb"
    build_stats_db(make_frames(), path)
    before = path.read_bytes()
    with pytest.raises(Exception):  # noqa: B017 - any failure mid-build
        build_stats_db(make_frames(drop_schedule_column="home_score"), path)
    assert path.read_bytes() == before
    assert not path.with_suffix(".tmp").exists()


def test_rows_without_player_id_excluded_from_players(tmp_path):
    import polars as pl

    frames = make_frames()
    blank = frames.player_stats.head(1).with_columns(
        pl.lit(None, dtype=pl.String).alias("player_id"),
        pl.lit(None, dtype=pl.String).alias("player_display_name"),
    )
    frames.player_stats = pl.concat([frames.player_stats, blank])
    build_stats_db(frames, tmp_path / "s.duckdb")
    con = duckdb.connect(str(tmp_path / "s.duckdb"), read_only=True)
    assert con.execute("SELECT count(*) FROM players WHERE player_id IS NULL").fetchone()[0] == 0
