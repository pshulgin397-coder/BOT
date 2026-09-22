"""
Telegram-бот: анализирует трендовые темы на YouTube в сегменте стриминга
и подсказывает идеи для видео.

Команды:
  /start   — приветствие и список команд
  /trends  — текущие трендовые видео (кэшируются на 30 минут, чтобы не жечь квоту API)
  /idea    — сгенерировать идеи для видео на основе последних трендов

Запуск:
  1. pip install -r requirements.txt
  2. Скопировать .env.example в .env и заполнить токены
  3. python bot.py
"""

import logging
import time
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from youtube_trends import fetch_trends, format_trends_message, DEFAULT_KEYWORDS
from idea_generator import generate_ideas

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DIGEST_CHAT_ID = os.getenv("DIGEST_CHAT_ID")
DIGEST_TIME = os.getenv("DIGEST_TIME", "10:00")

CACHE_TTL_SECONDS = 30 * 60  # не дёргать YouTube API чаще, чем раз в 30 минут

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_cache = {"videos": [], "fetched_at": 0}


def _get_trends(force: bool = False):
    now = time.time()
    if force or not _cache["videos"] or (now - _cache["fetched_at"] > CACHE_TTL_SECONDS):
        logger.info("Fetching fresh trends from YouTube API...")
        _cache["videos"] = fetch_trends(YOUTUBE_API_KEY, keywords=DEFAULT_KEYWORDS)
        _cache["fetched_at"] = now
    return _cache["videos"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я слежу за трендами в сегменте стриминга на YouTube.\n\n"
        "/trends — что сейчас хайповое и что набирает обороты\n"
        "/idea — готовые углы для видео на основе трендов"
    )


async def trends_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    try:
        videos = _get_trends()
    except Exception as e:
        logger.exception("Failed to fetch trends")
        await update.message.reply_text(f"Не получилось получить тренды: {e}")
        return

    message = format_trends_message(videos)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def idea_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    try:
        videos = _get_trends()
    except Exception as e:
        logger.exception("Failed to fetch trends")
        await update.message.reply_text(f"Не получилось получить тренды: {e}")
        return

    message = generate_ideas(videos)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def send_daily_digest(context: ContextTypes.DEFAULT_TYPE):
    if not DIGEST_CHAT_ID:
        return
    try:
        videos = _get_trends(force=True)
        message = format_trends_message(videos)
        await context.bot.send_message(
            chat_id=DIGEST_CHAT_ID,
            text="☀️ Утренняя сводка трендов\n\n" + message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        logger.exception("Failed to send daily digest")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан. Заполни .env по примеру .env.example")
    if not YOUTUBE_API_KEY:
        raise SystemExit("YOUTUBE_API_KEY не задан. Заполни .env по примеру .env.example")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("trends", trends_command))
    app.add_handler(CommandHandler("idea", idea_command))

    if DIGEST_CHAT_ID:
        hour, minute = map(int, DIGEST_TIME.split(":"))
        app.job_queue.run_daily(
            send_daily_digest,
            time=__import__("datetime").time(hour=hour, minute=minute),
        )
        logger.info(f"Daily digest scheduled at {DIGEST_TIME} for chat {DIGEST_CHAT_ID}")

    logger.info("Bot started. Polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
