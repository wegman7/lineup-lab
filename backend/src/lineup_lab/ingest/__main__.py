"""Refresh job entry point: `python -m lineup_lab.ingest stats`."""

import sys

from lineup_lab.config import get_settings
from lineup_lab.ingest.stats import SEASONS, build_stats_db, fetch_frames


def main(argv: list[str]) -> int:
    if argv[:1] != ["stats"]:
        print("usage: python -m lineup_lab.ingest stats", file=sys.stderr)
        return 2
    path = get_settings().stats_db_path
    report = build_stats_db(fetch_frames(SEASONS), path)
    print(f"wrote {path}")
    print(f"as of Week {report.as_of_week}, {report.as_of_season}")
    for table, n in report.row_counts.items():
        print(f"  {table}: {n:,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
