"""The only module that talks to the Anthropic SDK. Every call reports tokens, cost, and time.

Notes for claude-opus-5-5: thinking is always on and can't be disabled, so depth is tuned with
`output_config.effort`. No temperature, no prefill, no forced tool_choice (all rejected).
"""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

from pydantic import BaseModel

from lineup_lab.llm.pricing import cost_usd


class LLMError(Exception):
    pass


@dataclass
class CallStats:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int


class LLM:
    def __init__(self, client, model: str, on_call: Callable[[CallStats], None] | None = None):
        self._client = client
        self.model = model
        self._on_call = on_call

    def _system(self, system: str) -> list[dict]:
        # Cache breakpoint on the (stable) system prompt: schema + rules.
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    def _stats(self, usage, start: float) -> CallStats:
        stats = CallStats(
            model=self.model,
            input_tokens=(usage.input_tokens or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0),
            output_tokens=usage.output_tokens or 0,
            cost_usd=cost_usd(self.model, usage),
            duration_ms=round((time.perf_counter() - start) * 1000),
        )
        if self._on_call:
            self._on_call(stats)
        return stats

    async def parse[T: BaseModel](
        self, system: str, messages: list[dict], schema: type[T], effort: str
    ) -> tuple[T, CallStats]:
        start = time.perf_counter()
        resp = await self._client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=self._system(system),
            messages=messages,
            output_format=schema,
            output_config={"effort": effort},
        )
        stats = self._stats(resp.usage, start)
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            raise LLMError("model declined or returned no output")
        return resp.parsed_output, stats

    async def stream_text(
        self, system: str, messages: list[dict], effort: str, on_text: Callable[[str], None]
    ) -> tuple[str, CallStats]:
        start = time.perf_counter()
        parts: list[str] = []
        async with self._client.messages.stream(
            model=self.model,
            max_tokens=8000,
            system=self._system(system),
            messages=messages,
            output_config={"effort": effort},
        ) as stream:
            try:
                async for text in stream.text_stream:
                    parts.append(text)
                    on_text(text)
            except BaseException:
                # Cancelled (Stop button, closed tab) or failed mid-stream: the tokens so far
                # are still billed, so report an estimate rather than nothing.
                self._report_partial(stream, parts, start)
                raise
            final = await stream.get_final_message()
        if final.stop_reason == "refusal":
            self._stats(final.usage, start)
            raise LLMError("model declined")
        return "".join(parts), self._stats(final.usage, start)

    def _report_partial(self, stream, parts: list[str], start: float) -> None:
        try:
            snap = stream.current_message_snapshot.usage
        except Exception:
            return  # no message_start yet: nothing billed that we can see
        estimated_out = math.ceil(len("".join(parts)) / 4)
        self._stats(
            SimpleNamespace(
                input_tokens=snap.input_tokens,
                output_tokens=estimated_out,
                cache_creation_input_tokens=getattr(snap, "cache_creation_input_tokens", 0),
                cache_read_input_tokens=getattr(snap, "cache_read_input_tokens", 0),
            ),
            start,
        )
