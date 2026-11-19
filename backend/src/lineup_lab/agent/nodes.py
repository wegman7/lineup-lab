"""Graph nodes. Each is our own code calling the stats DB, the resolver, or the LLM directly;
LangGraph only decides which node runs next. Nodes report progress through the stream writer."""

import asyncio
import time
from dataclasses import dataclass

from langgraph.config import get_stream_writer

from lineup_lab.agent import prompts
from lineup_lab.agent.events import SourceEvent, StepEvent, TokenEvent
from lineup_lab.agent.state import AgentState
from lineup_lab.config import Settings
from lineup_lab.players.resolver import PlayerResolver, Resolution
from lineup_lab.stats.db import SqlError, StatsDB
from lineup_lab.stats.schema import schema_prompt


@dataclass
class AgentDeps:
    db: StatsDB
    resolver: PlayerResolver
    llm: object  # lineup_lab.llm.client.LLM, or a test fake with the same methods
    settings: Settings


def _ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _player_line(r: Resolution) -> str:
    p = r.player
    return f"{p.name} (player_id {p.player_id}; {p.team}, {p.position})"


def _resolution_detail(r: Resolution) -> dict:
    return {
        "text": r.text,
        "status": r.status,
        "name": r.player.name if r.player else None,
        "player_id": r.player.player_id if r.player else None,
        "candidates": [f"{c.name} ({c.team}, {c.position})" for c in r.candidates],
    }


class Nodes:
    def __init__(self, deps: AgentDeps):
        self.d = deps
        cov = deps.db.coverage()
        self.as_of = f"Week {cov.as_of_week}, {cov.as_of_season}"
        fmt = dict(
            seasons=" and ".join(str(s) for s in cov.seasons),
            as_of_week=cov.as_of_week,
            as_of_season=cov.as_of_season,
        )
        self.router_system = prompts.ROUTER_SYSTEM.format(**fmt)
        self.sql_system = prompts.SQL_SYSTEM.format(schema=schema_prompt(deps.db), **fmt)
        self.coverage_text = (
            f"weekly player stats for the {fmt['seasons']} seasons, through {self.as_of}"
        )

    async def route(self, state: AgentState) -> dict:
        write = get_stream_writer()
        start = time.perf_counter()
        write(StepEvent("route", "route", "started", "Choosing a route"))
        decision, stats = await self.d.llm.parse(
            self.router_system,
            [{"role": "user", "content": state["question"]}],
            prompts.RouteDecision,
            effort=self.d.settings.effort_route,
        )
        write(StepEvent(
            "route", "route", "done", f"Route: {decision.route}",
            {"route": decision.route, "reason": decision.reason}, _ms(start),
        ))  # fmt: skip
        return {
            "route": decision.route,
            "route_reason": decision.reason,
            "mentions": decision.player_mentions,
            "calls": [stats],
        }

    async def resolve(self, state: AgentState) -> dict:
        start = time.perf_counter()
        resolutions = [self.d.resolver.resolve(m) for m in state.get("mentions", [])]
        if resolutions:
            summary = ", ".join(
                f'"{r.text}" → {r.player.name}' if r.player else f'"{r.text}" → {r.status}'
                for r in resolutions
            )
            get_stream_writer()(StepEvent(
                "resolve", "resolve", "done", f"Resolved {summary}",
                {"resolutions": [_resolution_detail(r) for r in resolutions]}, _ms(start),
            ))  # fmt: skip
        return {"resolutions": resolutions}

    async def gen_sql(self, state: AgentState) -> dict:
        attempts = state.get("sql_attempts", [])
        n = len(attempts) + 1
        start = time.perf_counter()
        get_stream_writer()(StepEvent(f"sql-{n}", "sql", "started", f"SQL · attempt {n}"))
        players = [_player_line(r) for r in state.get("resolutions", []) if r.player]
        draft, stats = await self.d.llm.parse(
            self.sql_system,
            [{"role": "user",
              "content": prompts.sql_user_message(state["question"], players, attempts)}],
            prompts.SqlDraft,
            effort=self.d.settings.effort_sql,
        )  # fmt: skip
        return {
            "draft": {"sql": draft.sql, "label": draft.label, "gen_ms": _ms(start)},
            "calls": [stats],
        }

    async def run_sql(self, state: AgentState) -> dict:
        write = get_stream_writer()
        draft = state["draft"]
        n = len(state.get("sql_attempts", [])) + 1
        detail = {"sql": draft["sql"], "attempt": n, "gen_ms": draft["gen_ms"]}
        try:
            result = await asyncio.to_thread(
                self.d.db.run_sql, draft["sql"], self.d.settings.sql_max_rows
            )
        except SqlError as e:
            write(StepEvent(f"sql-{n}", "sql", "failed", f"SQL · attempt {n} ✗",
                            {**detail, "error": e.message}, draft["gen_ms"]))  # fmt: skip
            return {"sql_attempts": [{"sql": draft["sql"], "error": e.message}]}
        write(StepEvent(
            f"sql-{n}", "sql", "done",
            f"SQL · attempt {n} ✓ · {result.row_count} rows · {result.duration_ms}ms",
            {**detail, "row_count": result.row_count, "label": draft["label"]},
            draft["gen_ms"] + result.duration_ms,
        ))  # fmt: skip
        write(SourceEvent(1, "stat", draft["label"], result.columns, result.rows,
                          result.row_count, result.truncated))  # fmt: skip
        return {
            "sql_attempts": [{"sql": draft["sql"], "error": None}],
            "result": result,
            "result_label": draft["label"],
        }

    async def answer(self, state: AgentState) -> dict:
        write = get_stream_writer()
        start = time.perf_counter()
        write(StepEvent("answer", "answer", "started", "Writing the answer"))
        r = state["result"]
        assumptions = [
            f"Assuming {x.player.name} ({x.player.team}, {x.player.position})."
            for x in state.get("resolutions", [])
            if x.status == "assumed"
        ]
        source = prompts.format_source(1, state["result_label"], r.columns, r.rows, r.row_count)
        text, stats = await self.d.llm.stream_text(
            prompts.ANSWER_SYSTEM,
            [{"role": "user", "content": prompts.answer_user_message(
                state["question"], self.as_of, assumptions, source)}],
            effort=self.d.settings.effort_answer,
            on_text=lambda t: write(TokenEvent(t)),
        )  # fmt: skip
        write(StepEvent(
            "answer", "answer", "done", f"Answer · {stats.output_tokens} tokens",
            {"model": stats.model, "input_tokens": stats.input_tokens,
             "output_tokens": stats.output_tokens}, _ms(start),
        ))  # fmt: skip
        return {"answer": text, "calls": [stats]}

    async def decline(self, state: AgentState) -> dict:
        reason, text = self._decline_text(state)
        write = get_stream_writer()
        write(StepEvent("decline", "decline", "done", reason, {"reason": reason}, 0))
        write(TokenEvent(text))
        return {"answer": text}

    def _decline_text(self, state: AgentState) -> tuple[str, str]:
        route = state.get("route")
        if route == "podcasts":
            return "Podcasts not loaded", (
                "Podcast search isn't loaded yet. For now I can answer questions from "
                f"{self.coverage_text}. Try asking for a player's targets or fantasy points."
            )
        if route == "out_of_scope":
            return "Out of scope", (
                f"That's outside what I can answer. I have {self.coverage_text}, but no injury "
                "news, projections, or other sports."
            )
        if route == "ambiguous":
            return "Unclear who or what", (
                "I'm not sure who you mean. Ask again with the player's full name."
            )
        for r in state.get("resolutions", []):
            if r.status == "unknown":
                return "Unknown player", (
                    f'I couldn\'t find "{r.text}" in {self.coverage_text}. Check the spelling, '
                    "or use the player's full name."
                )
            if r.status == "ambiguous":
                options = " or ".join(f"{c.name} ({c.team}, {c.position})" for c in r.candidates)
                return "Ambiguous player", f"Did you mean {options}? Ask again with the full name."
        return "SQL failed", (
            "I couldn't get that stat from the database after several tries, so I won't guess. "
            "The failed queries are in Under the hood."
        )
