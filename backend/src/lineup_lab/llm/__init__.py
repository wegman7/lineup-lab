"""Model access. `make_llm` picks the provider from settings; both classes have the same
`parse()` and `stream_text()` methods."""

from collections.abc import Callable

from lineup_lab.config import Settings
from lineup_lab.llm.client import LLM, CallStats
from lineup_lab.llm.local import LocalLLM


def make_client(settings: Settings):
    """One long-lived HTTP client per process; per-request LLM objects share it."""
    if settings.llm_provider == "anthropic":
        import anthropic

        return anthropic.AsyncAnthropic()
    if settings.llm_provider == "local":
        import httpx

        return httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0))
    raise ValueError(f"unknown LLM_PROVIDER {settings.llm_provider!r} (use anthropic or local)")


def make_llm(
    settings: Settings, on_call: Callable[[CallStats], None] | None = None, client=None
) -> LLM | LocalLLM:
    client = client if client is not None else make_client(settings)
    if settings.llm_provider == "anthropic":
        return LLM(client, settings.model, on_call=on_call)
    if settings.llm_provider == "local":
        return LocalLLM(settings.local_llm_base_url, settings.model, on_call, http_client=client)
    raise ValueError(f"unknown LLM_PROVIDER {settings.llm_provider!r} (use anthropic or local)")
