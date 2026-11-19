import operator
from typing import Annotated, Any, TypedDict

from lineup_lab.llm.client import CallStats
from lineup_lab.players.resolver import Resolution
from lineup_lab.stats.db import SqlResult


class SqlAttempt(TypedDict):
    sql: str
    error: str | None


class AgentState(TypedDict, total=False):
    question: str
    route: str
    route_reason: str
    mentions: list[str]
    resolutions: list[Resolution]
    draft: dict[str, Any]  # {"sql", "label"} from the latest gen_sql
    sql_attempts: Annotated[list[SqlAttempt], operator.add]
    result: SqlResult | None
    result_label: str
    answer: str
    calls: Annotated[list[CallStats], operator.add]
