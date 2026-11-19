"""A local model for development, so testing the app doesn't spend API tokens.

Talks the OpenAI-compatible protocol (POST /chat/completions), which mlx_lm.server, LM Studio,
Ollama, and llama.cpp all serve. Same two methods as llm.client.LLM, so the agent can't tell
the difference.

mlx_lm.server ignores `response_format`, so structured output can't be forced there. We send
the schema anyway (LM Studio does enforce it), repeat it in the system prompt, validate the
reply with Pydantic, and retry once with the validation error if it doesn't fit.
Not for quality numbers: evals run on the real model.
"""

import json
import re
import time
from collections.abc import Callable

import httpx
from pydantic import BaseModel, ValidationError

from lineup_lab.llm.client import CallStats, LLMError

THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def extract_json(text: str) -> str:
    """Pull the JSON object out of a reply that may include think tags or code fences."""
    text = THINK.sub("", text)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text.strip()


class LocalLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        on_call: Callable[[CallStats], None] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._on_call = on_call
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0))

    def _stats(self, prompt_tokens: int, completion_tokens: int, start: float) -> CallStats:
        stats = CallStats(
            model=self.model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            cost_usd=0.0,
            duration_ms=round((time.perf_counter() - start) * 1000),
        )
        if self._on_call:
            self._on_call(stats)
        return stats

    async def _complete(self, body: dict) -> dict:
        try:
            r = await self._http.post(self._url, json=body)
        except httpx.HTTPError as e:
            raise LLMError(f"local model server unreachable at {self._url}: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"local model server returned {r.status_code}: {r.text[:200]}")
        return r.json()

    async def parse[T: BaseModel](
        self, system: str, messages: list[dict], schema: type[T], effort: str
    ) -> tuple[T, CallStats]:
        # `effort` is a Claude setting; local models have no equivalent, so it's ignored.
        start = time.perf_counter()
        json_schema = schema.model_json_schema()
        system = (
            f"{system}\n\nRespond with only a JSON object (no prose, no code fences) matching "
            f"this JSON schema:\n{json.dumps(json_schema)}"
        )
        convo = [{"role": "system", "content": system}, *messages]
        prompt_tokens = completion_tokens = 0
        error = None
        for _attempt in range(2):
            data = await self._complete({
                "model": self.model,
                "messages": convo,
                "temperature": 0,
                "max_tokens": 2048,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__, "schema": json_schema, "strict": True},
                },
            })  # fmt: skip
            usage = data.get("usage") or {}
            prompt_tokens += usage.get("prompt_tokens", 0)
            completion_tokens += usage.get("completion_tokens", 0)
            raw = data["choices"][0]["message"].get("content") or ""
            try:
                parsed = schema.model_validate_json(extract_json(raw))
            except ValidationError as e:
                error = e
                convo = [*convo, {"role": "assistant", "content": raw}, {
                    "role": "user",
                    "content": f"That reply didn't match the schema:\n{e}\n"
                               "Reply with only the corrected JSON object.",
                }]  # fmt: skip
                continue
            return parsed, self._stats(prompt_tokens, completion_tokens, start)
        self._stats(prompt_tokens, completion_tokens, start)
        raise LLMError(f"local model didn't return valid {schema.__name__} JSON: {error}")

    async def stream_text(
        self, system: str, messages: list[dict], effort: str, on_text: Callable[[str], None]
    ) -> tuple[str, CallStats]:
        start = time.perf_counter()
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0,
            "max_tokens": 2048,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        parts: list[str] = []
        usage: dict = {}
        try:
            async with self._http.stream("POST", self._url, json=body) as r:
                if r.status_code >= 400:
                    raise LLMError(f"local model server returned {r.status_code}")
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[len("data: ") :]
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    usage = chunk.get("usage") or usage
                    for choice in chunk.get("choices") or []:
                        text = (choice.get("delta") or {}).get("content")
                        if text:
                            parts.append(text)
                            on_text(text)
        except httpx.HTTPError as e:
            raise LLMError(f"local model server unreachable at {self._url}: {e}") from e
        stats = self._stats(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), start)
        return "".join(parts), stats
