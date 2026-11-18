# Lineup Lab: Functional Spec

*Fantasy football answers backed by the numbers and what analysts said.*

- **Date:** 2026-11-18
- **Status:** Draft for review
- **Companion doc:** `proj.md` (architecture, storage, eval plan). This spec covers **what the app does and what users see**. `proj.md` covers how it's built. Where they overlap, this spec wins on behavior and `proj.md` wins on infrastructure.

Items marked **(call)** were decided by Claude during brainstorming, not by the owner. They're sensible defaults; revisit freely.

---

## 1. Purpose and audience

Lineup Lab is a portfolio project for landing an LLM-focused "AI Engineer" role (main target: Verizon "AI Engineer - Go To Market").

**Primary user: a hiring manager or interviewer** who clicks a resume link and spends a few minutes poking at the app. They need to:

1. Understand what it is within ~10 seconds.
2. See it work with one click.
3. Look under the hood: how the agent routed, what SQL it ran, what it retrieved, and what it cost.
4. Find evidence of rigor: eval numbers, experiments, known failures.

Real fantasy players are a welcome secondary audience, but no decision should trade interviewer clarity for player convenience.

## 2. Goals, non-goals, anti-goals

**Goals**
- Answer fantasy football questions by combining a stats database (text-to-SQL) and podcast transcripts (RAG), with every claim cited.
- Make the agent's reasoning visible and inspectable in the UI.
- Publish measured quality, latency, and cost numbers, including before/after results for experiments.
- Stay explainable: the owner must be able to defend every design decision in an interview.

**Non-goals**
- Live, always-current data for real weekly lineup decisions (weekly refresh is a nice-to-have, see §8).
- User accounts, saved history, or personalization.
- Projections or point predictions.
- Full transcripts or full-episode playback inside the app.
- Sports other than NFL fantasy football.

**Anti-goals** (failure even if it technically works)
- Confident answers not backed by a cited source.
- A polished demo that hides how it works. If an interviewer can't see the SQL, retrieval, and routing, the project misses its point.
- Logic buried inside framework abstractions that the owner can't explain.
- A demo that's broken or costs-capped when an interviewer visits, with no graceful fallback.

## 3. Use cases

Each use case maps to a **route** the agent takes. Routes are explicit, so routing accuracy can be measured (see `proj.md` → Evaluation).

| # | Use case | Route | Example question |
|---|---|---|---|
| 1 | Stat lookup | Stats only | "How many targets did Puka Nacua have the last 3 weeks?" |
| 2 | Podcast search | Podcasts only | "What are podcasts saying about the Bears backfield?" |
| 3 | Stats + takes | Both, **in parallel** | "Start Puka Nacua or Garrett Wilson?" |
| 4 | Fact-check a take | **Podcasts → stats** (chained) | "Pod A said Bijan's red-zone work is up. True?" |
| 5 | Explain a stat | **Stats → podcasts** (chained) | "Why did X's snap share drop?" |
| 6 | Settle a debate | **Podcasts (find conflicting claims) → stats (grade each)** | "I heard conflicting takes on Wilson. Who's right?" |
| 7 | Analysts disagree | Podcasts only, presented as sides | "Are analysts high or low on Jaxon Smith-Njigba?" |
| 8 | Out of scope | None, or a failed lookup → declines | "Is Kupp injured?" / "Who wins the NBA title?" |
| 9 | Ambiguous | Clarify first | "How's Josh Allen doing?" |
| 10 | Follow-up | Any of the above, using conversation context | "What about last season?" / "Compare him to Chase." |

### Expected behavior per use case

1. **Stat lookup.** Answer with the numbers and a stats source card showing the result table. If the first SQL attempt errors, the agent retries with the error message (visible in the trace).
2. **Podcast search.** Summarize what was said, citing 1–5 clips. Prefer recent episodes (see §4, recency).
3. **Stats + takes.** Run both lookups independently, then merge. Start/sit questions get a **lean** ("Lean Nacua"), never a guarantee, plus the evidence for both sides.
4. **Fact-check a take.** Find the claim in the transcripts, turn it into a stat query, and report whether the data **supports**, **contradicts**, or **can't check** it. If the claim can't be found in any loaded episode, say so instead of checking a paraphrase the user may have misremembered.
5. **Explain a stat.** Get the number first, then search for analysts discussing it. If no podcast discusses it, return the stat and say no loaded episode covers it.
6. **Settle a debate.** Find the conflicting claims and grade each one separately: ✅ supported / ❌ contradicted / ➖ can't check with stats (predictions, opinions, things the data doesn't track). Name a "winner" only when one side is clearly supported and the other contradicted. Otherwise, say it's unresolved and why.
7. **Analysts disagree.** When retrieved clips take opposite positions, show the sides side by side, each attributed to its podcast and episode, rather than blending them into one opinion. This applies to any route that returns clips, not only explicit "disagree" questions. **(call)** Attribution is at the podcast level, not the individual host. Naming hosts would require speaker identification during transcription. That's a possible later experiment, but not v1.
8. **Out of scope.** Say plainly what can't be answered and why (not in the data, not covered by loaded podcasts, a prediction, not football). Where possible, suggest a nearby question it *can* answer. Never invent stats or quotes. Covers: injury/news status, players or seasons not loaded, stat types not in the schema, point projections, other sports, and off-topic requests.
9. **Ambiguous.** When a name or reference could mean more than one player, reply with a short "Did you mean…?" and one button per candidate (e.g., "Josh Allen (BUF, QB)" / "Josh Allen (JAX, LB)"). Clicking one re-runs the question. **(call)** If one candidate is overwhelmingly likely in a fantasy context (the QB over the defensive player), answer and state the assumption at the top instead of asking: "Assuming Josh Allen (BUF, QB)."
10. **Follow-ups.** References like "him," "that stat," and "last season" resolve against the conversation. The agent remembers the last ~5 exchanges **(call)**. "New chat" clears it.

## 4. Answer rules (apply to every answer)

- **Every factual claim is cited.** Stats claims cite a stats source; podcast claims cite a clip. Uncited general football knowledge is not allowed in the answer body.
- **"Now" means the data's as-of week, not today's date.** "This week," "last 3 weeks," and "this season" resolve relative to the loaded data's as-of week (§8). The answer states the range used ("Weeks 9–11, 2026").
- **Recency in podcasts.** By default, prefer episodes from the last ~2 weeks of the loaded range. Older clips may appear but are labeled with their date. Questions that name a time frame override this.
- **Player name resolution.** Nicknames, partial names, and common misspellings ("CMC," "Puka," "JSN") resolve to a canonical player. The resolution is shown in the trace.
- **Leans, not guarantees.** Recommendations are framed as a lean with reasons.
- **Short quotes only.** Clip quotes are at most ~2 sentences / ~40 words **(call)**. Full transcripts are never shown.
- **Honest failure.** If a step fails (SQL keeps erroring, search returns nothing relevant), the answer says what it couldn't get rather than silently answering from the other source alone.

## 5. Screens

The frontend is a single-page React app (see §9). It has four views, with a shared header showing **Lineup Lab · How it works · Eval results · GitHub**.

### 5.1 Landing (before the first question)

```
┌───────────────────────────────────────────────────────────────┐
│ Lineup Lab                    How it works · Eval results · GH │
│ Fantasy football answers backed by the numbers and what       │
│ analysts said.                                                │
│ ┌───────────────────────────────────────────────────────────┐ │
│ │ 📊 Stats: 2025–2026 seasons, through Week 11              │ │
│ │ 🎙 4 podcasts, 38 episodes (Oct 6 – Nov 17)                │ │
│ │ Data as of Week 11, 2026                                  │ │
│ └───────────────────────────────────────────────────────────┘ │
│ STATS          (Who led in targets the last 3 weeks?)         │
│ PODCASTS       (What are podcasts saying about …?)            │
│ BOTH           (Start Puka or Wilson?)                        │
│ FACT-CHECK     (Pod A says Bijan's usage is up. True?)        │
│ SETTLE A DEBATE(Analysts disagree on Wilson. Who's right?)    │
│ EDGE CASES     (How's Josh Allen doing?) (Is Kupp injured?)   │
│ ┌───────────────────────────────────────────────────────────┐ │
│ │ Ask about a player, stat, or podcast take…           [→]  │ │
│ └───────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

- The **coverage line** is generated from the loaded data, never hand-written.
- **Example questions** are grouped by use case. Clicking one runs it immediately. Each group has 1–2 examples, chosen so they produce good answers against the current snapshot. The list lives in a config file and is updated on each data refresh.
- The **Edge cases** group deliberately shows "I don't know" and "Did you mean…?" behavior.
- Input limit: 500 characters **(call)**.

### 5.2 Answer view

After the first question, the page becomes a two-pane layout: **conversation on the left, inspector on the right.**

```
┌──────────────────────────────┬────────────────────────────────┐
│ You: Start Puka or Wilson?   │ [Sources] [Under the hood]     │
│                              │                                │
│ Lean Nacua. More targets     │ ▸ Route: stats + podcasts      │
│ over Weeks 9–11 [1], and two │ ▸ Resolved "Puka" → Puka Nacua │
│ of three podcasts favor him  │ ▸ SQL · attempt 1 ✗ (bad col)  │
│ [2][3]. One analyst likes    │ ▸ SQL · attempt 2 ✓ · 38ms     │
│ Wilson's matchup [4].        │   SELECT player, SUM(targets)… │
│                              │ ▸ Search · 12 hits → top 4     │
│ 2.1s first token · 4.8s ·    │ ▸ Answer · 412 tokens          │
│ $0.004                       │                                │
│ ──────────────────────────── │                                │
│ [Ask a follow-up…]  [New chat]│                               │
└──────────────────────────────┴────────────────────────────────┘
```

**Left: conversation**
- Answers stream in token by token. A **Stop** button cancels a running answer.
- Citations appear as `[n]`. Clicking one switches the inspector to Sources and highlights that card.
- A footer under each answer shows time to first token, total time, and cost.
- Special formats:
  - *Settle a debate / fact-check:* each claim is a row with its ✅ / ❌ / ➖ verdict and citations.
  - *Analysts disagree:* sides shown in two columns, each with attributed clips.
  - *Ambiguous:* "Did you mean…?" with one button per candidate.
  - *Out of scope:* a plain explanation plus, if possible, a suggested question it *can* answer (clickable).
- Earlier exchanges stay in the thread. **(call)** Clicking an earlier answer points the inspector at that answer's sources and trace.

**Right: inspector, "Sources" tab**
- *Stat card:* a short label ("Targets, Weeks 9–11") and a small result table. Large results are truncated with a row count.
- *Clip card:* podcast name, episode title, episode date, timestamp, short quote, and a **▶ play** button. Play opens a small built-in audio player that streams the episode's public audio URL from the clip's timestamp and **stops at the end of the clip** (the chunk's end time plus a few seconds). Below the player is a link: "Continue on [podcast]'s site." This keeps §2's "no full-episode playback" rule. If the audio can't play inline, the card links to the episode page instead **(call)**.

**Right: inspector, "Under the hood" tab**
- Steps appear live, in order, while the agent works:
  - **Route chosen** (one of the routes in §3) and a one-line reason.
  - **Name resolution** (input text → canonical player).
  - **SQL**: the query, attempt number, result row count, duration. Failed attempts are shown with their error, followed by the retry.
  - **Search**: the query used, filters (date, podcast, player), hit count before and after reranking, and top hit scores.
  - **Claim extraction** (use cases 4 and 6): the claims found in transcripts.
  - **Answer generation**: model name and token counts.
- Each step shows its duration. The final summary shows total cost.

**Narrow screens (call):** the inspector collapses below the answer as two expandable sections.

### 5.3 Eval results page

The evidence of rigor. It's generated from the committed output of the eval run, so the numbers always match the latest real run.

- **Scorecard:** SQL accuracy, retrieval hit rate (correct clip in top 5), routing accuracy, "I don't know" accuracy, median and p95 time to first token, and median cost per question. Each shows the test set size and the run date.
- **Experiments table:** one row per experiment (chunk size, hybrid search, reranking, model choice, …) with before/after numbers and a one-line takeaway.
- **Known failures:** real examples of wrong or weak answers, each with what went wrong and whether it was fixed.

### 5.4 How it works page

The README in friendlier form:
- an architecture diagram
- a walkthrough of one question through the system
- short "why X over Y" notes, reusing §9

Static content.

## 6. Streaming contract (functional level)

Each question is one HTTP request. The answer streams back on the same response.

**Request:** `POST /chat` with the question text and a `chat_id` (new chat → server issues one). Follow-ups reuse the `chat_id`. Clicking a "Did you mean…?" button sends a new request with the chosen player made explicit.

**Response:** a Server-Sent Events stream of typed events, in order:

| Event | Meaning | Drives |
|---|---|---|
| `step` | An agent step started, finished, or failed (type, summary, details, duration) | Under the hood tab |
| `token` | A piece of answer text | Answer text |
| `source` | A citation's content (stat table or clip), with its `[n]` number | Sources tab |
| `clarify` | The agent needs the user to pick between candidates | "Did you mean…?" buttons |
| `done` | Final timing and cost | Answer footer |
| `error` | The request failed. Includes a user-safe message | Error message + retry button |

Cancelling the request (Stop button, or closing the tab) stops server-side work.

## 7. Public demo protection

- **No login.**
- **Per-visitor limit:** ~20 questions per hour, keyed by IP. Over the limit → a friendly message with the time until reset.
- **Daily spending cap:** a configurable dollar limit (**(call)** start at $5/day). When it's reached:
  - Example questions **replay recorded runs**, clearly labeled "Recorded run, from [date]". They replay the full event stream, so the Under the hood tab still works.
  - Free-form questions are paused, with a message saying when they'll resume.
- Recorded runs are captured from real live runs of each example question at each data refresh.
- Normally, example questions always run **live**.
- For rate limiting, IPs are held in memory only and never written to storage **(call)**.

## 7a. Question logging (observability)

Every live question is stored on the server, for two reasons: finding real failures for the "Known failures" section, and growing the eval set from real traffic.

- **Stored per question:**
  - question text and `chat_id`
  - route chosen
  - the full step trace (the same `step` events the UI shows, including SQL, search hits, and errors)
  - final answer and sources
  - timings, token counts, and cost
  - whether it was live or a recorded replay
- **Not stored:** IP addresses or any other visitor identifier.
- **Privacy note:** a one-line notice under the input box: "Questions are logged anonymously to improve the app."
- **Retention:** 90 days **(call)**.
- The owner can export logs locally, and turn a logged question into an eval case by adding the expected answer.
- Storage is a simple store on the server (e.g., a SQLite file or JSON-lines on a mounted volume). The exact choice is left to the builder. A hosted tracing tool (LangSmith, Langfuse) is out of scope for v1, but is a candidate experiment later.

## 8. Data coverage and freshness

- **Stats:** the 2025 season and the 2026 season to date (NFL, via nflverse).
- **Podcasts:** 3–4 shows, the most recent 4–6 weeks of episodes.
- **As-of week:** the latest completed week in the stats data. It's shown in the coverage line and drives all relative time words (§4).
- **During the season:** refresh weekly when practical (stats, new episodes, example questions, recorded runs), then redeploy. Missing a week is fine; the coverage line stays truthful.
- **After the season ends:** the data freezes at the final week. The app keeps working on that snapshot. Example questions stay valid because they're written against the snapshot, not against "today."
- **Podcast selection rule:** only use shows whose audio file is the same on every download (no dynamic ad insertion). Otherwise, clip timestamps drift by the length of the inserted ads. Check by downloading the same episode twice and comparing duration and checksum.

### 8a. Data refresh job (operator view)

The refresh is a **batch job, not a service**: it runs, does its work, and exits. Nothing runs continuously.

- **v1 runs manually on the owner's laptop** with one command (e.g., `python -m lineup_lab.refresh`). Transcription runs locally with faster-whisper. The job is designed so it could later run on a schedule (cron, GitHub Actions) with only config changes.
- **One command updates everything, in order:**
  1. Pull new stats and rebuild the DuckDB file.
  2. Read each podcast's RSS feed and find new episodes.
  3. Download and transcribe new episodes, keeping segment timestamps.
  4. Chunk, tag player mentions, embed, and load into Qdrant.
  5. Recompute the coverage line and as-of week (§8).
  6. Check the example questions still produce good answers, and re-record their recorded runs (§7).
  7. Re-run the evals and regenerate the Eval results data (§5.3).
- **Skips work already done.** Episodes are tracked by their RSS ID (GUID). Re-running never re-downloads or re-transcribes an episode it already has.
- **Each stage's output is saved.** Transcripts (with timestamps) are saved as files and are the **source of truth**. Qdrant can be rebuilt from them at any time. Re-chunking or re-embedding (e.g., for chunk-size experiments) never requires re-transcribing.
- **One failure doesn't stop the run.** A failed episode is logged and skipped, and everything else still updates. The next run retries it.
- **Ends with a report:**
  - episodes added, skipped, and failed (with reasons)
  - new chunk count
  - new as-of week
  - eval score changes vs. the previous run
- **Initial load:** the first run backfills 4–6 weeks of episodes (roughly 40–80 hours of audio). Expect it to run overnight. Weekly runs are much smaller.
- **Getting it to production:** after the job finishes, the new stats file and Qdrant data are pushed to the deployed app and it's redeployed. How (direct writes to the production Qdrant vs. a snapshot upload) is left to the builder.

## 9. Approaches and decisions

### Answer layout
Three were considered:
- **A:** everything inline in one chat column.
- **B:** answer plus a sources panel.
- **C:** answer plus an inspector with Sources and Under the hood tabs.

**Chosen: C.** The audience is interviewers who drill into decisions, and C puts the routing, SQL, retrieval, and costs on screen. Live step-by-step streaming also demonstrates the streaming requirement. A hid the trace. B showed sources but not reasoning.

### Landing page
- **Minimal** (title + 4 examples) vs. **guided** (coverage line + examples grouped by use case + edge cases + header links).
- **Chosen: guided.** It works as a menu of capabilities, lets an interviewer see failure handling in one click, and links to the eval numbers.

### Frontend: React + TypeScript, built with Vite
- **Vite** is a build tool and dev server. It compiles TypeScript/JSX into static HTML/JS/CSS that can be served from anywhere, including the API's container.
- **Next.js** (rejected) is a full framework with its own Node server, server-side rendering, and backend routes. Server-side rendering mostly helps search indexing and first-load speed on content sites. A one-page demo doesn't need it. And the backend is Python, so Next.js would add a second server to justify.

### Orchestration: LangGraph, used only for the graph
- **Hand-written loop:** most transparent, but parallel branches, retries, conversation memory, and step streaming would all be hand-built.
- **LangChain agents / LlamaIndex:** hide routing and retrieval logic. LlamaIndex is built mainly around RAG, not SQL plus RAG routing.
- **CrewAI / AutoGen:** multi-agent frameworks. Overkill for one agent with two tools.
- **Chosen: LangGraph** for the graph, routing, state, and conversation memory. The routes in §3 have known shapes (parallel, chained either direction, retry loop), which a graph expresses directly. It's also named in the target job listing.
- **Rule:** every node is the owner's own code calling the model SDK, DuckDB, and Qdrant directly, with no LangChain chains, retrievers, or agent wrappers. "LangGraph decides which step runs next; every step is my code."
- Explicit routes also make routing accuracy directly measurable.

### Streaming: one Server-Sent Events stream per question
- **SSE over a POST response** (chosen): the question goes up as a normal request, and typed events stream back on the same response. Follow-ups are new requests. Stop = cancel the request. This is the same pattern the Claude and OpenAI APIs use. The browser's `EventSource` only supports GET, so the frontend reads the stream with `fetch()`.
- **WebSockets** (rejected): useful when the server pushes unrequested updates or the client sends mid-stream (multiplayer, live voice). Neither applies. They add reconnect logic, load-balancer and hosting config, no per-message HTTP status or auth headers, and are harder to test with `curl`.
- **Separate streams for steps and answer** (rejected): the browser would have to line them back up for no benefit.
- **Next.js + an AI streaming SDK** (rejected): adds a TypeScript layer between browser and agent, and the SDK's message format would hide the step events the UI is built around.

## 10. Build stages (from `proj.md`, with use-case mapping)

**Delivery approach (owner decision): small proof of concept first.** No hard launch date is set. But the first milestone is a thin version that works end to end and is **deployed publicly**:
- stats-only questions (use case 1)
- streamed answer, basic inspector showing the SQL step
- a minimal landing page

Everything below then adds depth to a working, deployed app, rather than leaving the frontend and deployment for last. The implementation plan must reflect this ordering.

**If time runs short, cut in this order:**
1. Weekly refresh (freeze on the initial snapshot).
2. Recorded replays (when the cap is hit, the demo simply pauses).
3. The inline audio player (clip cards link to the episode page instead).

Fact-check (4) and settle-a-debate (6) are **not** on the cut list; they're the showcase.

Each stage works on its own. Stages 1 and 2 can be exercised through the API or a simple CLI before the full frontend exists.

1. **Stats agent:** use cases 1, 8 (stats side), and 9 (name resolution).
2. **Podcast search:**
   - the refresh job's podcast stages (§8a)
   - use cases 2 and 7
   - clip citations and audio playback
3. **Combined agent and full experience:**
   - use cases 3–6 and 10
   - the rest of the screens in §5
   - demo protection (§7) and question logging (§7a)

## 11. Open items

**Owner to decide**
- Which 3–4 podcasts. They need public RSS feeds with audio URLs, and must pass the no-dynamic-ads check (§8).
- LLM, embedding, and reranker providers.
- The real daily spending cap (§7 starts at $5).

**Settled as calls during review**
- The timing and cost figures in the §5.2 mockup ("2.1s", "$0.004") are illustrative, not targets. **(call)** Latency and cost targets are set after the first eval baseline. The per-visitor limit and daily cap (§7) are then tuned to the measured cost per question.
- Using a cheaper model for sub-steps (routing, claim extraction) and a stronger one for the final answer is allowed, and is a natural experiment for the Eval results page.

**Left to the builder**
- Exact event field names and payload shapes (§6 defines the meaning).
- How conversation memory is stored, and for how long (at least as long as an interviewer's session).
- How visitors are identified for rate limiting.
- Visual styling, beyond the layouts in §5.
- How recorded runs are stored and replayed.
