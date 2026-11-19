# Lineup Lab

*Fantasy football answers backed by the numbers and what analysts said.*

Ask a question and an agent routes it, resolves player names, writes and runs SQL (with
retries), and streams back a cited answer. Every step is shown in an inspector, so you can
see how it got there: the route it chose, the SQL it ran, the result, and the cost.

**Status: proof of concept.** Only stats questions work so far (2025 and 2026 seasons, weekly
player stats from nflverse). Podcast search, follow-ups, and the eval results page are next.
See `docs/functional-spec.md` §10 for the build stages.

**Not deployed yet.** The Cloud Run deploy is on hold until the owner gives the go-ahead (see `docs/plans/2026-11-18-poc-stats-agent.md`, Task 10).

## How it works

```
question → route → resolve names → write SQL ⇄ run SQL (≤3 tries) → stream answer with [n] citations
              └── podcasts / out of scope / unknown name → honest decline
```

- **Agent:** a LangGraph graph whose nodes are plain functions calling the Anthropic SDK
  (Claude Opus 5.5), DuckDB, and a deterministic name resolver. No LangChain chains or agents.
- **Stats:** nflverse via `nflreadpy`, loaded into a read-only DuckDB file that ships in the
  image. Model-written SQL runs with external access disabled, configuration locked, a
  single-SELECT check, and a 10-second timeout.
- **Streaming:** `POST /chat` returns one Server-Sent Events stream of typed events: `step`,
  `token`, `source`, `done`, `error`.
- **Frontend:** React + TypeScript + Vite, served by the same FastAPI container.

The reasons behind each choice, and what was rejected, are in `docs/technical-spec.md`.

## Run it locally

Requires [uv](https://docs.astral.sh/uv/) and Node 22+.

```bash
# 1. Build the stats database (downloads nflverse data, ~1 min)
cd backend && uv sync && uv run python -m lineup_lab.ingest stats

# 2. API on :8000. Put ANTHROPIC_API_KEY in backend/.env (see .env.example)
uv run uvicorn lineup_lab.api.app:create_app --factory --env-file .env --reload

# 3. Frontend on :5173 (proxies /chat and /api to :8000)
cd ../frontend && npm install && npm run dev
```

**No API key? Use a local model (Apple silicon).** Any OpenAI-compatible server works; with
[mlx-lm](https://github.com/ml-explore/mlx-lm):

```bash
mlx_lm.server --model mlx-community/Qwen2.5-Coder-14B-Instruct-4bit --port 8090
# then start the API with:
LLM_PROVIDER=local LLM_MODEL=mlx-community/Qwen2.5-Coder-14B-Instruct-4bit \
  uv run uvicorn lineup_lab.api.app:create_app --factory --reload
```

Good for exercising the UI and agent paths at no cost; answer quality is well below Claude's,
so eval numbers come from Claude.

Tests: `cd backend && uv run pytest` and `cd frontend && npm test`.

## Evals

```bash
cd backend && uv run --env-file .env python -m evals.run_sql_eval
```

This runs `evals/sql_cases.yaml` through the real agent. It grades the SQL by execution match
against a reference query, checks the route taken, and records cost and latency. Results are
written to `evals/results/`. A full run costs about $1–2.

## Deploy (Google Cloud Run)

One container, `max-instances=1`. The proof of concept keeps its rate limit (20 questions per
hour per IP) and daily spending cap ($5) in memory. See `scripts/deploy.sh` for the
one-time setup and the deploy command.

```bash
docker build -t lineup-lab . && docker run -p 8080:8080 --env-file backend/.env lineup-lab
```
