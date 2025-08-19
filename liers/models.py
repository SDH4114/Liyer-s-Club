from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Tuple


class Rank(str, Enum):
    K = "K"      # Король
    Q = "Q"      # Королева
    J = "J"      # Валет
    TR = "TR"    # Козырь (особая карта)

    @staticmethod
    def all_ranks() -> List["Rank"]:
        # Полный список карт в колоде: K, Q, J, TR (козырь)
        return [Rank.K, Rank.Q, Rank.J, Rank.TR]

    @staticmethod
    def from_str(s: str) -> "Rank":
        s = s.upper().strip()
        mapping = {"K": Rank.K, "Q": Rank.Q, "J": Rank.J, "TR": Rank.TR, "T": Rank.TR}
        if s not in mapping:
            raise ValueError("Неверный ранг. Разрешено: K,Q,J,TR (козырь)")
        return mapping[s]


@dataclass(frozen=True)
class Card:
    rank: Rank


@dataclass
class Player:
    user_id: int
    username: str  # может быть None → подставим имя/ID