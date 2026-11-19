"""The SSE contract (functional spec §6). frontend/src/api/types.ts mirrors these exactly."""

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, Literal

StepKind = Literal["route", "resolve", "sql", "answer", "decline"]
StepStatus = Literal["started", "done", "failed"]


@dataclass
class StepEvent:
    type: ClassVar[str] = "step"
    id: str
    kind: StepKind
    status: StepStatus
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None


@dataclass
class TokenEvent:
    type: ClassVar[str] = "token"
    text: str


@dataclass
class SourceEvent:
    type: ClassVar[str] = "source"
    n: int
    kind: Literal["stat"]
    label: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool


@dataclass
class DoneEvent:
    type: ClassVar[str] = "done"
    ttft_ms: int | None
    total_ms: int
    cost_usd: float
    input_tokens: int
    output_tokens: int


@dataclass
class ErrorEvent:
    type: ClassVar[str] = "error"
    message: str


Event = StepEvent | TokenEvent | SourceEvent | DoneEvent | ErrorEvent


def to_payload(event: Event) -> dict[str, Any]:
    return asdict(event)
