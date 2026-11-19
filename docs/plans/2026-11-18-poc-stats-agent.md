# Proof of Concept: Stats Agent, Deployed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status (2026-11-18):** Tasks 1–9 done, plus Task 10 Steps 1 and 3. **Deploy (Task 10 Step 2) is on hold at the owner's request.** Live smoke test (Task 7 Step 5) and the baseline eval run (Task 8 Step 5) are waiting on an API key.

**Goal:** A thin, public, end-to-end Lineup Lab: ask a stats question, watch the agent route → resolve names → write SQL (with retries) → stream a cited answer, with the SQL visible in an inspector.

**Architecture:** One Python package (`backend/src/lineup_lab`) holds a stats builder (nflreadpy → DuckDB), a read-only SQL runner, a player-name resolver, a thin Anthropic wrapper that counts cost, and a LangGraph graph whose nodes are our own functions. FastAPI exposes `POST /chat` as one SSE stream and serves the built React app from the same container, deployed to Cloud Run with `max-instances=1`.

**Tech Stack:** Python 3.12, uv, ruff, pytest · nflreadpy, DuckDB, LangGraph, `anthropic` SDK (Claude Opus 5.5), FastAPI · React + TypeScript + Vite, Vitest · Docker, Google Cloud Run.

**Spec:** `docs/functional-spec.md` (behavior), `docs/technical-spec.md` (how). This plan is the proof-of-concept milestone in functional spec §10.

## Decisions this plan makes (recorded in technical-spec §6–§7 by Task 1)

| Open decision (tech spec §6) | Decision | Rejected |
|---|---|---|
| LLM provider | **Claude Opus 5.5** (`claude-opus-5-5`) for every call; model is one setting. *(owner decision)* | Haiku router + Opus split: deferred to an eval experiment once a baseline exists. |
| Python tooling | **uv** (env + lockfile), **ruff** (lint + format), **pytest** | Poetry (slower, no Python version management), black + flake8 (ruff replaces both). |
| Graph skeleton | `route → (stats: resolve → gen_sql ⇄ run_sql → answer) / (other: decline)`. SQL retry is a **graph edge**, not a model tool loop. | Model-driven `run_sql` tool loop: the retry count and each attempt would live inside the model's loop, harder to cap, trace, and measure. Revisit if questions need several queries. |
| Stats tables + schema prompt | Four curated tables (`players`, `weekly_stats`, `snap_counts`, `games`) + `meta`. Schema prompt is **generated from DuckDB** (`information_schema` + `COMMENT ON COLUMN`) so it can't drift from the data. | Raw 150-column nflverse table (wastes tokens, confuses the model); hand-written schema text (drifts). |
| Name matching | Deterministic: alias file → exact → last/first name → `difflib` fuzzy; tie-break by PPR points in loaded data; "assume" when the top candidate has ≥3× the next one's points. | LLM-only resolution (not testable, not explainable); embedding match (overkill for ~2k names). |
| SSE payloads | Defined below in Task 7. `chat_id` returned as the `X-Chat-Id` response header. | A separate `start` event (not in the functional spec's event list). |
| SQL eval format | YAML cases with a **reference SQL**; graded by execution match (see Task 8). | Hard-coded expected numbers (go stale on every data refresh). |
| §4.2 shared state (PoC only) | Cloud Run `max-instances=1`, so in-memory per-IP limit and daily $ cap are correct. *(owner decision)* Real store decided before stage 3. | Firestore now (premature). |
| §4.3 routing | **One container**: FastAPI serves the Vite build. Same origin, no CORS. | Two Cloud Run services + CORS. `frontend/Dockerfile` from §1 is dropped; one root `Dockerfile` builds both. |

**Deferred to the next stage-1 plan:** `clarify` event + "Did you mean…?" buttons (PoC answers ambiguity in plain text), follow-ups/memory (use case 10), question logging (§7a), recorded replays, the Eval results and How it works pages.

## Global Constraints

- Model: `claude-opus-5-5`. Thinking can't be disabled on it; tune with `output_config={"effort": ...}` only. No `temperature`, no `budget_tokens`, no assistant prefill, no forced `tool_choice` (all 400).
- Pricing for cost tracking (per 1M tokens): input $4.00, output $20.00, cache write 1.25× input, cache read $0.20.
- Stats: seasons **2025 and 2026**, from `nflreadpy`. `stats.duckdb` opened **read-only**, and only `stats/` touches DuckDB. Only `llm/` touches the Anthropic SDK.
- Every config value comes from environment variables read in `config.py` (`STATS_DB_PATH`, `ANTHROPIC_API_KEY`, …). Never hard-coded.
- Input limit **500 characters**. Per-visitor limit **20 questions/hour**, keyed by IP, held in memory only. Daily cap **$5.00** (configurable).
- "Now" = the data's as-of week, never today's date. Answers state the week range used.
- Every factual claim in an answer cites a source `[n]`. Leans, not guarantees. If a step fails, say what couldn't be retrieved.
- No "NFL" or team names in the project title.

## Review Focus

1. **Model-written SQL that reaches outside the database** (`read_csv('/etc/passwd')`, `COPY … TO`, `ATTACH`, `SET`, `INSTALL httpfs`): must be rejected with an error the model can read, never executed. → Task 3 test `test_rejects_escape_attempts`.
2. **A query that returns a huge result** (`SELECT * FROM weekly_stats`): truncated to `max_rows` with a true total count. No giant SSE frame and no memory blowup. → Task 3 test `test_truncates_large_results`.
3. **SQL that fails every attempt** (3 tries): the answer says the stat couldn't be retrieved and contains no numbers. The trace shows all three failures. → Task 6 test `test_sql_gives_up_after_three_attempts`.
4. **A name not in the data, or ambiguous** ("Kupp", "Smith"): no invented player. Either the assumption is stated or the agent asks which player. → Task 4 tests `test_unknown_name`, `test_ambiguous_without_dominant`; Task 6 `test_ambiguous_name_asks`.
5. **Visitor presses Stop / closes the tab mid-answer:** server-side LLM work stops, and the cost so far still counts toward the daily cap. → Task 7 test `test_disconnect_cancels_and_charges`.

---

### Task 1: Backend scaffold, config, and recorded decisions

**Files:**
- Create: `backend/pyproject.toml`, `backend/src/lineup_lab/__init__.py`, `backend/src/lineup_lab/config.py`, `backend/tests/test_config.py`, `backend/.env.example`
- Modify: `docs/technical-spec.md` (§1 layout: root `Dockerfile`, no `frontend/Dockerfile`, no `docker-compose.yml` until Qdrant arrives; §6: mark PoC rows decided; add **§7 Proof-of-concept decisions** with the table above, what/why/rejected), `.gitignore` (`data/`, `frontend/node_modules`)

**Interfaces:**
- Produces: `Settings` (frozen dataclass) with fields `stats_db_path: Path` (env `STATS_DB_PATH`, default `<repo>/data/stats.duckdb`), `model: str` (`LLM_MODEL`, default `claude-opus-5-5`), `effort_route: str` (`"low"`), `effort_sql: str` (`"medium"`), `effort_answer: str` (`"low"`), `daily_cap_usd: float` (`DAILY_CAP_USD`, 5.0), `rate_limit_per_hour: int` (`RATE_LIMIT_PER_HOUR`, 20), `max_question_chars: int` (500), `sql_max_attempts: int` (3), `sql_max_rows: int` (50), `static_dir: Path | None` (`STATIC_DIR`, default None); `get_settings() -> Settings` (cached; `get_settings.cache_clear()` in tests).
- `pyproject.toml`: package `lineup-lab`, `requires-python = ">=3.12"`, src layout, deps `anthropic`, `langgraph`, `duckdb`, `fastapi`, `uvicorn[standard]`, `pydantic`, `pyyaml`; optional group `ingest = ["nflreadpy", "polars", "pyarrow"]`; dev group `pytest`, `pytest-asyncio`, `httpx`, `ruff`. `asyncio_mode = "auto"`.

- [ ] **Step 1:** Write `test_config.py`: `test_defaults` (no env → model `claude-opus-5-5`, cap 5.0, limit 20, 500 chars, 3 attempts) and `test_env_overrides` (monkeypatch `DAILY_CAP_USD=2.5`, `LLM_MODEL=x` → reflected).
- [ ] **Step 2:** `cd backend && uv sync --all-groups && uv run pytest tests/test_config.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `config.py`.
- [ ] **Step 4:** Run tests (PASS) and `uv run ruff check . && uv run ruff format --check .` (clean).
- [ ] **Step 5:** Update `docs/technical-spec.md` as listed above.

### Task 2: Stats builder (nflreadpy → DuckDB)

**Files:**
- Create: `backend/src/lineup_lab/ingest/__init__.py`, `backend/src/lineup_lab/ingest/__main__.py`, `backend/src/lineup_lab/ingest/stats.py`, `backend/tests/ingest/test_stats_build.py`, `backend/tests/conftest.py`

**Interfaces:**
- Produces:
  - `SEASONS = [2025, 2026]`
  - `fetch_frames(seasons: list[int]) -> RawFrames` (the only nflreadpy caller; `RawFrames` is a dataclass of polars frames `player_stats`, `players`, `snap_counts`, `schedules`)
  - `build_stats_db(frames: RawFrames, out_path: Path) -> BuildReport` writes the DB **atomically** (build to `out_path.with_suffix(".tmp")`, then rename). `BuildReport(as_of_season: int, as_of_week: int, row_counts: dict[str, int])`.
  - CLI: `uv run --group ingest python -m lineup_lab.ingest stats` prints the report.
  - `tests/conftest.py` fixture `stats_db(tmp_path) -> Path`: builds a DB from a tiny hand-made `RawFrames` (3 players incl. two named "Smith", 2 seasons, a few weeks). Every later backend test uses this fixture, never the network.
- Tables (only these columns; add `COMMENT ON COLUMN` for each non-obvious one):
  - `players(player_id, name, position, team, ppr_points)`: players with ≥1 `weekly_stats` row; `ppr_points` = sum of `fantasy_points_ppr` over loaded data.
  - `weekly_stats(player_id, player_name, position, team, opponent, season, week, season_type, game_id, completions, attempts, passing_yards, passing_tds, passing_interceptions, sacks_suffered, passing_air_yards, passing_epa, carries, rushing_yards, rushing_tds, rushing_first_downs, rushing_fumbles_lost, rushing_epa, targets, receptions, receiving_yards, receiving_tds, receiving_air_yards, receiving_yards_after_catch, receiving_first_downs, receiving_fumbles_lost, receiving_epa, target_share, air_yards_share, wopr, racr, fg_made, fg_att, pat_made, fantasy_points, fantasy_points_ppr)`
  - `snap_counts(player_id, player_name, team, season, week, offense_snaps, offense_pct)`: `player_id` from `players.pfr_id → gsis_id`; drop rows with no match.
  - `games(game_id, season, week, game_type, gameday, away_team, home_team, away_score, home_score)`
  - `meta(key, value)` with `as_of_season`, `as_of_week`, `seasons`, `built_at`.
- `as_of_week` = max `week` in `weekly_stats` where `season = max(season)` and `season_type = 'REG'`.

- [ ] **Step 1:** Write tests: `test_tables_and_columns` (the four tables exist with exactly the listed columns), `test_as_of_week` (fixture with 2026 REG weeks 1–3 → `(2026, 3)`), `test_snap_counts_mapped_to_player_id`, `test_players_only_with_stats`, `test_column_comments_present` (`targets`, `target_share`, `season_type` have comments), `test_build_is_atomic` (existing DB untouched if build raises mid-way).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement `stats.py` (register polars frames with DuckDB, `CREATE TABLE … AS SELECT`) and `__main__.py`.
- [ ] **Step 4:** Run tests (PASS). Then run the real build once: `uv run --group ingest python -m lineup_lab.ingest stats`. Expected report: `as_of_season=2026`, `as_of_week=10` (or later), `weekly_stats` around 30k rows.

### Task 3: Read-only SQL runner and schema prompt

**Files:**
- Create: `backend/src/lineup_lab/stats/__init__.py`, `backend/src/lineup_lab/stats/db.py`, `backend/src/lineup_lab/stats/schema.py`, `backend/tests/stats/test_db.py`, `backend/tests/stats/test_schema.py`

**Interfaces:**
- Consumes: `stats_db` fixture.
- Produces:
  - `class StatsDB`: `__init__(path: Path)` opens `duckdb.connect(path, read_only=True, config={"enable_external_access": False, "lock_configuration": True})`. Methods: `run_sql(sql: str, max_rows: int) -> SqlResult` (raises `SqlError(message: str)`), `as_of() -> tuple[int, int]`, `coverage() -> Coverage(seasons: list[int], as_of_season: int, as_of_week: int)`, `players() -> list[PlayerRow(player_id, name, position, team, ppr_points)]`. One connection per instance; `run_sql` uses `conn.cursor()` per call (safe across threads).
  - `SqlResult(columns: list[str], rows: list[list[Any]], row_count: int, truncated: bool, duration_ms: int)`; values JSON-safe (dates → ISO strings, floats rounded to 3 places).
  - Guard before executing: strip comments and trailing `;`; reject unless a **single statement** starting with `SELECT` or `WITH`, by `SqlError("Only a single SELECT statement is allowed")`.
  - `schema_prompt(db: StatsDB) -> str`: per table, `name(col TYPE -- comment, …)`, then `Data as of Week {w}, {season}.` The text is deterministic (sorted, no timestamps) so it can be prompt-cached.

- [ ] **Step 1:** Write tests: `test_select_returns_rows`, `test_truncates_large_results` (`max_rows=2` on a 5-row query → 2 rows, `row_count=5`, `truncated=True`), `test_rejects_escape_attempts` (parametrized: `SELECT * FROM read_csv('/etc/passwd')`, `COPY weekly_stats TO '/tmp/x.csv'`, `ATTACH ':memory:' AS x`, `SET enable_external_access=true`, `INSTALL httpfs`, `SELECT 1; DROP TABLE players`, `DELETE FROM players`. Each raises `SqlError`, and `players` row count is unchanged), `test_error_message_is_readable` (bad column → `SqlError` whose message names the column), `test_schema_prompt_deterministic_and_complete` (two calls equal; contains every table name, `targets`, and the as-of line).
- [ ] **Step 2:** Run; FAIL.
- [ ] **Step 3:** Implement. `row_count` without fetching everything: `SELECT count(*) FROM (<sql>)` only when the first fetch hits `max_rows + 1`.
- [ ] **Step 4:** Run; PASS.

### Task 4: Player name resolver

**Files:**
- Create: `backend/src/lineup_lab/players/__init__.py`, `backend/src/lineup_lab/players/resolver.py`, `backend/src/lineup_lab/players/aliases.yaml`, `backend/tests/players/test_resolver.py`

**Interfaces:**
- Consumes: `StatsDB.players()`.
- Produces: `class PlayerResolver`, `__init__(players: list[PlayerRow], aliases: dict[str, str])` (alias → canonical full name), `@classmethod from_db(db: StatsDB)` loads `aliases.yaml`. `resolve(text: str) -> Resolution`.
  - `Resolution(text: str, status: Literal["resolved", "assumed", "ambiguous", "unknown"], player: PlayerRow | None, candidates: list[PlayerRow])`, where `candidates` holds at most 5, sorted by `ppr_points` descending.
- Algorithm (in order; first stage with any match wins): normalize (lowercase, strip punctuation and `jr/sr/ii/iii`) → alias → exact full name → exact last name or exact first name → `difflib.get_close_matches(cutoff=0.85)` on full names. One match → `resolved`. Several: if top `ppr_points ≥ 3 × second` → `assumed`; else `ambiguous`. None → `unknown`.
- `aliases.yaml` seed: `cmc: Christian McCaffrey`, `jsn: Jaxon Smith-Njigba`, `arsb: Amon-Ra St. Brown`, `ajb: A.J. Brown`, `bijan: Bijan Robinson`, `puka: Puka Nacua`, `jjettas: Justin Jefferson`, `tank: Tank Dell`, `jt: Jonathan Taylor`, `dk: DK Metcalf`. Drop any alias whose target isn't in `players` at load time and log a warning.

- [ ] **Step 1:** Write tests with a hand-built player list: `test_alias` ("CMC" → resolved McCaffrey), `test_first_name` ("Puka"), `test_misspelling` ("Christian McCafrey" → resolved), `test_dominant_assumed` (two "Smith"s, 300 vs 40 points → assumed), `test_ambiguous_without_dominant` (300 vs 200 → ambiguous, two candidates), `test_unknown_name` ("Kupp" absent → unknown, no player), `test_alias_to_missing_player_is_dropped`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS.

### Task 5: LLM wrapper with cost accounting

**Files:**
- Create: `backend/src/lineup_lab/llm/__init__.py`, `backend/src/lineup_lab/llm/client.py`, `backend/src/lineup_lab/llm/pricing.py`, `backend/tests/llm/test_pricing.py`, `backend/tests/llm/test_client.py`

**Interfaces:**
- Produces:
  - `PRICES: dict[str, Price]` with `claude-opus-5-5 → Price(input=4.00, output=20.00, cache_write=5.00, cache_read=0.20)` (USD per 1M tokens). `cost_usd(model: str, usage) -> float` reads `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` (`None` → 0). Unknown model raises `KeyError`.
  - `CallStats(model: str, input_tokens: int, output_tokens: int, cost_usd: float, duration_ms: int)`.
  - `class LLM`, `__init__(client: anthropic.AsyncAnthropic, model: str)`:
    - `async parse(system: str, messages: list[dict], schema: type[BaseModel], effort: str) -> tuple[BaseModel, CallStats]`: `client.messages.parse(..., output_format=schema, output_config={"effort": effort}, max_tokens=16000, cache_control={"type": "ephemeral"})`. If `stop_reason == "refusal"` or `parsed_output is None`, raise `LLMError("model declined or returned no output")`.
    - `async stream_text(system, messages, effort, on_text: Callable[[str], None]) -> tuple[str, CallStats]` uses `client.messages.stream(..., max_tokens=8000)`, calls `on_text` for each `text_stream` chunk, and returns the full text plus stats from `get_final_message().usage`.
  - `LLMError(message)`. SDK errors propagate unchanged; the API layer maps them to a user-safe message.
  - `class FakeLLM` in `tests/fakes.py` (scripted: queue of parse results and stream texts, records calls). It is used by Task 6–8 tests.

- [ ] **Step 1:** Write tests: `test_cost_opus` (1M input + 1M output → 24.00; 1M cache-read → 0.20), `test_none_usage_fields_are_zero`, `test_parse_raises_on_refusal` and `test_stream_text_calls_on_text`. The last two use a stub object shaped like `AsyncAnthropic` that returns canned responses. No network.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS.

### Task 6: Agent graph (route → resolve → SQL loop → answer)

**Files:**
- Create: `backend/src/lineup_lab/agent/__init__.py`, `agent/state.py`, `agent/events.py`, `agent/prompts.py`, `agent/nodes.py`, `agent/graph.py`, `backend/tests/agent/test_graph.py`

**Interfaces:**
- Consumes: `StatsDB`, `schema_prompt`, `PlayerResolver`, `LLM` / `FakeLLM`, `Settings`.
- Produces:
  - Events (`agent/events.py`): dataclasses serialized with `asdict`. They form the SSE contract, and Task 7 and the frontend use them verbatim:
    - `StepEvent(id: str, kind: Literal["route","resolve","sql","answer","decline"], status: Literal["started","done","failed"], summary: str, detail: dict, duration_ms: int | None)`. `detail` holds route+reason; `resolutions` (text → name/status); `sql`, `attempt`, `row_count`, `error`; `model`, `input_tokens`, `output_tokens`.
    - `TokenEvent(text: str)`
    - `SourceEvent(n: int, kind: Literal["stat"], label: str, columns: list[str], rows: list[list], row_count: int, truncated: bool)`
    - `DoneEvent(ttft_ms: int | None, total_ms: int, cost_usd: float, input_tokens: int, output_tokens: int)`
    - `ErrorEvent(message: str)`
  - LLM output schemas (Pydantic): `RouteDecision(route: Literal["stats","podcasts","out_of_scope","ambiguous"], reason: str, player_mentions: list[str])` and `SqlDraft(sql: str, label: str)` (label like "Targets, Weeks 8–10").
  - `AgentState` (TypedDict): `question`, `route`, `route_reason`, `mentions`, `resolutions: list[Resolution]`, `sql_attempts: list[dict]` (sql, error | None), `result: SqlResult | None`, `answer`, `calls: list[CallStats]`.
  - `build_graph(deps: AgentDeps) -> CompiledGraph`, where `AgentDeps(db, resolver, llm, settings)`. Nodes: `route`, `resolve`, `gen_sql`, `run_sql`, `answer`, `decline`. Edges: `START→route`; `route→resolve` if route `stats`, else `→decline`; `resolve→gen_sql` unless any resolution is `ambiguous`/`unknown` (then `→decline`); `gen_sql→run_sql`; `run_sql→gen_sql` on error while attempts < `sql_max_attempts`; `run_sql→answer` on success; `run_sql→decline` when attempts are exhausted; `answer→END`, `decline→END`.
  - Nodes emit events with `langgraph.config.get_stream_writer()`. The `answer` and `decline` nodes write the reply as `TokenEvent`s (decline text is fixed per reason: podcasts "not loaded yet", out of scope, unknown or ambiguous name listing candidates as "Did you mean …?", SQL gave up). `run_sql` calls `db.run_sql` through `asyncio.to_thread`.
  - `async run_agent(deps, question: str) -> AsyncIterator[Event]` runs `graph.astream(..., stream_mode="custom")`, yields events, and ends with `DoneEvent` (cost summed over `calls`, `ttft_ms` = time to first `TokenEvent`). On `LLMError`/SDK error it yields `ErrorEvent("Something went wrong talking to the model. Please try again.")` and stops.
- Prompts (`prompts.py`, constant strings except the injected schema and as-of): the router describes the four routes with one example each. The SQL prompt is `schema_prompt` + rules: use the resolved `player_id`s given; `season_type = 'REG'` unless asked; "last N weeks" = `as_of_week-N+1 … as_of_week` of `as_of_season`; select `player_name` + the asked stat; on retry the previous SQL and error are appended as a user turn. The answer prompt gets numbered sources `[1]` and these rules: cite every number, state the week range, start/sit = "Lean X" with reasons, never use outside knowledge, 2–5 sentences, and say "Assuming <name> (<team>, <pos>)." first when a resolution is `assumed`.

- [ ] **Step 1:** Write tests using `FakeLLM` + the `stats_db` fixture, collecting `run_agent` events: `test_stat_lookup_happy_path` (event kinds in order: route, resolve, sql(started), sql(done), source n=1, ≥1 token, done; done cost = sum of fake stats), `test_sql_retry_then_success` (first draft bad column → `sql` failed with error text, second succeeds; gen_sql's 2nd call includes the error text), `test_sql_gives_up_after_three_attempts` (three bad drafts → three failed sql steps, decline tokens contain "couldn't", contain no digits, no source event), `test_podcast_route_declines`, `test_ambiguous_name_asks` (two Smiths without dominance → tokens contain "Did you mean", no SQL step), `test_assumed_name_passed_to_answer` (answer prompt contains "Assuming"), `test_llm_error_yields_error_event`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** Run; PASS.

### Task 7: HTTP API (SSE, limits, cap, static files)

**Files:**
- Create: `backend/src/lineup_lab/api/__init__.py`, `api/app.py`, `api/sse.py`, `api/limits.py`, `backend/tests/api/test_chat.py`, `backend/tests/api/test_limits.py`, `backend/src/lineup_lab/examples.yaml`

**Interfaces:**
- Consumes: `run_agent`, events, `StatsDB.coverage()`, `Settings`.
- Produces:
  - `create_app(settings: Settings, deps_factory: Callable[[], AgentDeps] | None = None) -> FastAPI` (tests inject fakes).
  - `POST /chat` body `{"question": str, "chat_id": str | null}`. Responses: `400` if empty or over 500 chars; `429` `{"detail": "...", "retry_after_s": int}` over the per-IP limit; `503` `{"detail": "Live questions are paused until <UTC midnight>."}` when the daily cap is reached. Otherwise `200 text/event-stream` with header `X-Chat-Id` (new `uuid4().hex` if none given). Each frame is `event: <step|token|source|done|error>\ndata: <json>\n\n` (`sse.py: format_event(event) -> bytes`).
  - `GET /api/meta` returns `{"coverage": {...}, "examples": [{"group": str, "questions": [str]}]}` from `examples.yaml` (groups: STATS, EDGE CASES).
  - `GET /healthz` returns `{"ok": true}`.
  - If `settings.static_dir` is set, mount it at `/` with `html=True` after the API routes.
  - `limits.py`: `RateLimiter(per_hour: int, clock)` with `check(ip) -> int | None` (seconds until reset or None), a sliding window kept in a dict, no persistence; `SpendTracker(cap_usd: float, clock)` with `add(usd)`, `exhausted() -> bool`, `resets_at() -> datetime`, resetting at UTC midnight. The client IP is the **rightmost** `X-Forwarded-For` entry (Cloud Run appends the real client IP), else `request.client.host`.
  - Cost is added to `SpendTracker` from each `CallStats` as it completes, **inside a `finally`**, so cancelled streams still count.

- [ ] **Step 1:** Write tests: `test_limits.py` (21st request in an hour → wait seconds > 0; window slides; spend over cap → exhausted; resets next UTC day; uses a fake clock), and `test_chat.py` with `httpx.AsyncClient(transport=ASGITransport(app))` and a fake agent: `test_stream_frames_in_order`, `test_question_too_long_400`, `test_rate_limited_429`, `test_cap_reached_503`, `test_xff_rightmost_used`, `test_disconnect_cancels_and_charges` (fake agent emits one call's cost and then awaits forever; client closes after the first frame → the agent task is cancelled and `SpendTracker` includes that cost), `test_meta_has_coverage_and_examples`.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement (`StreamingResponse` over an async generator; cancellation propagates from Starlette into `run_agent`). **Step 4:** Run; PASS.
- [ ] **Step 5 (needs an `ANTHROPIC_API_KEY` in `backend/.env`; costs about $0.10):** `uv run uvicorn lineup_lab.api.app:app --reload`, then `curl -N -X POST localhost:8000/chat -H 'content-type: application/json' -d '{"question":"How many targets did Puka Nacua have the last 3 weeks?"}'`. Expected: step, step, step, source, token…, done frames.

### Task 8: SQL eval set and runner

**Files:**
- Create: `backend/evals/__init__.py`, `backend/evals/sql_cases.yaml`, `backend/evals/run_sql_eval.py`, `backend/evals/grading.py`, `backend/tests/evals/test_grading.py`, output `backend/evals/results/sql-<date>.json` (committed)

**Interfaces:**
- Consumes: `build_graph` pieces (`route`, `resolve`, `gen_sql`, `run_sql` via `run_agent` with the real `LLM`), `StatsDB`.
- Produces:
  - Case format: `{id: str, question: str, route: stats|podcasts|out_of_scope|ambiguous, reference_sql: str | null}`. `reference_sql` is null for non-stats routes.
  - `grade(reference: SqlResult, actual: SqlResult | None) -> bool` passes when row counts are equal **and** every reference column's sorted value list (floats rounded to 1 decimal, strings casefolded) equals the sorted values of **some** actual column. Extra actual columns are allowed. Documented limitation: it doesn't check row alignment across columns.
  - Runner: `uv run python -m evals.run_sql_eval [--limit N]` runs each case through the agent and records route accuracy, SQL execution accuracy (stats cases), attempts used, cost, and latency. It writes the JSON results file and prints a summary table.
  - Seed **20 cases**: 14 stat lookups (single player multi-week sums, leaders top-5, per-game averages, snap %, a 2025 full-season question, a playoff question, a kicker), 3 out-of-scope ("Is Kupp injured?", "Who wins the NBA title?", "Project Bijan's points"), 2 podcast, 1 ambiguous-name.

- [ ] **Step 1:** Write `test_grading.py`: equal results pass; extra actual column passes; reordered rows pass; wrong value fails; row-count mismatch fails; `actual=None` fails; float 12.04 vs 12.0 passes.
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement grading, runner, and cases. Check every `reference_sql` runs against the real DB.
- [ ] **Step 4:** Run tests; PASS. **Step 5 (needs API key; costs about $1–2; ask the owner first):** run the full eval, commit the results file, and note the baseline numbers in the tech spec's §7.

### Task 9: Frontend (landing, streaming answer, inspector)

**Files:**
- Create via `npm create vite@latest frontend -- --template react-ts`, then: `frontend/src/api/sse.ts`, `frontend/src/api/chat.ts`, `frontend/src/api/types.ts`, `frontend/src/components/Landing.tsx`, `Conversation.tsx`, `Inspector.tsx`, `StepList.tsx`, `StatCard.tsx`, `frontend/src/App.tsx`, `frontend/src/api/sse.test.ts`, `frontend/src/chatReducer.ts`, `frontend/src/chatReducer.test.ts`; `vite.config.ts` proxies `/chat`, `/api` → `localhost:8000`.

**Interfaces:**
- Consumes: the SSE contract and `/api/meta` from Task 7. `types.ts` mirrors the Task 6 event dataclasses exactly.
- Produces:
  - `parseSSE(chunk: string, buffer: string) -> { events: {event: string, data: unknown}[], buffer: string }`. Frames can split across network chunks.
  - `streamChat(question, chatId, signal, onEvent) -> Promise<{chatId}>` uses `fetch` POST + `response.body.getReader()`. Non-200 responses become an `error` event carrying the server's `detail`.
  - `chatReducer(state, action)`: one `Exchange` per question `{question, answer, steps[], sources[], done?, error?}`. Steps are keyed by `id` (a `done`/`failed` update replaces its `started` entry).
  - UI per functional spec §5.1/§5.2: the landing has a coverage line from `/api/meta` (never hard-coded), grouped example buttons that run immediately, an input with a 500-char limit, and the privacy line omitted (no logging yet). The answer view is two panes: conversation on the left (streaming text, `[n]` buttons that switch the inspector to Sources and highlight the card, footer "X.Xs first token · Y.Ys · $0.0ZZ", a Stop button while running, New chat); the inspector on the right with **Under the hood** (live steps: icon by status, summary, duration, expandable SQL `<pre>` / error) and **Sources** (stat card: label + table, "showing 50 of N rows" when truncated). Clicking an earlier exchange points the inspector at it. Below 900px the inspector stacks under the answer.
  - Title "Lineup Lab", tagline "Fantasy football answers backed by the numbers and what analysts said."

- [ ] **Step 1:** Write `sse.test.ts` (one frame; two frames in one chunk; one frame split across chunks; ignores comment lines) and `chatReducer.test.ts` (step started→done replaces; tokens append; source added; error sets error and keeps partial answer).
- [ ] **Step 2:** `cd frontend && npm i -D vitest && npx vitest run`. FAIL.
- [ ] **Step 3:** Implement the parser, reducer, client, and components.
- [ ] **Step 4:** `npx vitest run` (PASS), `npm run build` (no type errors).
- [ ] **Step 5 (manual, needs API key):** with the backend running, `npm run dev`. Click a STATS example: steps appear live, the answer streams, `[1]` opens the stat card, Stop halts streaming. Check a phone-width layout.

### Task 10: Container and Cloud Run deploy

**Files:**
- Create: `Dockerfile` (repo root), `.dockerignore`, `.gcloudignore`, `README.md` (pitch, local dev, deploy, status), `scripts/deploy.sh`

**Interfaces:**
- `Dockerfile`: stage 1 `node:22-slim` runs `npm ci && npm run build` in `frontend/`. Stage 2 `python:3.12-slim` + `uv`: `uv sync --frozen --no-dev` (no `ingest` group), copies `backend/src`, `frontend/dist → /app/static`, `data/stats.duckdb → /app/data/stats.duckdb`. Env `STATS_DB_PATH=/app/data/stats.duckdb STATIC_DIR=/app/static`. `CMD uvicorn lineup_lab.api.app:app --host 0.0.0.0 --port ${PORT:-8080}`.
- `.gcloudignore` **must re-include** `data/stats.duckdb` (gcloud otherwise falls back to `.gitignore`, which excludes `data/`) and exclude `node_modules`, `.venv`, other `data/*`.
- `scripts/deploy.sh`: `gcloud run deploy lineup-lab --source . --region us-east1 --max-instances 1 --memory 1Gi --allow-unauthenticated --set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest --set-env-vars DAILY_CAP_USD=5`.

- [ ] **Step 1:** `docker build -t lineup-lab .` succeeds. Then `docker run --rm -p 8080:8080 --env-file backend/.env lineup-lab`. `curl localhost:8080/healthz` returns `{"ok":true}`, `/` serves the app, and one example question streams.
- [ ] **Step 2 — ON HOLD (owner decision, 2026-11-18): don't deploy until the owner says so.** (Outward-facing; when unblocked, confirm the GCP project and region first.) create the secret (`gcloud secrets create anthropic-api-key --data-file=-`), run `scripts/deploy.sh`, and open the URL. Repeat the Task 9 Step 5 checks against it.
- [ ] **Step 3:** Add the public URL and "PoC: stats only" status to `README.md`, and record the Cloud Run settings in technical-spec §4.
