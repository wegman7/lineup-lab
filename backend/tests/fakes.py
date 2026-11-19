"""Scripted stand-in for lineup_lab.llm.client.LLM: same methods, no network."""

from collections.abc import Callable

from pydantic import BaseModel

from lineup_lab.llm.client import CallStats


class FakeLLM:
    model = "fake-model"

    def __init__(
        self,
        parses: list = (),
        texts: list[str] = (),
        cost: float = 0.01,
        on_call: Callable[[CallStats], None] | None = None,
    ):
        self.parses = list(parses)  # BaseModel instances, or Exceptions to raise
        self.texts = list(texts)
        self.cost = cost
        self.on_call = on_call
        self.calls: list[dict] = []

    def _stats(self) -> CallStats:
        s = CallStats(
            self.model, input_tokens=100, output_tokens=10, cost_usd=self.cost, duration_ms=1
        )
        if self.on_call:
            self.on_call(s)
        return s

    async def parse(self, system, messages, schema: type[BaseModel], effort):
        self.calls.append(dict(kind="parse", system=system, messages=messages, schema=schema))
        item = self.parses.pop(0)
        stats = self._stats()
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, schema), f"scripted {type(item).__name__}, asked {schema.__name__}"
        return item, stats

    async def stream_text(self, system, messages, effort, on_text):
        self.calls.append(dict(kind="stream", system=system, messages=messages))
        text = self.texts.pop(0)
        for word in text.split(" "):
            on_text(word + " ")
        return text, self._stats()
