from __future__ import annotations
import asyncio
import logging
import os
from typing import Dict

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
            await context.bot.send_message(
                chat_id=p.user_id,
                text=f"Игра в группе {chat_id}\nТема: {gs.current_topic.value}\n{gs.hand_str(p.user_id)}"
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
            await update.effective_message.reply_text(
                f"Группа {gs.chat_id}. Тема: {gs.current_topic.value if gs.current_topic else '—'}\n{gs.hand_str(update.effective_user.id)}"
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
        await context.bot.send_message(chat_id=uid, text=gs.hand_str(uid))
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
                await context.bot.send_message(chat_id=p.user_id, text=gs.hand_str(p.user_id))
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
        "/startgame — начать (3+ игроков)\n"
        "/hand — ваша рука (в личке)\n"
        "/play <i> <ранг> — положить карту по индексу и заявить ранг (A,K,Q,J,10..2)\n"
        "/accuse — обвинить предыдущего игрока (может только следующий по ходу)\n"
        "/status — текущее состояние\n"
        "/topic — текущая тема\n"
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
    # Отсекать лишние сообщения, но можно логировать при желании
    app.add_handler(MessageHandler(filters.ALL, lambda u, c: None))
    return app


if __name__ == "__main__":
    app = build_app()
    logger.info("Starting Liar's Deck bot...")
    app.run_polling(close_loop=False)