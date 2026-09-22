"""
Telegram-бот: анализирует трендовые темы на YouTube (русский сегмент стриминга)
и подсказывает идеи для видео.

Команды:
  /start   — приветствие и список команд
  /trends  — большая таблица трендов (100+ позиций), присылается файлом (HTML, с анимацией)
  /idea    — короткие идеи в чат + HTML-отчёт с анализом подачи (форматы, вовлечённость, паттерны)

Запуск:
  1. pip install -r requirements.txt
  2. Скопировать .env.example в .env и заполнить токены
  3. python bot.py
"""

import io
import logging
import re
import sys
import time
import os

from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.constants import ParseMode
from telegram.error import InvalidToken, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from googleapiclient.errors import HttpError

from youtube_trends import fetch_trends, format_trends_message, DEFAULT_KEYWORDS
from idea_generator import generate_ideas, build_style_report_html
from report_builder import build_trends_html

load_dotenv()

# .strip() на случай, если при копировании в переменные окружения (Railway/Render/.env)
# зацепился лишний пробел или перенос строки — частая причина InvalidToken
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
YOUTUBE_API_KEY = (os.getenv("YOUTUBE_API_KEY") or "").strip()
DIGEST_CHAT_ID = (os.getenv("DIGEST_CHAT_ID") or "").strip()
DIGEST_TIME = (os.getenv("DIGEST_TIME") or "10:00").strip()

CACHE_TTL_SECONDS = 30 * 60  # не дёргать YouTube API чаще, чем раз в 30 минут

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_cache = {"videos": [], "fetched_at": 0}


def _friendly_youtube_error(e: Exception) -> str:
    if isinstance(e, HttpError):
        status = e.resp.status if hasattr(e, "resp") else None
        if status == 400:
            return "YouTube API отклонил запрос (400) — проверь, что YOUTUBE_API_KEY скопирован верно."
        if status == 403:
            return (
                "YouTube API вернул 403 — либо ключ неверный, либо YouTube Data API v3 не включён "
                "в Google Cloud Console для этого проекта, либо кончилась дневная квота (10 000 units)."
            )
        return f"YouTube API вернул ошибку {status}: {e}"
    return str(e)


def _get_trends(force: bool = False):
    now = time.time()
    if force or not _cache["videos"] or (now - _cache["fetched_at"] > CACHE_TTL_SECONDS):
        logger.info("Fetching fresh trends from YouTube API...")
        _cache["videos"] = fetch_trends(YOUTUBE_API_KEY, keywords=DEFAULT_KEYWORDS)
        _cache["fetched_at"] = now
    return _cache["videos"]


async def _send_html_report(message, html_content: str, filename: str, caption: str = None):
    buf = io.BytesIO(html_content.encode("utf-8"))
    buf.name = filename
    await message.reply_document(
        document=InputFile(buf, filename=filename),
        caption=caption,
        parse_mode=ParseMode.HTML if caption else None,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Слежу за трендами русского сегмента YouTube в стриминге.\n\n"
        "/trends — большая таблица (100+ видео) файлом: что уже хайповое, что растёт,\n"
        "          и отдельно — маленькие каналы с большими просмотрами\n"
        "/idea — идеи для видео + разбор подачи (форматы, вовлечённость, паттерны заголовков)"
    )


async def trends_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("upload_document")
    try:
        videos = _get_trends()
    except Exception as e:
        logger.exception("Failed to fetch trends")
        await update.message.reply_text(f"Не получилось получить тренды.\n{_friendly_youtube_error(e)}")
        return

    if not videos:
        await update.message.reply_text(format_trends_message(videos))
        return

    caption = format_trends_message(videos)
    html_report = build_trends_html(videos)
    await _send_html_report(update.message, html_report, "trends.html", caption=caption)


async def idea_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    try:
        videos = _get_trends()
    except Exception as e:
        logger.exception("Failed to fetch trends")
        await update.message.reply_text(f"Не получилось получить тренды.\n{_friendly_youtube_error(e)}")
        return

    message = generate_ideas(videos)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if videos:
        await update.message.chat.send_action("upload_document")
        style_report = build_style_report_html(videos)
        await _send_html_report(update.message, style_report, "style_analysis.html")


async def send_daily_digest(context: ContextTypes.DEFAULT_TYPE):
    if not DIGEST_CHAT_ID:
        return
    try:
        videos = _get_trends(force=True)
        caption = "☀️ Утренняя сводка трендов\n\n" + format_trends_message(videos)
        if not videos:
            await context.bot.send_message(chat_id=DIGEST_CHAT_ID, text=caption)
            return
        html_report = build_trends_html(videos)
        buf = io.BytesIO(html_report.encode("utf-8"))
        buf.name = "trends.html"
        await context.bot.send_document(
            chat_id=DIGEST_CHAT_ID,
            document=InputFile(buf, filename="trends.html"),
            caption=caption,
        )
    except Exception:
        logger.exception("Failed to send daily digest")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Ловит любые необработанные ошибки в хендлерах, чтобы бот не падал целиком."""
    logger.error("Unhandled exception while processing update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Что-то пошло не так при обработке команды. Попробуй ещё раз через минуту."
            )
        except TelegramError:
            pass


def main():
    if not TELEGRAM_BOT_TOKEN:
        sys.exit(
            "❌ TELEGRAM_BOT_TOKEN не задан.\n"
            "Заполни его в .env (локально) или в Variables (Railway/Render)."
        )
    if not re.match(r"^\d+:[\w-]{30,}$", TELEGRAM_BOT_TOKEN):
        sys.exit(
            "❌ TELEGRAM_BOT_TOKEN выглядит некорректно (не похож на формат '123456789:AA...').\n"
            "Частые причины: лишний пробел/перенос строки при вставке, токен скопирован не полностью,\n"
            "или вставлен ключ YouTube вместо токена бота.\n"
            "Проверь значение и, если сомневаешься — перевыпусти токен через @BotFather → /mybots → API Token → Revoke current token."
        )
    if not YOUTUBE_API_KEY:
        sys.exit(
            "❌ YOUTUBE_API_KEY не задан.\n"
            "Заполни его в .env (локально) или в Variables (Railway/Render)."
        )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("trends", trends_command))
    app.add_handler(CommandHandler("idea", idea_command))
    app.add_error_handler(error_handler)

    if DIGEST_CHAT_ID:
        try:
            hour, minute = map(int, DIGEST_TIME.split(":"))
            app.job_queue.run_daily(
                send_daily_digest,
                time=__import__("datetime").time(hour=hour, minute=minute),
            )
            logger.info(f"Daily digest scheduled at {DIGEST_TIME} for chat {DIGEST_CHAT_ID}")
        except ValueError:
            logger.warning(
                f"DIGEST_TIME='{DIGEST_TIME}' некорректен (нужен формат ЧЧ:ММ, например 10:00). "
                "Авторассылка отключена, но бот всё равно запустится и команды будут работать."
            )

    logger.info("Bot started. Polling...")
    try:
        app.run_polling()
    except InvalidToken:
        sys.exit(
            "❌ Telegram отклонил токен бота (InvalidToken).\n"
            "Токен не совпадает с тем, что выдал @BotFather, или был отозван.\n"
            "Перевыпусти его: @BotFather → /mybots → выбери бота → API Token → Revoke current token,\n"
            "и вставь новое значение в переменные окружения."
        )
    except TelegramError as e:
        sys.exit(f"❌ Ошибка Telegram API при запуске: {e}")


if __name__ == "__main__":
    main()
