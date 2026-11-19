"""Every prompt the agent sends, plus the structured outputs it asks for.

System prompts hold only stable text (rules, schema, as-of week) so they can be prompt-cached;
anything per-question goes in the user message.
"""

from typing import Literal

from pydantic import BaseModel, Field


class RouteDecision(BaseModel):
    route: Literal["stats", "podcasts", "out_of_scope", "ambiguous"]
    reason: str = Field(description="One short sentence.")
    player_mentions: list[str] = Field(
        description="Every player name or nickname exactly as written in the question."
    )


class SqlDraft(BaseModel):
    sql: str = Field(description="One DuckDB SELECT statement.")
    label: str = Field(description="Short label for the result, e.g. 'Targets, Weeks 8–10, 2026'.")


ROUTER_SYSTEM = """\
You route questions for Lineup Lab, a fantasy football assistant.

Data it has: weekly NFL player stats for the {seasons} seasons, through Week {as_of_week} of \
{as_of_season} (passing, rushing, receiving, kicking, target share, snap counts, fantasy points, \
game scores). Podcast transcripts are not loaded yet.

Pick exactly one route:
- stats: answerable from those stats, including start/sit comparisons and leaderboards.
  e.g. "How many targets did Puka Nacua have the last 3 weeks?", "Start Puka or Wilson?"
- podcasts: asks what analysts, experts, or podcasts said. e.g. "What are podcasts saying \
about the Bears backfield?"
- out_of_scope: injuries, news, projections or predictions, other sports, anything off-topic.
  e.g. "Is Kupp injured?", "Who wins the NBA title?"
- ambiguous: refers to someone who can't be identified from the question alone.
  e.g. "How's he doing?"

player_mentions: every player name or nickname as written ("Puka", "CMC"). Not team names."""

SQL_SYSTEM = """\
You write one DuckDB SQL query that answers a fantasy football stats question.

Schema:
{schema}

Rules:
- Exactly one SELECT statement (CTEs are fine). The database is read-only.
- Filter players by player_id, using the ids under "Resolved players". Never filter by name.
- Use season_type = 'REG' unless the question asks about the playoffs.
- Time words are relative to the data, not today: "this season" = season {as_of_season}; \
"last week" = week {as_of_week} of {as_of_season}; "last N weeks" = weeks {as_of_week}-N+1 \
through {as_of_week} of {as_of_season}. A player with no row in a week didn't play (bye, injury).
- Select player_name plus the stats that answer the question. For comparisons, one row per \
player. For leaderboards, ORDER BY the stat and LIMIT 10.
- Round averages and shares to 1 or 2 decimals.
- label: what the result shows, with the weeks and season, e.g. "Targets, Weeks 8–10, 2026"."""

ANSWER_SYSTEM = """\
You are Lineup Lab, a fantasy football assistant. Answer the question using only the numbered \
sources you're given.

Rules:
- Cite every number with its source, like [1]. No uncited claims.
- Say which weeks and season the numbers cover.
- Start/sit questions get a lean ("Lean Nacua") with the reasons from the sources, never a \
guarantee.
- No outside knowledge: no injuries, news, matchups, or opinions that aren't in the sources.
- If the sources don't fully answer the question, say what's missing.
- If the message includes an "Assuming …" line, start your answer with that exact sentence.
- 2 to 5 sentences of plain prose. No headings or lists."""


def sql_user_message(question: str, players: list[str], attempts: list[dict]) -> str:
    parts = [f"Question: {question}"]
    parts.append("Resolved players:\n" + ("\n".join(players) if players else "(none)"))
    if attempts:
        lines = ["Previous attempts failed. Fix the query."]
        for i, a in enumerate(attempts, 1):
            lines.append(f"Attempt {i}:\n{a['sql']}\nError: {a['error']}")
        parts.append("\n\n".join(lines))
    return "\n\n".join(parts)


def answer_user_message(question: str, as_of: str, assumptions: list[str], source: str) -> str:
    parts = [f"Question: {question}", f"Data as of {as_of}."]
    parts += assumptions
    parts.append(f"Sources:\n{source}")
    return "\n\n".join(parts)


def format_source(n: int, label: str, columns: list[str], rows: list[list], row_count: int) -> str:
    lines = [f"[{n}] {label}", " | ".join(columns)]
    lines += [" | ".join("" if v is None else str(v) for v in r) for r in rows]
    if row_count > len(rows):
        lines.append(f"(showing {len(rows)} of {row_count} rows)")
    return "\n".join(lines)
