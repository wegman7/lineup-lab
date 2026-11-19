"""HTTP layer: POST /chat streams one question's events as SSE; GET /api/meta feeds the landing
page; the built frontend is served from the same origin (technical spec §7).

Run: uvicorn lineup_lab.api.app:create_app --factory
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lineup_lab.agent.events import ErrorEvent, Event
from lineup_lab.api.limits import RateLimiter, SpendTracker
from lineup_lab.api.sse import format_event
from lineup_lab.config import Settings, get_settings
from lineup_lab.stats.db import Coverage

log = logging.getLogger(__name__)

EXAMPLES_PATH = Path(__file__).resolve().parents[1] / "examples.yaml"
CRASH_MESSAGE = "Something went wrong on our side. Please try again."

Runner = Callable[[str, Callable[[float], None]], AsyncIterator[Event]]


class ChatRequest(BaseModel):
    question: str
    # Echoed back in a response header, so only safe characters.
    chat_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


def client_ip(request: Request) -> str:
    # Cloud Run appends the real client address to X-Forwarded-For; anything to its left
    # was supplied by the client and can't be trusted.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _real_runner(settings: Settings) -> tuple[Runner, Callable[[], Coverage]]:
    import anthropic

    from lineup_lab.agent.graph import AgentDeps, run_agent
    from lineup_lab.llm.client import LLM
    from lineup_lab.players.resolver import PlayerResolver
    from lineup_lab.stats.db import StatsDB

    db = StatsDB(settings.stats_db_path)
    resolver = PlayerResolver.from_db(db)
    client = anthropic.AsyncAnthropic()

    def runner(question: str, on_cost: Callable[[float], None]) -> AsyncIterator[Event]:
        llm = LLM(client, settings.model, on_call=lambda s: on_cost(s.cost_usd))
        return run_agent(AgentDeps(db, resolver, llm, settings), question)

    return runner, db.coverage


def create_app(
    settings: Settings | None = None,
    *,
    runner: Runner | None = None,
    coverage: Callable[[], Coverage] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if runner is None or coverage is None:
        real_runner, real_coverage = _real_runner(settings)
        runner, coverage = runner or real_runner, coverage or real_coverage
    examples = yaml.safe_load(EXAMPLES_PATH.read_text())

    app = FastAPI(title="Lineup Lab", docs_url=None, redoc_url=None)
    app.state.limiter = RateLimiter(settings.rate_limit_per_hour)
    app.state.spend = SpendTracker(settings.daily_cap_usd)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/api/meta")
    def meta() -> dict:
        return {"coverage": asdict(coverage()), "examples": examples}

    @app.post("/chat")
    async def chat(body: ChatRequest, request: Request):
        question = body.question.strip()
        if not question:
            raise HTTPException(400, "Ask a question.")
        if len(question) > settings.max_question_chars:
            raise HTTPException(400, f"Questions are limited to {settings.max_question_chars} "
                                     "characters.")  # fmt: skip
        spend: SpendTracker = app.state.spend
        if spend.exhausted():
            when = spend.resets_at().strftime("%H:%M UTC")
            return JSONResponse(
                {"detail": f"Live questions are paused for today. They resume at {when}."}, 503
            )
        wait = app.state.limiter.check(client_ip(request))
        if wait is not None:
            return JSONResponse(
                {"detail": f"You've hit the hourly question limit. Try again in "
                           f"{max(1, wait // 60)} min.", "retry_after_s": wait},
                429, headers={"Retry-After": str(wait)},
            )  # fmt: skip
        chat_id = body.chat_id or uuid.uuid4().hex
        return StreamingResponse(
            _stream(runner, question, spend.add),
            media_type="text/event-stream",
            headers={"X-Chat-Id": chat_id, "Cache-Control": "no-cache",
                     "X-Accel-Buffering": "no"},
        )  # fmt: skip

    if settings.static_dir:
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")
    return app


async def _stream(
    runner: Runner, question: str, on_cost: Callable[[float], None]
) -> AsyncIterator[bytes]:
    """Run the agent as its own task so that when the visitor leaves (Starlette cancels this
    generator), the `finally` cancels the agent and no more model calls are paid for."""
    queue: asyncio.Queue[Event | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for event in runner(question, on_cost):
                await queue.put(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("agent crashed")
            await queue.put(ErrorEvent(CRASH_MESSAGE))
        await queue.put(None)

    task = asyncio.create_task(produce())
    try:
        while (event := await queue.get()) is not None:
            yield format_event(event)
    finally:
        task.cancel()
