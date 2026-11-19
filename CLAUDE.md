# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Lineup Lab is a portfolio project: a fantasy football agent that answers questions with
text-to-SQL over nflverse stats (and, from stage 2, RAG over podcast transcripts), showing its
routing, SQL, sources, and cost in the UI. The owner must be able to defend every design
decision in interviews, so **explain trade-offs, and don't hide logic inside framework
abstractions** (no LangChain chains/agents/retrievers; LangGraph only decides which node runs
next, and every node is our own code).

## Docs are the source of truth

- `docs/functional-spec.md`: what the app does. Wins on behavior.
- `docs/technical-spec.md`: how it's built. Wins on implementation. It's a living document:
  when you make a design decision, add it there as **what / why / rejected** (see §7).
- `docs/project-context.md`: the original brief; the two specs override it.
- `docs/plans/`: one implementation plan per milestone, with status at the top.

**The Cloud Run deploy is on hold until the owner says otherwise.** Don't run
`scripts/deploy.sh` or `gcloud run deploy` without a fresh go-ahead.

## Commands

Backend (run from `backend/`; uv manages Python 3.12 and the venv):

```bash
uv sync                                            # install (dev + ingest groups by default)
uv run pytest                                      # all tests (no network, no API key)
uv run pytest tests/agent/test_graph.py::test_sql_retry_then_success   # one test
uv run ruff check . && uv run ruff format .        # lint + format (line length 100)
uv run python -m lineup_lab.ingest stats           # rebuild data/stats.duckdb from nflverse
uv run uvicorn lineup_lab.api.app:create_app --factory --env-file .env --reload   # API on :8000
uv run --env-file .env python -m evals.run_sql_eval [--limit N] [--ids a,b]       # SQL eval
```

The eval spends real API money (~$1–2 per full run on Opus). Ask the owner before running it,
unless `LLM_PROVIDER=local`. There's no module-level `app`: always use `create_app --factory`.

Frontend (run from `frontend/`; Vite dev server proxies `/chat` and `/api` to :8000):

```bash
npm run dev          # :5173
npm test             # vitest
npm run build        # tsc -b + vite build
npx oxlint src       # lint
```

Container (repo root): `docker build -t lineup-lab .` then
`docker run -p 8080:8080 --env-file backend/.env lineup-lab`. Port 8081 is taken on the
owner's machine.

Local model instead of Claude (no cost; see README): run
`mlx_lm.server --model <mlx model> --port 8090`, then set `LLM_PROVIDER=local` and `LLM_MODEL`.

## Architecture

One request = one `POST /chat` returning a Server-Sent Events stream:

```
api/app.py ─► agent/graph.py run_agent() ─► LangGraph: route → resolve → gen_sql ⇄ run_sql → answer
                                                        └──────────── decline (any other path)
```

- **Nodes** (`agent/nodes.py`) emit events through LangGraph's `get_stream_writer()`.
  `run_agent` streams with `stream_mode=["custom", "values"]`, forwards the custom events, and
  ends with a `DoneEvent` built from the final state's `calls`.
- **The SQL retry is a graph edge**, not a model tool loop: `run_sql → gen_sql` on error, up to
  `sql_max_attempts` (3). Each attempt is a `sql-N` step in the trace.
- **The SSE contract** lives in `agent/events.py` and is mirrored by hand in
  `frontend/src/api/types.ts`. Change both together. `chat_id` travels in the `X-Chat-Id`
  header, not in an event.
- **Prompts and structured-output schemas** (`RouteDecision`, `SqlDraft`) are all in
  `agent/prompts.py`. System prompts hold only stable text (rules, generated schema, as-of week)
  so they can be prompt-cached; per-question content goes in the user message.
- **"Now" means the data's as-of week** (`meta` table), never today's date.

Module boundaries (keep them):
- `stats/` is the only code that touches DuckDB. `StatsDB` treats model-written SQL as untrusted:
  read-only connection, `enable_external_access=false`, locked config, 256MB memory cap,
  DuckDB's parser must see exactly one SELECT, 10s interrupt timer, long cells clipped.
- `llm/` is the only code that talks to a model. `make_llm(settings)` returns `LLM` (Anthropic
  SDK) or `LocalLLM` (OpenAI-compatible HTTP); both expose `parse()` and `stream_text()` and
  report `CallStats` (tokens, cost, time) through an `on_call` hook. The API wires that hook to
  the daily `SpendTracker`, so cancelled requests still count.
- `players/` resolves names deterministically (alias file → exact → first/last → fuzzy; "assume"
  when the top candidate has ≥3× the runner-up's PPR points). The LLM never picks player ids.
- `ingest/` (the refresh job) is the only code that imports `nflreadpy`/`polars`. Those are in
  the optional `ingest` group and aren't in the Docker image.
- `search/` (Qdrant) arrives in stage 2 and will be the only code that talks to Qdrant.

Claude API notes (model `claude-opus-5-5`): thinking can't be disabled, so depth is tuned only
with `output_config.effort` (per step in `config.py`). `temperature`, `budget_tokens`,
assistant prefill, and forced `tool_choice` are all rejected with a 400. Prices for cost
tracking are in `llm/pricing.py`.

Rate limit (20/hour per IP) and the daily $ cap live in memory (`api/limits.py`). That's only
correct because the PoC runs as one Cloud Run instance; revisit before scaling. The client IP is
the rightmost `X-Forwarded-For` entry.

## Testing conventions

- Backend tests never hit the network. `tests/conftest.py` provides `stats_db` (a tiny DuckDB
  built from hand-made frames in `tests/factories.py`), and `tests/fakes.py` provides `FakeLLM`
  (scripted parse results and streamed texts) for agent, API, and eval tests.
- `test_disconnect_cancels_and_charges` runs a real uvicorn server in a thread, because httpx's
  `ASGITransport` buffers responses and can't show a client disconnect.
- SQL evals (`backend/evals/sql_cases.yaml`) are graded by execution match against a
  `reference_sql`, so cases survive data refreshes. Results are committed to `evals/results/`.

## Data

`data/` is gitignored: `stats.duckdb` (regenerable, and baked into the Docker image; `.gcloudignore`
re-includes it), plus future audio and transcripts (copyrighted; never commit them).
