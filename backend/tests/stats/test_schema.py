import re

from lineup_lab.stats.db import StatsDB
from lineup_lab.stats.schema import schema_prompt


def test_schema_prompt_deterministic_and_complete(stats_db):
    db = StatsDB(stats_db)
    a, b = schema_prompt(db), schema_prompt(db)
    assert a == b
    for table in ("players", "weekly_stats", "snap_counts", "games"):
        assert f"{table}(" in a
    assert "meta" not in a.split("Data as of")[0]
    assert re.search(r"\btargets \w+ -- times targeted by a pass", a)
    assert "Data as of Week 3, 2026." in a
