from evals.run_sql_eval import run_case, summarize
from lineup_lab.agent.graph import AgentDeps
from lineup_lab.agent.prompts import RouteDecision, SqlDraft
from lineup_lab.config import get_settings
from lineup_lab.players.resolver import PlayerResolver
from lineup_lab.stats.db import StatsDB
from tests.fakes import FakeLLM

REF = (
    "SELECT sum(targets) FROM weekly_stats WHERE player_id = '00-0001' "
    "AND season = 2026 AND season_type = 'REG'"
)


def deps(stats_db, llm):
    db = StatsDB(stats_db)
    return AgentDeps(db, PlayerResolver.from_db(db), llm, get_settings())


async def test_run_case_grades_sql_and_route(stats_db):
    llm = FakeLLM(
        parses=[
            RouteDecision(route="stats", reason="r", player_mentions=["Puka"]),
            SqlDraft(
                sql="SELECT player_name, sum(targets) AS t FROM weekly_stats "
                "WHERE player_id = '00-0001' AND season = 2026 GROUP BY 1",
                label="Targets",
            ),
        ],
        texts=["ok [1]"],
    )
    case = {"id": "c1", "question": "Puka targets?", "route": "stats", "reference_sql": REF}
    row = await run_case(deps(stats_db, llm), case)
    assert row["route_ok"] is True and row["sql_ok"] is True and row["attempts"] == 1


async def test_run_case_route_only(stats_db):
    llm = FakeLLM(parses=[RouteDecision(route="stats", reason="r", player_mentions=[])])
    llm.parses.append(SqlDraft(sql="SELECT 1", label="x"))
    llm.texts.append("x")
    case = {"id": "c2", "question": "NBA?", "route": "out_of_scope", "reference_sql": None}
    row = await run_case(deps(stats_db, llm), case)
    assert row["route_ok"] is False and row["sql_ok"] is None


def test_summarize():
    rows = [
        {"route_ok": True, "sql_ok": True, "cost_usd": 0.02, "ttft_ms": 1000, "attempts": 1},
        {"route_ok": True, "sql_ok": False, "cost_usd": 0.04, "ttft_ms": 3000, "attempts": 3},
        {"route_ok": False, "sql_ok": None, "cost_usd": 0.01, "ttft_ms": None, "attempts": 0},
    ]
    s = summarize(rows)
    assert s["route_accuracy"] == "2/3"
    assert s["sql_accuracy"] == "1/2"
    assert s["median_cost_usd"] == 0.02 and s["total_cost_usd"] == 0.07
    assert s["median_ttft_ms"] == 2000
