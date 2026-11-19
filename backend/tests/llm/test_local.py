import json

import httpx
import pytest
from pydantic import BaseModel

from lineup_lab.llm.client import LLMError
from lineup_lab.llm.local import LocalLLM


class Route(BaseModel):
    route: str
    n: int


def completion(content: str, prompt_tokens=50, completion_tokens=5) -> dict:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def llm_with(handler, **kw) -> tuple[LocalLLM, list[dict]]:
    requests = []

    def record(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"url": str(request.url), **body})
        return handler(body, len(requests))

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return LocalLLM("http://local:8090/v1", "qwen-test", http_client=client, **kw), requests


async def test_parse_sends_schema_and_validates():
    llm, reqs = llm_with(
        lambda b, i: httpx.Response(200, json=completion('{"route":"stats","n":2}'))
    )
    out, stats = await llm.parse("sys", [{"role": "user", "content": "q"}], Route, effort="low")
    assert out == Route(route="stats", n=2)
    assert stats.cost_usd == 0 and stats.input_tokens == 50 and stats.output_tokens == 5
    r = reqs[0]
    assert r["url"] == "http://local:8090/v1/chat/completions"
    assert r["model"] == "qwen-test"
    assert r["response_format"]["type"] == "json_schema"
    assert r["response_format"]["json_schema"]["schema"]["properties"]["n"]["type"] == "integer"
    assert r["messages"][0]["role"] == "system" and '"route"' in r["messages"][0]["content"]
    assert r["messages"][1] == {"role": "user", "content": "q"}


async def test_parse_strips_code_fences_and_think_tags():
    text = '<think>hmm</think>\n```json\n{"route": "stats", "n": 1}\n```'
    llm, _ = llm_with(lambda b, i: httpx.Response(200, json=completion(text)))
    out, _ = await llm.parse("s", [], Route, effort="low")
    assert out.n == 1


async def test_parse_retries_once_on_invalid_json():
    replies = ['{"route": "stats"}', '{"route": "stats", "n": 3}']
    llm, reqs = llm_with(lambda b, i: httpx.Response(200, json=completion(replies[i - 1])))
    out, stats = await llm.parse("s", [{"role": "user", "content": "q"}], Route, effort="low")
    assert out.n == 3
    retry_msgs = reqs[1]["messages"]
    assert retry_msgs[-2] == {"role": "assistant", "content": '{"route": "stats"}'}
    assert "n" in retry_msgs[-1]["content"]  # the validation error is fed back
    assert stats.input_tokens == 100  # both attempts counted


async def test_parse_gives_up_after_second_failure():
    llm, _ = llm_with(lambda b, i: httpx.Response(200, json=completion("not json")))
    with pytest.raises(LLMError):
        await llm.parse("s", [], Route, effort="low")


async def test_server_error_raises_llm_error():
    llm, _ = llm_with(lambda b, i: httpx.Response(500, text="boom"))
    with pytest.raises(LLMError):
        await llm.parse("s", [], Route, effort="low")


async def test_stream_text_reads_sse_deltas_and_usage():
    def sse(body, i):
        assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
        chunks = [
            {"choices": [{"delta": {"role": "assistant", "content": ""}}]},
            {"choices": [{"delta": {"content": "Lean "}}]},
            {"choices": [{"delta": {"content": "Nacua [1]."}}]},
            {"choices": [], "usage": {"prompt_tokens": 70, "completion_tokens": 4}},
        ]
        lines = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=lines, headers={"content-type": "text/event-stream"})

    seen, calls = [], []
    llm, _ = llm_with(sse, on_call=calls.append)
    text, stats = await llm.stream_text("s", [{"role": "user", "content": "q"}], "low", seen.append)
    assert seen == ["Lean ", "Nacua [1]."]
    assert text == "Lean Nacua [1]."
    assert stats.input_tokens == 70 and stats.output_tokens == 4 and stats.cost_usd == 0
    assert calls == [stats]


def test_make_llm_picks_provider(monkeypatch):
    from dataclasses import replace

    from lineup_lab.config import get_settings
    from lineup_lab.llm import make_llm
    from lineup_lab.llm.client import LLM

    s = get_settings()
    assert isinstance(make_llm(replace(s, llm_provider="anthropic"), client=object()), LLM)
    local = make_llm(replace(s, llm_provider="local", model="m"))
    assert isinstance(local, LocalLLM) and local.model == "m"
    with pytest.raises(ValueError):
        make_llm(replace(s, llm_provider="nope"))
