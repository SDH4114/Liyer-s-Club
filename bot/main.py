from __future__ import annotations
import asyncio
import logging
import os
from typing import Dict
import secrets

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters
)

from liers.game import GameState
from liers.models import Rank

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("liers-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN не задан. Создайте .env на основе .env.example")


# Игры по chat_id
GAMES: Dict[int, GameState] = {}

# Последние сообщения с рукой в личке (user_id -> message_id)
LAST_HAND_MSG: Dict[int, int] = {}

async def _send_hand_dm(context: ContextTypes.DEFAULT_TYPE, uid: int, text: str):
    """Удаляет прошлое сообщение с рукой в личке и отправляет новое, сохраняя message_id."""
    # Сначала пробуем удалить прошлое сообщение (если было)
    prev_id = LAST_HAND_MSG.get(uid)
    if prev_id is not None:
        try:
            await context.bot.delete_message(chat_id=uid, message_id=prev_id)
        except Exception:
            pass  # игнорируем если нельзя удалить/нет доступа
    # Отправляем новое
    try:
        msg = await context.bot.send_message(chat_id=uid, text=text)
        LAST_HAND_MSG[uid] = msg.message_id
    except Exception:
        pass

# === Dealer mode (работает в личке с ботом) ===
class DealerSession:
    """Простая сессия дилера: имена игроков и их статус alive."""
    def __init__(self) -> None:
        self.players: dict[str, bool] = {}  # name -> alive
        self.revolvers: dict[str, int] = {}

    def reset_revolver(self, name: str | None = None) -> None:
        """Перезарядить барабан(ы). Если name передан — только для этого игрока, иначе для всех."""
        if name is None:
            for n in list(self.revolvers.keys()):
                self.revolvers[n] = 6
        else:
            if name in self.revolvers:
                self.revolvers[name] = 6

    def add(self, name: str) -> str:
        name = name.strip()
        if not (1 <= len(name) <= 24):
            raise ValueError("Имя должно быть 1..24 символа.")
        if name in self.players:
            return f"Игрок {name} уже в списке."
        if len(self.players) >= 6:
            raise ValueError("Максимум 6 игроков.")
        self.players[name] = True
        self.revolvers[name] = 6
        return f"Добавлен: {name}"

    def ensure_bounds(self) -> None:
        n = len(self.players)
        if n < 2:
            raise ValueError("Нужно минимум 2 игрока. Добавьте /dealer_add <имя>.")

    def list_text(self) -> str:
        if not self.players:
            return "Список пуст. Добавляйте игроков: /dealer_add <имя>"
        rows = []
        for i, (n, alive) in enumerate(self.players.items()):
            odds = self.revolvers.get(n, 6)
            extra = f" (шанс 1/{odds})" if alive else ""
            rows.append(f"{i+1}. {n} — {'Жив(а)' if alive else 'Выбыл(а)'}{extra}")
        return "Игроки:\n" + "\n".join(rows)

    def shoot(self, name: str) -> tuple[str, bool]:
        self.ensure_bounds()
        if name not in self.players:
            raise ValueError(f"Нет игрока с именем: {name}")
        if not self.players[name]:
            return (f"{name} уже выбыл.", False)

        # Получаем текущий шанс именно для этого игрока
        remaining = self.revolvers.get(name, 6)
        if remaining < 1:
            remaining = 1
        bullet = (secrets.randbelow(remaining) == 0)

        if bullet:
            self.players[name] = False
            self.reset_revolver(name)  # перезарядка только этого игрока
            msg = f"🔫 Бах! {name} не выжил."
            return (msg, True)
        else:
            remaining = max(1, remaining - 1)
            self.revolvers[name] = remaining
            hint = f"1/{remaining}" if remaining > 1 else "1/1"
            msg = f"🔫 Щелчок... {name} повезло! (следующий шанс {hint})"
            return (msg, False)

# Хранилище сессий дилера: по user_id (личка)
DEALERS: Dict[int, DealerSession] = {}

def _is_dm(update: Update) -> bool:
    chat = update.effective_chat
    return chat and chat.type == ChatType.PRIVATE

async def cmd_dealer_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_dm(update):
        return await update.effective_message.reply_text("Dealer доступен только в личке с ботом.")
    DEALERS[update.effective_user.id] = DealerSession()
    await update.effective_message.reply_text(
        "🎲 Dealer-режим создан.\n"
        "Добавляй игроков: /dealer_add <имя>\n"
        "Показать список: /dealer_list\n"
        "Сделать выстрел по игроку: /dealer_shoot <имя>\n"
        "Сбросить сессию: /dealer_reset\n"
        "Лимит: 2–6 игроков."
    )

async def cmd_dealer_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_dm(update):
        return await update.effective_message.reply_text("Добавлять игроков можно только в личке.")
    sess = DEALERS.setdefault(update.effective_user.id, DealerSession())
    if not context.args:
        return await update.effective_message.reply_text("Использование: /dealer_add <имя>")
    name = " ".join(context.args)
    try:
        msg = sess.add(name)
        await update.effective_message.reply_text(msg + "\n" + sess.list_text())
    except ValueError as e:
        await update.effective_message.reply_text(f"Нельзя: {e}")

async def cmd_dealer_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_dm(update):
        return await update.effective_message.reply_text("Список доступен в личке.")
    sess = DEALERS.setdefault(update.effective_user.id, DealerSession())
    await update.effective_message.reply_text(sess.list_text())

async def cmd_dealer_shoot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_dm(update):
        return await update.effective_message.reply_text("Стрелять можно только в личке (Dealer).")
    sess = DEALERS.setdefault(update.effective_user.id, DealerSession())
    if not context.args:
        return await update.effective_message.reply_text("Использование: /dealer_shoot <имя>")
    name = " ".join(context.args)
    try:
        text, died = sess.shoot(name)
        alive = [n for n, a in sess.players.items() if a]
        if len(alive) == 1:
            text += f"\n🏆 Победитель: {alive[0]}"
        elif len(alive) == 0:
            text += "\nВсе выбыли. /dealer_reset — начать заново."
        await update.effective_message.reply_text(text + "\n" + sess.list_text())
    except ValueError as e:
        await update.effective_message.reply_text(f"Нельзя: {e}")

async def cmd_dealer_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_dm(update):
        return await update.effective_message.reply_text("Сброс доступен в личке.")
    DEALERS[update.effective_user.id] = DealerSession()
    await update.effective_message.reply_text("Сессия сброшена. /dealer_add <имя> — добавляйте заново.")


def in_group(update: Update) -> bool:
    chat = update.effective_chat
    return chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Привет! Я Liar’s Deck бот.\n"
        "Добавьте меня в группу и используйте /newgame, /join, /startgame.\n"
        "В личке можно посмотреть руку: /hand"
    )


async def cmd_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_group(update):
        return await update.effective_message.reply_text("Создавать игру нужно в группе.")
    chat_id = update.effective_chat.id
    GAMES[chat_id] = GameState(chat_id=chat_id)
    await update.effective_message.reply_text("Создано новое лобби. Игроки: используйте /join. Организатор: /startgame.")


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_group(update):
        return await update.effective_message.reply_text("Присоединяться к игре нужно в группе.")
    chat_id = update.effective_chat.id
    gs = GAMES.get(chat_id)
    if not gs:
        return await update.effective_message.reply_text("Сначала создайте игру: /newgame")
    user = update.effective_user
    gs.add_player(user.id, user.username or user.full_name)
    await update.effective_message.reply_text(f"@{user.username or user.full_name} присоединился.\n{gs.status()}")


async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_group(update):
        return await update.effective_message.reply_text("Стартовать игру нужно в группе.")
    chat_id = update.effective_chat.id
    gs = GAMES.get(chat_id)
    if not gs:
        return await update.effective_message.reply_text("Сначала /newgame и /join.")
    try:
        gs.start()
    except ValueError as e:
        return await update.effective_message.reply_text(f"Нельзя начать: {e}")

    # Разослать руки в личку
    for p in gs.players:
        try:
            await _send_hand_dm(
                context,
                p.user_id,
                f"Игра в группе {chat_id}\nТема: {gs.current_topic.value}\n{gs.hand_str(p.user_id)}",
            )
        except Exception:
            pass  # если не писал боту — Telegram не даст написать первым

    await update.effective_message.reply_text(
        f"Игра началась! Тема: {gs.current_topic.value}\nПервый ход: @{gs.current_player().username}\n"
        "Ход: /play <индекс_карты> <заявленный_ранг>, например: /play 0 K\n"
        "Следующий после хода может сказать /accuse (обвинить)."
    )


async def cmd_hand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # В личке: показать руку. В группе: подсказка.
    if in_group(update):
        return await update.effective_message.reply_text("Напишите мне в личку /hand — пришлю вашу руку.")
    # в личке — нужен chat_id игры. Храним по последней?
    # MVP: покажем руки во всех текущих играх, где вы участник (их обычно мало).
    found = False
    for gs in GAMES.values():
        if any(p.user_id == update.effective_user.id for p in gs.players):
            found = True
            await _send_hand_dm(
                context,
                update.effective_user.id,
                f"Группа {gs.chat_id}. Тема: {gs.current_topic.value if gs.current_topic else '—'}\n{gs.hand_str(update.effective_user.id)}",
            )
    if not found:
        await update.effective_message.reply_text("Вы пока ни в одной игре. Присоединитесь в группе через /join.")


async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_group(update):
        return await update.effective_message.reply_text("Играть нужно в группе.")
    chat_id = update.effective_chat.id
    gs = GAMES.get(chat_id)
    if not gs or not gs.started:
        return await update.effective_message.reply_text("Игра не идёт. /newgame → /join → /startgame.")
    args = context.args
    if len(args) != 2:
        return await update.effective_message.reply_text("Использование: /play <индекс_карты> <ранг>. Пример: /play 0 K")
    try:
        idx = int(args[0])
        claimed = Rank.from_str(args[1])
    except Exception as e:
        return await update.effective_message.reply_text(f"Ошибка: {e}")

    uid = update.effective_user.id
    try:
        lp = gs.play(uid, idx, claimed)
    except ValueError as e:
        return await update.effective_message.reply_text(f"Нельзя: {e}")

    await update.effective_message.reply_text(
        f"@{update.effective_user.username or update.effective_user.full_name} положил карту лицом вниз и заявил {claimed.value}.\n"
        f"Обвинить может следующий игрок: @{gs.current_player().username}. Используйте /accuse"
    )
    # Попробуем прислать руку сыгравшему
    try:
        await _send_hand_dm(context, uid, gs.hand_str(uid))
    except Exception:
        pass


async def cmd_accuse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_group(update):
        return await update.effective_message.reply_text("Обвинять нужно в группе.")
    chat_id = update.effective_chat.id
    gs = GAMES.get(chat_id)
    if not gs or not gs.started:
        return await update.effective_message.reply_text("Игра не идёт.")
    uid = update.effective_user.id
    try:
        msg, shot, died_uid = gs.accuse(uid)
    except ValueError as e:
        return await update.effective_message.reply_text(f"Нельзя: {e}")

    await update.effective_message.reply_text(msg)
    # обновим руки всем, кого это затронуло
    affected = set([uid])
    if died_uid:
        affected.add(died_uid)
    if gs.started:
        # также последнему, кто клал карту
        # (после accuse last_play уже None — не узнаем, кого именно; пропустим)
        pass
    for p in gs.players:
        if p.user_id in affected:
            try:
                await _send_hand_dm(context, p.user_id, gs.hand_str(p.user_id))
            except Exception:
                pass


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_group(update):
        return await update.effective_message.reply_text("Статус лучше смотреть в группе.")
    gs = GAMES.get(update.effective_chat.id)
    if not gs:
        return await update.effective_message.reply_text("Нет активной игры. /newgame")
    await update.effective_message.reply_text(gs.status())


async def cmd_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not in_group(update):
        return await update.effective_message.reply_text("Останавливать игру нужно в группе.")
    chat_id = update.effective_chat.id
    gs = GAMES.get(chat_id)
    if not gs:
        return await update.effective_message.reply_text("Нет активной игры.")
    msg = gs.stop()
    await update.effective_message.reply_text(msg)
    if not in_group(update):
        return await update.effective_message.reply_text("Тема актуальна для групповой игры.")
    gs = GAMES.get(update.effective_chat.id)
    if not gs or not gs.current_topic:
        return await update.effective_message.reply_text("Тема пока не установлена.")
    await update.effective_message.reply_text(f"Текущая тема: {gs.current_topic.value}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "/newgame — создать лобби в группе\n"
        "/join — присоединиться\n"
        "/startgame — начать (2+ игроков)\n"
        "/hand — ваша рука (в личке)\n"
        "/play <i> <ранг> — положить карту по индексу и заявить ранг (K,Q,J,TR)\n"
        "/accuse — обвинить предыдущего игрока (может только следующий по ходу)\n"
        "/status — текущее состояние\n"
        "/topic — текущая тема\n"
        "\nDealer (в личке):\n"
        "/dealer_new — создать Dealer\n"
        "/dealer_add <имя> — добавить игрока\n"
        "/dealer_list — показать список\n"
        "/dealer_shoot <имя> — выстрел по игроку\n"
        "/dealer_reset — очистить список\n"
    )


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("newgame", cmd_newgame))
    app.add_handler(CommandHandler("join", cmd_join))
    app.add_handler(CommandHandler("startgame", cmd_startgame))
    app.add_handler(CommandHandler("hand", cmd_hand))
    app.add_handler(CommandHandler("play", cmd_play))
    app.add_handler(CommandHandler("accuse", cmd_accuse))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("topic", cmd_topic))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("dealer_new", cmd_dealer_new))
    app.add_handler(CommandHandler("dealer_add", cmd_dealer_add))
    app.add_handler(CommandHandler("dealer_list", cmd_dealer_list))
    app.add_handler(CommandHandler("dealer_shoot", cmd_dealer_shoot))
    app.add_handler(CommandHandler("dealer_reset", cmd_dealer_reset))
    # Отсекать лишние сообщения, но можно логировать при желании
    app.add_handler(MessageHandler(filters.ALL, lambda u, c: None))
    return app


if __name__ == "__main__":
    app = build_app()
    logger.info("Starting Liar's Deck bot...")
    app.run_polling(close_loop=False)