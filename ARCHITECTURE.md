# Architecture

A map of the code as it is now. It answers "where does this live, and why there?" The reasons
behind each design choice, and what was rejected, are in `docs/technical-spec.md`.

## Bird's-eye view

A user asks a fantasy football question. One `POST /chat` request runs an agent that decides
what kind of question it is, matches player names, writes SQL against a local stats database
(retrying if the SQL fails), and streams back an answer with citations. Every step is sent to
the browser as it happens, so the UI can show the route, the SQL, the result, and the cost.

```
browser ──POST /chat──► api/ ──► agent/ run_agent()
                                   │
                                   ▼  (LangGraph decides which step runs next)
              route ─► resolve ─► gen_sql ⇄ run_sql ─► answer
                │         │                   │
                └─────────┴───────────────────┴──► decline   (any other path)
                                   │
browser ◄──── Server-Sent Events: step · token · source · done · error
```

## Code map

All backend code is in `backend/src/lineup_lab/`. Imports only go one way:

```
api ──► agent ──► llm       talks to a model, knows nothing about football
          ├─────► stats     talks to DuckDB
          └─────► players ─► stats

ingest   separate: builds the DuckDB file that stats/ reads
config   imported by anyone; reads every environment variable in one place
```

The quickest way to place new code: **would it still make sense in a project that isn't about
football?** If yes, it probably belongs in `llm/` or `stats/`. If no, it belongs in `agent/`.

### `api/`: the web layer

`app.py` builds the FastAPI app (`create_app`, always run with `--factory`). It validates the
question, applies the per-IP rate limit and the daily spending cap (`limits.py`), runs the
agent as a background task, and writes its events to the response as Server-Sent Events
(`sse.py`). If the browser disconnects, the task is cancelled and its cost still counts. It
also serves `/api/meta` (data coverage and example questions), `/healthz`, and, in the
container, the built frontend.

It contains no agent logic. It only knows that the agent is something that takes a question
and yields events.

### `agent/`: the application logic

This is where the football lives.

- `graph.py` wires the steps into a LangGraph graph and decides which runs next. The SQL retry
  is a graph edge (`run_sql → gen_sql`, up to 3 attempts), not a loop inside the model.
  `run_agent()` runs the graph and yields events, ending with a `DoneEvent` that totals cost
  and tokens.
- `nodes.py` holds the steps themselves: `route`, `resolve`, `gen_sql`, `run_sql`, `answer`,
  `decline`. Each is a plain async function that calls `llm/`, `stats/`, or `players/` and
  emits events.
- `prompts.py` holds every prompt and the schemas the model must answer in (`RouteDecision`,
  `SqlDraft`). System prompts hold only stable text so they can be prompt-cached; the
  question itself goes in the user message.
- `state.py` is what the graph carries between steps.
- `events.py` is the event contract the browser reads. `frontend/src/api/types.ts` mirrors it
  by hand, so change both together.

### `llm/`: talking to a model

Plumbing only. Two clients with the same two methods:

- `client.py`: `LLM`, Claude through the Anthropic SDK.
- `local.py`: `LocalLLM`, any OpenAI-compatible server (used with `mlx_lm.server` for free
  local runs).
- `parse()` returns a validated object matching a schema. `stream_text()` streams the answer
  token by token.
- Every call reports a `CallStats` (tokens, cost, time) through an `on_call` hook. The API
  wires that hook to the spending cap. `pricing.py` turns tokens into dollars.
- `make_llm(settings)` picks the client from `LLM_PROVIDER`.

Swapping Claude for a local model touched only this package.

### `stats/`: the stats database

The only code that touches DuckDB. `db.py`'s `StatsDB` runs SQL the model wrote, so it treats
that SQL as untrusted: read-only connection, no file or network access, locked settings, a
256MB memory cap, exactly one `SELECT`, a 10-second timeout, and long cells clipped. It also
reports the data's "as of" week, which is what "this week" means everywhere (never today's
date). `schema.py` turns the database's tables and column comments into the schema text the
SQL prompt includes.

### `players/`: name matching

Turns "CMC" or "Puka" into a player id, deterministically: alias file (`aliases.yaml`), then
exact name, then first or last name, then fuzzy match. If one candidate scored at least 3× the
next one's fantasy points, it assumes that player and says so; otherwise it asks. The model
never picks player ids.

### `ingest/`: the refresh job

`python -m lineup_lab.ingest stats` downloads nflverse data and builds `data/stats.duckdb`
(written to a temp file, then swapped in). It's the only code that imports `nflreadpy` and
`polars`, which are in an optional dependency group and aren't in the Docker image.

### Not built yet

`search/` (podcast transcripts in Qdrant) arrives in stage 2. It will be the only code that
talks to Qdrant, the same rule `stats/` follows for DuckDB.

## Frontend

`frontend/src/` is React + TypeScript + Vite.

- `api/` talks to the backend: `chat.ts` sends the question, `sse.ts` parses the event stream,
  and `types.ts` mirrors `agent/events.py`.
- `chatReducer.ts` holds all conversation state. Each incoming event becomes a reducer action,
  so it's testable without a browser.
- `components/` renders it: `Landing`, `Conversation`, `Inspector` (the step trace, with
  `StepList` and `StatCard`), and `QuestionInput`.

In development, Vite serves the frontend on :5173 and proxies `/chat` and `/api` to the API on
:8000. In the container, FastAPI serves the built files itself.

## Evals and tests

- `backend/evals/` runs `sql_cases.yaml` through the real agent and grades SQL by comparing its
  result to a reference query's result, so cases survive data refreshes. Results are committed
  to `evals/results/`, one file per date and model.
- `backend/tests/` never touches the network. It uses a tiny hand-built DuckDB
  (`factories.py`) and a scripted fake model (`fakes.py`).

## Where to start reading

1. `agent/graph.py`: the whole flow on one screen.
2. `agent/nodes.py`: what each step does.
3. `agent/prompts.py`: what the model is actually told.
4. `api/app.py`: how a request becomes a stream.
