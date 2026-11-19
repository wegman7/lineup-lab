"""Build data/stats.duckdb from nflverse (via nflreadpy).

Only `fetch_frames` touches the network; `build_stats_db` is pure frames -> file,
so it is tested with tiny hand-made frames.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    import polars as pl

SEASONS = [2025, 2026]

STAT_COLUMNS = [
    "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
    "sacks_suffered", "passing_air_yards", "passing_epa",
    "carries", "rushing_yards", "rushing_tds", "rushing_first_downs", "rushing_fumbles_lost",
    "rushing_epa",
    "targets", "receptions", "receiving_yards", "receiving_tds", "receiving_air_yards",
    "receiving_yards_after_catch", "receiving_first_downs", "receiving_fumbles_lost",
    "receiving_epa", "target_share", "air_yards_share", "wopr", "racr",
    "fg_made", "fg_att", "pat_made",
    "fantasy_points", "fantasy_points_ppr",
]  # fmt: skip

WEEKLY_COLUMNS = [
    "player_id", "player_name", "position", "team", "opponent", "season", "week",
    "season_type", "game_id", *STAT_COLUMNS,
]  # fmt: skip

COMMENTS = {
    "players": {
        "player_id": "nflverse GSIS id; joins to weekly_stats.player_id and snap_counts.player_id",
        "team": "most recent team in the loaded data",
        "ppr_points": "total PPR fantasy points across all loaded weeks (popularity proxy)",
    },
    "weekly_stats": {
        "player_id": "nflverse GSIS id",
        "player_name": "full display name, e.g. 'Puka Nacua'",
        "team": "player's team that week (abbreviation, e.g. 'LA', 'KC')",
        "opponent": "opponent team abbreviation",
        "week": "week number; regular season 1-18, postseason 19+",
        "season_type": "'REG' regular season or 'POST' postseason",
        "sacks_suffered": "times sacked (QB)",
        "passing_air_yards": "air yards on all pass attempts, complete or not",
        "passing_epa": "expected points added on pass plays",
        "rushing_epa": "expected points added on rushes",
        "targets": "times targeted by a pass",
        "receiving_air_yards": "air yards on all targets",
        "receiving_epa": "expected points added on targets",
        "target_share": "share of team targets that week, 0-1",
        "air_yards_share": "share of team air yards that week, 0-1",
        "wopr": "weighted opportunity rating: 1.5*target_share + 0.7*air_yards_share",
        "racr": "receiving air conversion ratio: receiving_yards / receiving_air_yards",
        "fantasy_points": "standard (non-PPR) fantasy points",
        "fantasy_points_ppr": "PPR fantasy points (1 point per reception)",
    },
    "snap_counts": {
        "offense_snaps": "offensive snaps played",
        "offense_pct": "share of team offensive snaps played, 0-1",
    },
    "games": {
        "game_type": "'REG' regular season; 'WC','DIV','CON','SB' postseason",
        "gameday": "game date",
    },
}


@dataclass
class RawFrames:
    player_stats: pl.DataFrame
    players: pl.DataFrame
    snap_counts: pl.DataFrame
    schedules: pl.DataFrame


@dataclass
class BuildReport:
    as_of_season: int
    as_of_week: int
    row_counts: dict[str, int]


def fetch_frames(seasons: list[int]) -> RawFrames:
    import nflreadpy as nfl

    return RawFrames(
        player_stats=nfl.load_player_stats(seasons, summary_level="week"),
        players=nfl.load_players(),
        snap_counts=nfl.load_snap_counts(seasons),
        schedules=nfl.load_schedules(seasons),
    )


def build_stats_db(frames: RawFrames, out_path: Path, seasons: list[int] = SEASONS) -> BuildReport:
    """Build to a temp file, then rename over out_path, so a failed build never leaves a
    half-written database where the app expects a good one."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    _remove(tmp)
    try:
        con = duckdb.connect(str(tmp))
        try:
            report = _build(con, frames, seasons)
        finally:
            con.close()
        os.replace(tmp, out_path)
        return report
    finally:
        _remove(tmp)


def _remove(path: Path) -> None:
    for p in (path, Path(f"{path}.wal")):
        p.unlink(missing_ok=True)


def _build(con: duckdb.DuckDBPyConnection, f: RawFrames, seasons: list[int]) -> BuildReport:
    for name, frame in [("raw_stats", f.player_stats), ("raw_players", f.players),
                        ("raw_snaps", f.snap_counts), ("raw_sched", f.schedules)]:  # fmt: skip
        con.register(name, frame.to_arrow())
    season_list = ", ".join(str(int(s)) for s in seasons)
    stats_sql = ", ".join(STAT_COLUMNS)

    con.execute(f"""
        CREATE TABLE weekly_stats AS
        SELECT player_id, player_display_name AS player_name, position, team,
               opponent_team AS opponent, season, week, season_type, game_id, {stats_sql}
        FROM raw_stats WHERE season IN ({season_list})
        ORDER BY season, week, player_id
    """)
    con.execute("""
        CREATE TABLE players AS
        SELECT player_id,
               arg_max(player_name, season * 100 + week) AS name,
               arg_max(position, season * 100 + week) AS position,
               arg_max(team, season * 100 + week) AS team,
               round(sum(coalesce(fantasy_points_ppr, 0)), 2) AS ppr_points
        FROM weekly_stats WHERE player_id IS NOT NULL
        GROUP BY player_id ORDER BY ppr_points DESC
    """)
    con.execute(f"""
        CREATE TABLE snap_counts AS
        SELECT p.gsis_id AS player_id, s.player AS player_name, s.team, s.season, s.week,
               s.offense_snaps, s.offense_pct
        FROM raw_snaps s JOIN raw_players p ON s.pfr_player_id = p.pfr_id
        WHERE p.gsis_id IS NOT NULL AND s.season IN ({season_list})
        ORDER BY s.season, s.week, player_id
    """)
    con.execute(f"""
        CREATE TABLE games AS
        SELECT game_id, season, week, game_type, CAST(gameday AS DATE) AS gameday,
               away_team, home_team, away_score, home_score
        FROM raw_sched WHERE season IN ({season_list}) ORDER BY season, week, game_id
    """)
    as_of_season, as_of_week = con.execute("""
        SELECT season, max(week) FROM weekly_stats
        WHERE season = (SELECT max(season) FROM weekly_stats) AND season_type = 'REG'
        GROUP BY season
    """).fetchone()
    con.execute("CREATE TABLE meta (key VARCHAR, value VARCHAR)")
    con.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("as_of_season", str(as_of_season)),
        ("as_of_week", str(as_of_week)),
        ("seasons", ",".join(str(s) for s in seasons)),
        ("built_at", datetime.now(UTC).isoformat(timespec="seconds")),
    ])  # fmt: skip
    for table, cols in COMMENTS.items():
        for col, text in cols.items():
            con.execute(f"COMMENT ON COLUMN {table}.{col} IS '{text.replace("'", "''")}'")
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("players", "weekly_stats", "snap_counts", "games")}  # fmt: skip
    return BuildReport(as_of_season, as_of_week, counts)
