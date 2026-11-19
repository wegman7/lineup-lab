import logging

from lineup_lab.players.resolver import PlayerResolver
from lineup_lab.stats.db import PlayerRow


def _p(pid, name, pts, pos="WR", team="LA"):
    return PlayerRow(pid, name, pos, team, pts)


PLAYERS = [
    _p("1", "Christian McCaffrey", 250, "RB", "SF"),
    _p("2", "Puka Nacua", 280),
    _p("3", "Jaxon Smith-Njigba", 260, team="SEA"),
    _p("4", "Amon-Ra St. Brown", 240, team="DET"),
    _p("5", "Marvin Harrison Jr.", 150, team="ARI"),
]
ALIASES = {"cmc": "Christian McCaffrey", "jsn": "Jaxon Smith-Njigba"}


def r(players=PLAYERS, aliases=ALIASES):
    return PlayerResolver(players, aliases)


def test_alias():
    res = r().resolve("CMC")
    assert res.status == "resolved" and res.player.name == "Christian McCaffrey"


def test_exact_full_name_case_and_punctuation():
    assert r().resolve("amon-ra st brown").player.player_id == "4"
    assert r().resolve("Marvin Harrison").player.player_id == "5"  # suffix stripped


def test_first_name():
    res = r().resolve("Puka")
    assert res.status == "resolved" and res.player.name == "Puka Nacua"


def test_last_name():
    assert r().resolve("Nacua").player.player_id == "2"


def test_misspelling():
    res = r().resolve("Christian McCafrey")
    assert res.status == "resolved" and res.player.player_id == "1"


def test_dominant_assumed():
    players = [_p("a", "Geno Smith", 300, "QB"), _p("b", "DeVonta Smith", 40)]
    res = r(players, {}).resolve("Smith")
    assert res.status == "assumed" and res.player.player_id == "a"
    assert [c.player_id for c in res.candidates] == ["a", "b"]


def test_ambiguous_without_dominant():
    players = [_p("a", "Geno Smith", 300, "QB"), _p("b", "DeVonta Smith", 200)]
    res = r(players, {}).resolve("Smith")
    assert res.status == "ambiguous" and res.player is None
    assert [c.player_id for c in res.candidates] == ["a", "b"]


def test_unknown_name():
    res = r().resolve("Kupp")
    assert res.status == "unknown" and res.player is None and res.candidates == []


def test_alias_to_missing_player_is_dropped(caplog):
    with caplog.at_level(logging.WARNING):
        res = r(aliases={"tank": "Tank Dell"}).resolve("tank")
    assert res.status == "unknown"
    assert "Tank Dell" in caplog.text


def test_from_db_loads_alias_file(stats_db):
    from lineup_lab.stats.db import StatsDB

    res = PlayerResolver.from_db(StatsDB(stats_db)).resolve("cmc")
    assert res.player.name == "Christian McCaffrey"


def test_players_without_a_name_are_skipped():
    res = r([*PLAYERS, PlayerRow("x", None, "WR", "LA", 10.0)], {}).resolve("Puka")
    assert res.player.player_id == "2"
