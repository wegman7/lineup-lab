"""Turn a name as typed ("CMC", "Puka", "McCafrey") into a player in the stats data.

Deterministic on purpose: testable, explainable, free, and shown in the trace.
Stages run in order and the first one with any match wins:
alias -> exact full name -> first or last name -> fuzzy full name.
"""

import difflib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from lineup_lab.stats.db import PlayerRow, StatsDB

log = logging.getLogger(__name__)

ALIASES_PATH = Path(__file__).with_name("aliases.yaml")
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
DOMINANCE = 3.0  # top candidate needs this many times the runner-up's points to be assumed
MAX_CANDIDATES = 5

Status = Literal["resolved", "assumed", "ambiguous", "unknown"]


@dataclass
class Resolution:
    text: str
    status: Status
    player: PlayerRow | None
    candidates: list[PlayerRow] = field(default_factory=list)


def normalize(name: str) -> str:
    name = name.lower().replace("-", " ")
    name = re.sub(r"[^\w\s]", "", name)
    return " ".join(t for t in name.split() if t not in SUFFIXES)


class PlayerResolver:
    def __init__(self, players: list[PlayerRow], aliases: dict[str, str]):
        self._by_full: dict[str, list[PlayerRow]] = defaultdict(list)
        self._by_part: dict[str, list[PlayerRow]] = defaultdict(list)
        for p in players:
            if not p.name:
                continue
            full = normalize(p.name)
            self._by_full[full].append(p)
            tokens = full.split()
            parts = {tokens[0], tokens[-1], " ".join(tokens[1:])} if len(tokens) > 1 else set()
            for part in parts:
                self._by_part[part].append(p)
        self._aliases: dict[str, str] = {}
        for alias, target in aliases.items():
            if normalize(target) in self._by_full:
                self._aliases[normalize(alias)] = normalize(target)
            else:
                log.warning("alias %r -> %r: player not in loaded data, dropped", alias, target)

    @classmethod
    def from_db(cls, db: StatsDB) -> "PlayerResolver":
        aliases = yaml.safe_load(ALIASES_PATH.read_text()) or {}
        return cls(db.players(), {str(k): str(v) for k, v in aliases.items()})

    def resolve(self, text: str) -> Resolution:
        q = normalize(text)
        matches = self._match(q)
        if not matches:
            return Resolution(text, "unknown", None, [])
        ranked = sorted({p.player_id: p for p in matches}.values(), key=lambda p: -p.ppr_points)
        candidates = ranked[:MAX_CANDIDATES]
        if len(ranked) == 1:
            return Resolution(text, "resolved", ranked[0], candidates)
        if ranked[0].ppr_points >= DOMINANCE * max(ranked[1].ppr_points, 0):
            return Resolution(text, "assumed", ranked[0], candidates)
        return Resolution(text, "ambiguous", None, candidates)

    def _match(self, q: str) -> list[PlayerRow]:
        if q in self._aliases:
            return self._by_full[self._aliases[q]]
        if q in self._by_full:
            return self._by_full[q]
        if q in self._by_part:
            return self._by_part[q]
        close = difflib.get_close_matches(q, self._by_full.keys(), n=MAX_CANDIDATES, cutoff=0.85)
        return [p for name in close for p in self._by_full[name]]
