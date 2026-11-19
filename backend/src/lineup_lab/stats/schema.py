"""Schema prompt for text-to-SQL, generated from the database so it can't drift."""

from itertools import groupby

from lineup_lab.stats.db import StatsDB


def schema_prompt(db: StatsDB) -> str:
    lines = []
    for table, cols in groupby(db.columns(), key=lambda c: c[0]):
        lines.append(f"{table}(")
        for _t, name, dtype, comment in cols:
            lines.append(f"  {name} {dtype}" + (f" -- {comment}" if comment else ""))
        lines.append(")")
    season, week = db.as_of()
    lines.append(f"Data as of Week {week}, {season}.")
    return "\n".join(lines)
