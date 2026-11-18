# Project context

## Who I am and why I'm building this
- I have ML experience but have not built RAG or LLM applications before.
- I'm building a portfolio project to qualify for LLM-focused "AI engineer" roles.
- Main target: Verizon "AI Engineer - Go To Market" (Python/TypeScript, RAG pipelines,
  agents, LangChain/LangGraph, vector databases, evaluation and observability,
  streaming APIs, Docker, CI/CD, rapid prototyping with AI coding tools;
  speech-to-text is a bonus).
- Interviews for these roles reportedly focus on drilling into what you built,
  so I need to understand every design decision. Explain trade-offs as we go
  and don't hide logic inside framework abstractions.

## The project
A fantasy football analyst agent that combines:
1. A stats database queried through text-to-SQL.
2. Podcast transcripts searched through RAG, with timestamped links to the audio.

Example: "Should I start Player A or Player B this week?" returns recent stats
for both plus clips of analysts discussing them.

Working name: "Receipts" (suggested, not final).
Sport: NFL assumed (not confirmed).

## Proposed architecture
- Stats: nflverse data via the `nflreadpy` package (not the deprecated
  `nfl_data_py`), loaded into DuckDB. Refresh weekly in season.
  DuckDB is an embedded library (no server), so the stats file ships inside
  the app container and is opened read-only.
- Text-to-SQL: the LLM gets the schema in its prompt and calls a
  `run_sql(query)` tool. Read-only connection. Feed errors back for retries.
  Write this by hand instead of using a wrapper library.
- Podcasts: read RSS feeds (`feedparser`), download audio, transcribe with
  Whisper (`faster-whisper`), keeping timestamps.
- RAG: chunk transcripts (about 30-60 seconds of speech), embed, store in a
  vector database with metadata (podcast, episode date, start timestamp,
  audio URL, players mentioned). Vector database: Qdrant (decided, see
  Storage below).
- Agent: LangGraph routes each question to SQL, vector search, or both, then
  merges the results into one cited answer.
- Serving: streaming API, simple web demo, Docker, deployed publicly.

## Storage (decided)
| Data | Now | Later, if needed |
|---|---|---|
| Stats | DuckDB file in the app container | MotherDuck (settings change) |
| Transcript chunks | Qdrant server container next to the app (Docker Compose) | Qdrant Cloud (settings change, then re-run ingestion) |

- Why: simplest setup, same compute, no accounts or free-tier suspensions.
  Hosting isn't a selling point; evaluation and retrieval decisions are.
- Connection details come from environment variables (`STATS_DB_PATH`,
  `QDRANT_URL`, `QDRANT_API_KEY`), never hard-coded.
- All Qdrant calls go through one module (e.g. `search_transcripts(...)`);
  the agent never uses the client directly.
- The ingestion pipeline can rebuild the Qdrant collection from stored
  transcripts, so moving servers means re-running it.
- Weekly refresh: rebuild the stats file and load new transcript chunks,
  then redeploy.
- Rejected: Neon/pgvector (wanted a dedicated vector database), DuckDB's
  vector extension (not a real vector database), Qdrant local mode
  (test-only engine), hosted-by-default (adds accounts and latency for no
  benefit at this scale).

## Build stages (each should work independently)
1. Stats agent with text-to-SQL (about week 1).
2. Podcast search with timestamped citations (about week 2).
3. Combined agent, streaming, deployment (a few days).

## Evaluation (the most important part)
- SQL accuracy: 50+ questions with known numeric answers.
- Retrieval quality: is the correct clip in the top results?
- Routing accuracy: does the agent pick the right tool?
- "I don't know" behavior when the data doesn't cover the question.
- Latency (time to first token) and cost per question.
- Keep before/after numbers for experiments: chunk size, hybrid
  (keyword + vector) search, reranking, model choice.

## Known hard problems
- Player name matching across stats and transcripts ("CMC" vs
  "Christian McCaffrey").
- Recency: prefer this week's episodes (use date metadata filters).
- Scope: start with two seasons of stats and the last 4-6 weeks of
  3-4 podcasts.

## Constraints
- Public demo shows short transcript snippets with links to the episode,
  not full transcripts.
- No "NFL" or team names in the project title.
- README should cover what failed and the quality/latency/cost trade-offs.

## Open decisions
- Final project name
- Sport (NFL assumed)
- Which podcasts
- LLM and embedding model providers