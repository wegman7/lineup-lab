from pathlib import Path

import pytest

from lineup_lab.ingest.stats import build_stats_db
from tests.factories import make_frames


@pytest.fixture
def stats_db(tmp_path) -> Path:
    path = tmp_path / "stats.duckdb"
    build_stats_db(make_frames(), path)
    return path
