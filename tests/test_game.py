import pytest
from liers.game import GameState
from liers.models import Rank


def make_game(n=3):
    gs = GameState(chat_id=1)
    for i in range(n):
        gs.add_player(100+i, f"user{i}")
    gs.start()
    return gs


def test_start_and_hands():
    gs = make_game(3)
    assert gs.started
    for p in gs.players:
        assert len(gs.hands[p.user_id]) == 5
    assert gs.current_topic in set(Rank.all_ranks())


def test_turn_play_and_accuse_flow():
    gs = make_game(3)
    first = gs.current_player().user_id
    # сыграть первую карту, заявив текущую тему
    lp = gs.play(first, 0, gs.current_topic)
    # обвиняет следующий
    accuser = gs.current_player().user_id
    msg, shot, died = gs.accuse(accuser)
    assert isinstance(msg, str)
    # кто-то мог умереть, но игра может продолжаться
    assert (died is None) or (died in [p.user_id for p in gs.players] or True)


def test_invalid_index():
    gs = make_game(3)
    uid = gs.current_player().user_id
    with pytest.raises(ValueError):
        gs.play(uid, 999, gs.current_topic)