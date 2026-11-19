from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from lineup_lab.llm.client import LLM, LLMError


class Answer(BaseModel):
    x: int


def _usage(i=100, o=10):
    return SimpleNamespace(
        input_tokens=i, output_tokens=o, cache_creation_input_tokens=0, cache_read_input_tokens=0
    )


class StubStream:
    def __init__(self, chunks, snapshot_usage=None):
        self._chunks = chunks
        self._snapshot_usage = snapshot_usage

    async def __aenter__(self):
        async def gen():
            for c in self._chunks:
                yield c

        self.text_stream = gen()
        return self

    async def __aexit__(self, *a):
        return False

    @property
    def current_message_snapshot(self):
        return SimpleNamespace(usage=self._snapshot_usage)

    async def get_final_message(self):
        return SimpleNamespace(stop_reason="end_turn", usage=_usage(200, 20))


class StubMessages:
    def __init__(self, parse_result=None, chunks=()):
        self.parse_result, self.chunks, self.calls = parse_result, chunks, []
        self.snapshot_usage = None

    async def parse(self, **kw):
        self.calls.append(kw)
        return self.parse_result

    def stream(self, **kw):
        self.calls.append(kw)
        return StubStream(self.chunks, self.snapshot_usage)


def stub_client(**kw):
    return SimpleNamespace(messages=StubMessages(**kw))


async def test_parse_returns_model_and_stats():
    client = stub_client(
        parse_result=SimpleNamespace(
            stop_reason="end_turn", parsed_output=Answer(x=3), usage=_usage()
        )
    )
    out, stats = await LLM(client, "claude-opus-5-5").parse(
        "sys", [{"role": "user", "content": "q"}], Answer, effort="low"
    )
    assert out.x == 3
    assert stats.input_tokens == 100 and stats.output_tokens == 10
    assert stats.cost_usd == pytest.approx(100 * 4e-6 + 10 * 20e-6)
    call = client.messages.calls[0]
    assert call["output_format"] is Answer
    assert call["output_config"] == {"effort": "low"}
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in call and "thinking" not in call


async def test_parse_raises_on_refusal():
    client = stub_client(
        parse_result=SimpleNamespace(stop_reason="refusal", parsed_output=None, usage=_usage())
    )
    with pytest.raises(LLMError):
        await LLM(client, "claude-opus-5-5").parse("s", [], Answer, effort="low")


async def test_stream_text_calls_on_text():
    client = stub_client(chunks=["Lean ", "Nacua [1]."])
    seen = []
    text, stats = await LLM(client, "claude-opus-5-5").stream_text(
        "s", [{"role": "user", "content": "q"}], effort="low", on_text=seen.append
    )
    assert seen == ["Lean ", "Nacua [1]."]
    assert text == "Lean Nacua [1]."
    assert stats.output_tokens == 20


async def test_on_call_hook_gets_every_call():
    seen = []
    client = stub_client(
        parse_result=SimpleNamespace(
            stop_reason="end_turn", parsed_output=Answer(x=1), usage=_usage()
        ),
        chunks=["a"],
    )
    llm = LLM(client, "claude-opus-5-5", on_call=seen.append)
    await llm.parse("s", [], Answer, effort="low")
    await llm.stream_text("s", [], effort="low", on_text=lambda t: None)
    assert [s.input_tokens for s in seen] == [100, 200]


async def test_cancelled_stream_still_reports_estimated_cost():
    import asyncio

    seen = []
    client = stub_client(chunks=["x" * 400, "never"])
    client.messages.snapshot_usage = _usage(i=1000, o=0)

    def stop(_t):
        raise asyncio.CancelledError

    llm = LLM(client, "claude-opus-5-5", on_call=seen.append)
    with pytest.raises(asyncio.CancelledError):
        await llm.stream_text("s", [], effort="low", on_text=stop)
    assert seen[0].input_tokens == 1000
    assert seen[0].output_tokens == 100  # ~4 chars per token for text received
