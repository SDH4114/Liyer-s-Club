from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import secrets
from .models import Rank, Card, Player


def _fresh_deck() -> List[Card]:
    # 4 масти * 13 рангов — масти не важны, только ранги (52 карты)
    return [Card(rank=r) for r in Rank.all_ranks() for _ in range(4)]


@dataclass
class LastPlay:
    player_id: int
    actual_rank: Rank
    claimed_rank: Rank


@dataclass
class GameState:
    chat_id: int
    players: List[Player] = field(default_factory=list)
    started: bool = False
    deck: List[Card] = field(default_factory=_fresh_deck)
    hands: Dict[int, List[Card]] = field(default_factory=dict)
    current_topic: Optional[Rank] = None
    current_idx: int = 0  # индекс в self.players
    last_play: Optional[LastPlay] = None
    alive: Dict[int, bool] = field(default_factory=dict)

    def reset(self):
        self.started = False
        self.deck = _fresh_deck()
        self.hands.clear()
        self.current_topic = None
        self.current_idx = 0
        self.last_play = None
        self.alive = {p.user_id: True for p in self.players}

    # --- Лобби ---
    def add_player(self, uid: int, username: str):
        if any(p.user_id == uid for p in self.players):
            return
        self.players.append(Player(uid, username or str(uid)))
        self.alive[uid] = True

    def remove_dead(self):
        self.players = [p for p in self.players if self.alive.get(p.user_id, False)]
        if self.current_idx >= len(self.players):
            self.current_idx = 0

    # --- Раздача и старт ---
    def start(self):
        if self.started:
            raise ValueError("Игра уже начата.")
        if len(self.players) < 3:
            raise ValueError("Нужно минимум 3 игрока.")
        self.reset()
        # Перетасовка через secrets (криптоустойчивый рандом)
        deck = self.deck
        for i in range(len(deck) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            deck[i], deck[j] = deck[j], deck[i]
        # Раздача по 5 карт
        for p in self.players:
            self.hands[p.user_id] = [self.deck.pop() for _ in range(5)]
        # Тема
        self.current_topic = secrets.choice(Rank.all_ranks())
        # Стартовый игрок
        self.current_idx = secrets.randbelow(len(self.players))
        self.started = True
        self.last_play = None

    def draw_if_possible(self, uid: int):
        # Добор при пустой руке
        if not self.hands[uid] and self.deck:
            # если колода кончилась — новая сдача
            to_draw = min(5, len(self.deck))
            self.hands[uid] = [self.deck.pop() for _ in range(to_draw)]
            # при новой фазе добора можно обновить тему
            if self.current_topic is None:
                self.current_topic = secrets.choice(Rank.all_ranks())

    # --- Ход и обвинение ---
    def current_player(self) -> Player:
        return self.players[self.current_idx]

    def play(self, uid: int, hand_index: int, claimed_rank: Rank) -> LastPlay:
        if not self.started:
            raise ValueError("Игра не начата.")
        if uid != self.current_player().user_id:
            raise ValueError("Сейчас не ваш ход.")
        if self.current_topic is None:
            raise ValueError("Тема не задана.")
        hand = self.hands.get(uid, [])
        if hand_index < 0 or hand_index >= len(hand):
            raise ValueError("Неверный индекс карты.")
        actual_card = hand.pop(hand_index)
        self.last_play = LastPlay(player_id=uid, actual_rank=actual_card.rank, claimed_rank=claimed_rank)
        # Переход хода к следующему живому
        self.current_idx = self._next_alive_idx(self.current_idx)
        # добор при необходимости
        self.draw_if_possible(uid)
        return self.last_play

    def _next_alive_idx(self, idx: int) -> int:
        n = len(self.players)
        for _ in range(n):
            idx = (idx + 1) % n
            pid = self.players[idx].user_id
            if self.alive.get(pid, False):
                return idx
        return idx  # если остался один, вернём как есть

    def accuse(self, accuser_uid: int) -> Tuple[str, bool, Optional[int]]:
        """
        Возвращает: (сообщение, выстрел_случился, погибший_uid|None)
        """
        if not self.started:
            raise ValueError("Игра не начата.")
        if self.last_play is None:
            raise ValueError("Нечего оспаривать.")
        # обвинять может только текущий по очереди (следующий после игрока, который уже походил)
        if accuser_uid != self.current_player().user_id:
            raise ValueError("Обвинять может только следующий игрок по очереди.")

        lp = self.last_play
        liar_caught = (lp.actual_rank != lp.claimed_rank)
        punished_uid = lp.player_id if liar_caught else accuser_uid

        # Русская рулетка: шанс 1/6
        bullet = secrets.randbelow(6) == 0
        died_uid: Optional[int] = None
        if bullet:
            self.alive[punished_uid] = False
            died_uid = punished_uid
            self.remove_dead()

        # После обвинения «вскрылись» — сбрасываем last_play
        self.last_play = None

        # Проверка конца игры
        alive_players = [p for p in self.players if self.alive.get(p.user_id, False)]
        winner_text = ""
        if len(alive_players) == 1:
            winner = alive_players[0]
            self.started = False
            winner_text = f"\n🏆 Победитель: @{winner.username}!"

        if liar_caught:
            msg = f"Лжец пойман! @{self._name(lp.player_id)} положил {lp.actual_rank}, а заявил {lp.claimed_rank}."
        else:
            msg = f"Обвинение провалилось! @{self._name(lp.player_id)} был честен: {lp.actual_rank}."

        if bullet:
            msg += f"\n🔫 Русская рулетка: @{self._name(punished_uid)} не выжил."
        else:
            msg += f"\n🔫 Русская рулетка: щелчок... повезло @{self._name(punished_uid)}!"

        msg += winner_text
        return msg, bullet, died_uid

    def _name(self, uid: int) -> str:
        for p in self.players:
            if p.user_id == uid:
                return p.username
        return str(uid)

    def status(self) -> str:
        if not self.players:
            return "Лобби пустое. Используйте /join."
        alive_marks = {uid: ("🟢" if self.alive.get(uid, False) else "⚫️") for uid in self.alive}
        order = " → ".join([f"@{p.username}{alive_marks.get(p.user_id,'')}" for p in self.players])
        cur = self.current_player().username if self.started else "—"
        topic = self.current_topic.value if self.current_topic else "—"
        pending = ""
        if self.last_play:
            pending = f"\nПоследний ход: @{self._name(self.last_play.player_id)} заявил {self.last_play.claimed_rank} (карта скрыта)."
        return f"Игроки: {order}\nТема: {topic}\nХод: @{cur}{pending}"

    def hand_str(self, uid: int) -> str:
        cards = self.hands.get(uid, [])
        if not cards:
            return "Рука пуста."
        return "Ваша рука:\n" + "\n".join([f"{i}: {c.rank}" for i, c in enumerate(cards)])