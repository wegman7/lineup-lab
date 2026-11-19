"""Run the SQL eval set through the real agent and write evals/results/sql-<date>.json.

    uv run --env-file .env python -m evals.run_sql_eval [--limit N] [--ids a,b]

Spends real API money (~$0.05 per case with Opus 5.5), unless LLM_PROVIDER=local.
"""

import argparse
import asyncio
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evals.grading import grade, outcome_from_events
from lineup_lab.agent.graph import AgentDeps, run_agent
from lineup_lab.stats.db import SqlError

HERE = Path(__file__).parent
CASES = HERE / "sql_cases.yaml"
FULL_ROWS = 10_000  # grade on complete results, not the 50-row display cap


async def run_case(deps: AgentDeps, case: dict) -> dict:
    events = [e async for e in run_agent(deps, case["question"])]
    o = outcome_from_events(events)
    sql_ok = None
    if case.get("reference_sql"):
        reference = deps.db.run_sql(case["reference_sql"], FULL_ROWS)
        actual = None
        if o["final_sql"]:
            try:
                actual = deps.db.run_sql(o["final_sql"], FULL_ROWS)
            except SqlError:
                actual = None
        sql_ok = grade(reference, actual)
    answer = "".join(getattr(e, "text", "") for e in events if type(e).__name__ == "TokenEvent")
    return {
        "id": case["id"],
        "question": case["question"],
        "expected_route": case["route"],
        "route_ok": o["outcome"] == case["route"],
        "sql_ok": sql_ok,
        **o,
        "answer": answer,
    }


def _ratio(values: list[bool]) -> str:
    return f"{sum(values)}/{len(values)}"


def summarize(rows: list[dict]) -> dict:
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    ttfts = [r["ttft_ms"] for r in rows if r["ttft_ms"] is not None]
    graded = [r["sql_ok"] for r in rows if r["sql_ok"] is not None]
    return {
        "route_accuracy": _ratio([r["route_ok"] for r in rows]),
        "sql_accuracy": _ratio(graded),
        "median_cost_usd": round(statistics.median(costs), 4) if costs else None,
        "total_cost_usd": round(sum(costs), 4),
        "median_ttft_ms": round(statistics.median(ttfts)) if ttfts else None,
        "max_ttft_ms": max(ttfts) if ttfts else None,
        "mean_sql_attempts": round(statistics.mean(r["attempts"] for r in rows), 2),
    }


async def main() -> None:
    from lineup_lab.config import get_settings
    from lineup_lab.llm import make_llm
    from lineup_lab.players.resolver import PlayerResolver
    from lineup_lab.stats.db import StatsDB

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="comma-separated case ids")
    args = ap.parse_args()

    cases = yaml.safe_load(CASES.read_text())
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    cases = cases[: args.limit] if args.limit else cases

    settings = get_settings()
    db = StatsDB(settings.stats_db_path)
    llm = make_llm(settings)
    deps = AgentDeps(db, PlayerResolver.from_db(db), llm, settings)
    rows = []
    for case in cases:
        row = await run_case(deps, case)
        mark = {True: "✓", False: "✗", None: "-"}
        print(
            f"{case['id']:30} route {mark[row['route_ok']]}  sql {mark[row['sql_ok']]}  "
            f"tries {row['attempts']}  ${row['cost_usd'] or 0:.4f}  ttft {row['ttft_ms']}ms"
        )
        rows.append(row)

    cov = db.coverage()
    summary = summarize(rows)
    out = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": settings.llm_provider,
        "model": settings.model,
        "efforts": {"route": settings.effort_route, "sql": settings.effort_sql,
                    "answer": settings.effort_answer},
        "data_as_of": f"Week {cov.as_of_week}, {cov.as_of_season}",
        "summary": summary,
        "cases": rows,
    }  # fmt: skip
    (HERE / "results").mkdir(exist_ok=True)
    path = HERE / "results" / f"sql-{datetime.now(UTC):%Y-%m-%d}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2))
    print(f"wrote {path}")


if __name__ == "__main__":
    asyncio.run(main())
