from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Tuple


class Rank(str, Enum):
    A = "A"
    K = "K"
    Q = "Q"
    J = "J"
    T10 = "10"
    R9 = "9"
    R8 = "8"
    R7 = "7"
    R6 = "6"
    R5 = "5"
    R4 = "4"
    R3 = "3"
    R2 = "2"

    @staticmethod
    def all_ranks() -> List["Rank"]:
        return [
            Rank.A, Rank.K, Rank.Q, Rank.J, Rank.T10, Rank.R9, Rank.R8, Rank.R7,
            Rank.R6, Rank.R5, Rank.R4, Rank.R3, Rank.R2
        ]

    @staticmethod
    def from_str(s: str) -> "Rank":
        s = s.upper().strip()
        mapping = {"10": Rank.T10, "A": Rank.A, "K": Rank.K, "Q": Rank.Q, "J": Rank.J,
                   "9": Rank.R9, "8": Rank.R8, "7": Rank.R7, "6": Rank.R6, "5": Rank.R5,
                   "4": Rank.R4, "3": Rank.R3, "2": Rank.R2}
        if s not in mapping:
            raise ValueError("Неверный ранг. Разрешено: A,K,Q,J,10,9,8,7,6,5,4,3,2")
        return mapping[s]


@dataclass(frozen=True)
class Card:
    rank: Rank


@dataclass
class Player:
    user_id: int
    username: str  # может быть None → подставим имя/ID