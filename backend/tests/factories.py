"""Tiny hand-made nflverse-shaped frames, so backend tests never touch the network."""

import polars as pl

from lineup_lab.ingest.stats import STAT_COLUMNS, RawFrames

# (gsis_id, display_name, position, team, pfr_id)
PLAYERS = [
    ("00-0001", "Puka Nacua", "WR", "LA", "NacuPu00"),
    ("00-0002", "Geno Smith", "QB", "LV", "SmitGe00"),
    ("00-0003", "DeVonta Smith", "WR", "PHI", "SmitDe00"),
    ("00-0004", "Christian McCaffrey", "RB", "SF", "McCaCh01"),
    ("00-0009", "Old Timer", "QB", "FA", "TimeOl00"),  # no stats in loaded seasons
]

# (season, week, season_type)
WEEKS = [
    (2025, 1, "REG"),
    (2025, 2, "REG"),
    (2025, 19, "POST"),
    (2026, 1, "REG"),
    (2026, 2, "REG"),
    (2026, 3, "REG"),
]


def _stat_row(
    pid: str, name: str, pos: str, team: str, season: int, week: int, stype: str, k: int
) -> dict:
    row = {c: 0 for c in STAT_COLUMNS}
    row.update(
        player_id=pid,
        player_display_name=name,
        position=pos,
        team=team,
        opponent_team="SEA",
        season=season,
        week=week,
        season_type=stype,
        game_id=f"{season}_{week:02d}_{team}_SEA",
        targets=k + week,
        receptions=k + week - 2,
        receiving_yards=10 * (k + week),
        target_share=round(0.1 * k, 3),
        fantasy_points_ppr=float(10 * k + week),
    )
    return row


def make_frames(*, drop_schedule_column: str | None = None) -> RawFrames:
    stats = []
    for i, (pid, name, pos, team, _pfr) in enumerate(PLAYERS[:4], start=1):
        for season, week, stype in WEEKS:
            if stype == "POST" and team != "LA":
                continue
            stats.append(_stat_row(pid, name, pos, team, season, week, stype, k=i))
    player_stats = pl.DataFrame(stats, infer_schema_length=None)
    players = pl.DataFrame(
        [
            dict(gsis_id=g, display_name=n, position=p, latest_team=t, pfr_id=f)
            for g, n, p, t, f in PLAYERS
        ]
    )
    snaps = pl.DataFrame(
        [
            dict(
                pfr_player_id=f,
                player=n,
                team=t,
                season=s,
                week=w,
                game_type=st,
                offense_snaps=50 + w,
                offense_pct=0.8,
            )
            for _g, n, _p, t, f in PLAYERS[:4]
            for s, w, st in WEEKS
            if st == "REG"
        ]
        + [
            dict(
                pfr_player_id="UnknownX00",
                player="Nobody",
                team="SEA",
                season=2026,
                week=1,
                game_type="REG",
                offense_snaps=1,
                offense_pct=0.01,
            )
        ]
    )
    schedules = pl.DataFrame(
        [
            dict(
                game_id=f"{s}_{w:02d}_LA_SEA",
                season=s,
                week=w,
                game_type=st,
                gameday=f"{s}-09-{10 + w % 20:02d}",
                away_team="LA",
                home_team="SEA",
                away_score=24,
                home_score=20,
            )
            for s, w, st in WEEKS
        ]
    )
    if drop_schedule_column:
        schedules = schedules.drop(drop_schedule_column)
    return RawFrames(
        player_stats=player_stats, players=players, snap_counts=snaps, schedules=schedules
    )
