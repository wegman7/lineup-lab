import re

import pytest

from lineup_lab.agent.events import DoneEvent, ErrorEvent, SourceEvent, StepEvent, TokenEvent
from lineup_lab.agent.graph import AgentDeps, run_agent
from lineup_lab.agent.prompts import RouteDecision, SqlDraft
from lineup_lab.config import get_settings
from lineup_lab.llm.client import LLMError
from lineup_lab.players.resolver import PlayerResolver
from lineup_lab.stats.db import PlayerRow, StatsDB
from tests.fakes import FakeLLM

GOOD_SQL = (
    "SELECT player_name, sum(targets) AS targets FROM weekly_stats "
    "WHERE player_id = '00-0001' AND season = 2026 AND season_type = 'REG' GROUP BY 1"
)
BAD_SQL = "SELECT targetz FROM weekly_stats"


def route(r="stats", mentions=("Puka",)):
    return RouteDecision(route=r, reason="because", player_mentions=list(mentions))


def draft(sql=GOOD_SQL):
    return SqlDraft(sql=sql, label="Targets, Weeks 1–3, 2026")


@pytest.fixture
def deps_for(stats_db):
    def make(llm, resolver=None):
        db = StatsDB(stats_db)
        return AgentDeps(
            db=db, resolver=resolver or PlayerResolver.from_db(db), llm=llm, settings=get_settings()
        )

    return make


async def collect(deps, q="How many targets did Puka have?"):
    return [e async for e in run_agent(deps, q)]


def kinds(events):
    out = []
    for e in events:
        if isinstance(e, StepEvent):
            out.append(f"{e.kind}:{e.status}")
        elif isinstance(e, TokenEvent):
            if not out or out[-1] != "token":
                out.append("token")
        else:
            out.append(type(e).__name__)
    return out


def text(events):
    return "".join(e.text for e in events if isinstance(e, TokenEvent))


async def test_stat_lookup_happy_path(deps_for):
    llm = FakeLLM(parses=[route(), draft()], texts=["Puka had 15 targets [1]."], cost=0.01)
    events = await collect(deps_for(llm))
    assert kinds(events) == [
        "route:started",
        "route:done",
        "resolve:done",
        "sql:started",
        "sql:done",
        "SourceEvent",
        "answer:started",
        "token",
        "answer:done",
        "DoneEvent",
    ]
    src = next(e for e in events if isinstance(e, SourceEvent))
    assert src.n == 1 and src.rows == [["Puka Nacua", 9]] and src.label.startswith("Targets")
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.cost_usd == pytest.approx(0.03)  # route + sql + answer
    assert done.ttft_ms is not None and done.total_ms >= 0
    resolve = next(e for e in events if isinstance(e, StepEvent) and e.kind == "resolve")
    assert resolve.detail["resolutions"][0]["name"] == "Puka Nacua"
    sql_prompt = llm.calls[1]["messages"][0]["content"]
    assert "00-0001" in sql_prompt  # resolved id handed to the SQL step
    assert "weekly_stats(" in llm.calls[1]["system"]  # schema in the (cacheable) system prompt


async def test_sql_retry_then_success(deps_for):
    llm = FakeLLM(parses=[route(), draft(BAD_SQL), draft()], texts=["ok [1]"])
    events = await collect(deps_for(llm))
    sql_steps = [e for e in events if isinstance(e, StepEvent) and e.kind == "sql"]
    assert [(s.id, s.status) for s in sql_steps] == [
        ("sql-1", "started"),
        ("sql-1", "failed"),
        ("sql-2", "started"),
        ("sql-2", "done"),
    ]
    assert "targetz" in sql_steps[1].detail["error"]
    retry_prompt = llm.calls[2]["messages"][0]["content"]
    assert BAD_SQL in retry_prompt and "targetz" in retry_prompt


async def test_sql_gives_up_after_three_attempts(deps_for):
    llm = FakeLLM(parses=[route(), draft(BAD_SQL), draft(BAD_SQL), draft(BAD_SQL)])
    events = await collect(deps_for(llm))
    failed = [
        e for e in events if isinstance(e, StepEvent) and e.kind == "sql" and e.status == "failed"
    ]
    assert len(failed) == 3
    assert not any(isinstance(e, SourceEvent) for e in events)
    reply = text(events)
    assert "couldn't" in reply and not re.search(r"\d", reply)
    assert isinstance(events[-1], DoneEvent)


async def test_podcast_route_declines(deps_for):
    llm = FakeLLM(parses=[route("podcasts", ())])
    events = await collect(deps_for(llm), "What are podcasts saying about Puka?")
    assert "odcast" in text(events)
    assert not any(isinstance(e, StepEvent) and e.kind == "sql" for e in events)
    assert len(llm.calls) == 1


async def test_out_of_scope_declines(deps_for):
    llm = FakeLLM(parses=[route("out_of_scope", ())])
    events = await collect(deps_for(llm), "Who wins the NBA title?")
    assert any(isinstance(e, StepEvent) and e.kind == "decline" for e in events)
    assert text(events)


async def test_ambiguous_name_asks(deps_for):
    llm = FakeLLM(parses=[route(mentions=["Smith"])])
    events = await collect(deps_for(llm), "How many targets did Smith have?")
    reply = text(events)
    assert "Did you mean" in reply and "DeVonta Smith" in reply and "Geno Smith" in reply
    assert not any(isinstance(e, StepEvent) and e.kind == "sql" for e in events)


async def test_unknown_name_declines(deps_for):
    llm = FakeLLM(parses=[route(mentions=["Zzyzx"])])
    events = await collect(deps_for(llm))
    assert "Zzyzx" in text(events)
    assert not any(isinstance(e, StepEvent) and e.kind == "sql" for e in events)


async def test_assumed_name_passed_to_answer(deps_for):
    resolver = PlayerResolver(
        [
            PlayerRow("00-0001", "Puka Nacua", "WR", "LA", 300.0),
            PlayerRow("00-0002", "Puka Other", "QB", "LV", 10.0),
        ],
        {},
    )
    llm = FakeLLM(parses=[route(mentions=["Puka"]), draft()], texts=["Assuming ... [1]"])
    await collect(deps_for(llm, resolver))
    answer_prompt = llm.calls[-1]["messages"][0]["content"]
    assert "Assuming Puka Nacua (LA, WR)." in answer_prompt


async def test_llm_error_yields_error_event(deps_for):
    llm = FakeLLM(parses=[LLMError("declined")])
    events = await collect(deps_for(llm))
    assert isinstance(events[-1], ErrorEvent)
    assert "try again" in events[-1].message
