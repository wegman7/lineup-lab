import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from lineup_lab.agent.events import DoneEvent, SourceEvent, StepEvent, TokenEvent
from lineup_lab.api.app import create_app
from lineup_lab.config import get_settings
from lineup_lab.stats.db import Coverage

COVERAGE = Coverage(seasons=[2025, 2026], as_of_season=2026, as_of_week=10)


async def happy_runner(question, on_cost):
    yield StepEvent("route", "route", "done", "Route: stats", {"route": "stats"}, 5)
    yield SourceEvent(1, "stat", "Targets", ["player_name", "t"], [["Puka Nacua", 9]], 1, False)
    on_cost(0.01)
    yield TokenEvent("Puka had 9 [1].")
    yield DoneEvent(ttft_ms=10, total_ms=20, cost_usd=0.01, input_tokens=100, output_tokens=10)


def make_app(runner=happy_runner, **settings_overrides):
    settings = get_settings()
    if settings_overrides:
        from dataclasses import replace

        settings = replace(settings, **settings_overrides)
    return create_app(settings, runner=runner, coverage=lambda: COVERAGE)


def parse_frames(body: str):
    frames = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        frames.append((lines["event"], json.loads(lines["data"])))
    return frames


async def post(app, json_body, headers=None):
    transport = httpx.ASGITransport(app=app, client=("9.9.9.9", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.post("/chat", json=json_body, headers=headers or {})


async def test_stream_frames_in_order():
    r = await post(make_app(), {"question": "How many targets did Puka have?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert len(r.headers["x-chat-id"]) == 32
    frames = parse_frames(r.text)
    assert [f[0] for f in frames] == ["step", "source", "token", "done"]
    assert frames[1][1]["rows"] == [["Puka Nacua", 9]]
    assert frames[3][1]["cost_usd"] == 0.01


async def test_chat_id_is_echoed():
    r = await post(make_app(), {"question": "q", "chat_id": "abc"})
    assert r.headers["x-chat-id"] == "abc"


@pytest.mark.parametrize("q", ["", "   ", "x" * 501])
async def test_bad_question_400(q):
    r = await post(make_app(), {"question": q})
    assert r.status_code == 400


async def test_rate_limited_429():
    app = make_app(rate_limit_per_hour=2)
    for _ in range(2):
        assert (await post(app, {"question": "q"})).status_code == 200
    r = await post(app, {"question": "q"})
    assert r.status_code == 429
    assert r.json()["retry_after_s"] > 0
    assert int(r.headers["retry-after"]) > 0


async def test_cap_reached_503():
    app = make_app(daily_cap_usd=0.015)
    assert (await post(app, {"question": "q"})).status_code == 200  # spends 0.01
    assert (await post(app, {"question": "q"})).status_code == 200  # spends 0.02 total
    r = await post(app, {"question": "q"})
    assert r.status_code == 503
    assert "paused" in r.json()["detail"]


async def test_xff_rightmost_used():
    app = make_app(rate_limit_per_hour=1)
    # Spoofed leftmost entries vary; the rightmost (added by Cloud Run) is the real client.
    ok = await post(app, {"question": "q"}, {"x-forwarded-for": "1.1.1.1, 7.7.7.7"})
    assert ok.status_code == 200
    r = await post(app, {"question": "q"}, {"x-forwarded-for": "2.2.2.2, 7.7.7.7"})
    assert r.status_code == 429
    other = await post(app, {"question": "q"}, {"x-forwarded-for": "7.7.7.7, 8.8.8.8"})
    assert other.status_code == 200


async def test_agent_crash_becomes_error_event():
    async def boom(question, on_cost):
        yield StepEvent("route", "route", "started", "Choosing a route")
        raise RuntimeError("bug")

    r = await post(make_app(boom), {"question": "q"})
    frames = parse_frames(r.text)
    assert frames[-1][0] == "error" and "try again" in frames[-1][1]["message"]
    assert "bug" not in r.text


async def test_meta_has_coverage_and_examples():
    transport = httpx.ASGITransport(app=make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        meta = (await c.get("/api/meta")).json()
        assert (await c.get("/healthz")).json() == {"ok": True}
    assert meta["coverage"] == {"seasons": [2025, 2026], "as_of_season": 2026, "as_of_week": 10}
    groups = [g["group"] for g in meta["examples"]]
    assert groups[0] == "STATS" and "EDGE CASES" in groups
    assert all(g["questions"] for g in meta["examples"])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_disconnect_cancels_and_charges():
    started, cancelled = threading.Event(), threading.Event()

    async def slow(question, on_cost):
        try:
            yield StepEvent("route", "route", "started", "Choosing a route")
            on_cost(0.02)  # a model call finished and was billed
            started.set()
            await asyncio.sleep(3600)  # the next model call, still running
            yield TokenEvent("never")
        finally:
            cancelled.set()

    app = make_app(slow)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        with (
            httpx.Client() as c,
            c.stream("POST", f"http://127.0.0.1:{port}/chat", json={"question": "q"}) as r,
        ):
            next(r.iter_lines())  # first frame arrives, then the visitor presses Stop
            assert started.wait(2)
        assert cancelled.wait(3), "agent kept running after the client went away"
        assert app.state.spend.spent == pytest.approx(0.02)
    finally:
        server.should_exit = True
        thread.join(5)


@pytest.mark.parametrize("chat_id", ["a\r\nSet-Cookie: x=1", "x" * 200, "has space"])
async def test_bad_chat_id_rejected(chat_id):
    r = await post(make_app(), {"question": "q", "chat_id": chat_id})
    assert r.status_code in (400, 422)
