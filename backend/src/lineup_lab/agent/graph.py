"""route → resolve → gen_sql ⇄ run_sql → answer, with decline for everything else.

START → route ─stats→ resolve ─names ok→ gen_sql → run_sql ─ok→ answer → END
              └other→ decline           └bad name→ decline   ├error, tries left→ gen_sql
                                                             └error, no tries→ decline
"""

import time
from collections.abc import AsyncIterator

import anthropic
from langgraph.graph import END, START, StateGraph

from lineup_lab.agent.events import DoneEvent, ErrorEvent, Event, TokenEvent
from lineup_lab.agent.nodes import AgentDeps, Nodes
from lineup_lab.agent.state import AgentState
from lineup_lab.llm.client import LLMError

__all__ = ["AgentDeps", "build_graph", "run_agent"]

ERROR_MESSAGE = "Something went wrong talking to the model. Please try again."


def build_graph(deps: AgentDeps):
    n = Nodes(deps)
    max_attempts = deps.settings.sql_max_attempts

    def after_route(s: AgentState) -> str:
        return "resolve" if s["route"] == "stats" else "decline"

    def after_resolve(s: AgentState) -> str:
        ok = all(r.player for r in s.get("resolutions", []))
        return "gen_sql" if ok else "decline"

    def after_run_sql(s: AgentState) -> str:
        if s.get("result") is not None:
            return "answer"
        return "gen_sql" if len(s["sql_attempts"]) < max_attempts else "decline"

    g = StateGraph(AgentState)
    for name in ("route", "resolve", "gen_sql", "run_sql", "answer", "decline"):
        g.add_node(name, getattr(n, name))
    g.add_edge(START, "route")
    g.add_conditional_edges("route", after_route, ["resolve", "decline"])
    g.add_conditional_edges("resolve", after_resolve, ["gen_sql", "decline"])
    g.add_edge("gen_sql", "run_sql")
    g.add_conditional_edges("run_sql", after_run_sql, ["answer", "gen_sql", "decline"])
    g.add_edge("answer", END)
    g.add_edge("decline", END)
    return g.compile()


async def run_agent(deps: AgentDeps, question: str, graph=None) -> AsyncIterator[Event]:
    graph = graph or build_graph(deps)
    start = time.perf_counter()
    ttft_ms = None
    final: dict = {}
    try:
        async for mode, chunk in graph.astream(
            {"question": question}, stream_mode=["custom", "values"]
        ):
            if mode == "values":
                final = chunk
                continue
            if isinstance(chunk, TokenEvent) and ttft_ms is None:
                ttft_ms = round((time.perf_counter() - start) * 1000)
            yield chunk
    except (LLMError, anthropic.APIError):
        yield ErrorEvent(ERROR_MESSAGE)
        return
    calls = final.get("calls", [])
    yield DoneEvent(
        ttft_ms=ttft_ms,
        total_ms=round((time.perf_counter() - start) * 1000),
        cost_usd=round(sum(c.cost_usd for c in calls), 6),
        input_tokens=sum(c.input_tokens for c in calls),
        output_tokens=sum(c.output_tokens for c in calls),
    )
