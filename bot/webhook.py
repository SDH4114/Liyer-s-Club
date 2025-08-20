# bot/webhook.py
from __future__ import annotations
import os
import logging
from telegram.ext import Application
from bot.main import build_app  # переиспользуем все хендлеры и логику

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("liers-bot-webhook")

BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("WEBHOOK_PUBLIC_URL")  # например: https://liers-deck-bot-web.onrender.com
SECRET_PATH = os.getenv("WEBHOOK_SECRET") or f"hook-{os.urandom(4).hex()}"
PORT = int(os.getenv("PORT", "10000"))  # Render прокидывает PORT в env

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN не задан (env).")
if not PUBLIC_URL:
    raise SystemExit("WEBHOOK_PUBLIC_URL не задан (env). Пример: https://<service>.onrender.com")

if __name__ == "__main__":
    app: Application = build_app()

    webhook_url = f"{PUBLIC_URL.rstrip('/')}/{SECRET_PATH}"
    logger.info("Starting webhook server on port %s, path '/%s'", PORT, SECRET_PATH)
    logger.info("Registering webhook URL: %s", webhook_url)

    # Поднимет aiohttp-сервер и зарегистрирует вебхук в Telegram
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=SECRET_PATH,
        webhook_url=webhook_url,
        # drop_pending_updates=True,  # включи при необходимости
    )

#webhook_url