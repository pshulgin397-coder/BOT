"""
Telegram-бот: анализирует твич-стримеров русского сегмента YouTube, следит за ростом
каналов, присылает регулярные "пульс"-уведомления и профессиональный ИИ-анализ.

Команды:
  /start    — приветствие, показывает меню кнопок
  /trends   — большая таблица трендов файлом (превью, аватары, hero-карточки топ-видео)
  /idea     — идеи для видео + HTML-отчёт с анализом подачи
  /analysis — отдельный текстовый разбор от ИИ-аналитика (или шаблонный без ключа)
  /breakout — каналы с наибольшим ростом подписчиков с начала отслеживания
  /notify   — вкл/выкл регулярные уведомления о движениях в трендах (раз в 1-2ч)

Запуск:
  1. pip install -r requirements.txt
  2. Скопировать .env.example в .env и заполнить токены
  3. python bot.py
"""

import datetime
import io
import logging
import re
import sys
import time
import os

from dotenv import load_dotenv
from telegram import (
    Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.constants import ParseMode
from telegram.error import InvalidToken, TelegramError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters,
)

from googleapiclient.errors import HttpError

from youtube_trends import fetch_trends, format_trends_message, DEFAULT_KEYWORDS, PULSE_KEYWORDS
from idea_generator import generate_ideas, build_style_report_html
from report_builder import build_trends_html
from analyst import generate_analyst_commentary
import storage

load_dotenv()

# .strip() на случай, если при копировании в переменные окружения (Railway/Render/.env)
# зацепился лишний пробел или перенос строки — частая причина InvalidToken
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
YOUTUBE_API_KEY = (os.getenv("YOUTUBE_API_KEY") or "").strip()
DIGEST_CHAT_ID = (os.getenv("DIGEST_CHAT_ID") or "").strip()

CACHE_TTL_SECONDS = 30 * 60         # кэш для полного /trends
PULSE_CACHE_TTL_SECONDS = 25 * 60   # отдельный кэш для лёгких пульс-проверок
MIN_NOTIFY_INTERVAL_HOURS = 1.0     # защита от слишком частых уведомлений (квота API)
PULSE_TICK_SECONDS = 15 * 60        # как часто проверяем "не пора ли отправить пульс"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_cache = {"videos": [], "fetched_at": 0}
_pulse_cache = {"videos": [], "fetched_at": 0}

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 Тренды"), KeyboardButton("💡 Идеи")],
        [KeyboardButton("🎙️ Аналитика"), KeyboardButton("📈 Рост каналов")],
        [KeyboardButton("🔔 Уведомления")],
    ],
    resize_keyboard=True,
)

REFRESH_TRENDS_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🔄 Обновить сейчас", callback_data="refresh_trends")]]
)
REFRESH_IDEA_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🔄 Обновить сейчас", callback_data="refresh_idea")]]
)
NOTIFY_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("✅ Включить, раз в 1ч", callback_data="notify_on_1")],
    [InlineKeyboardButton("✅ Включить, раз в 2ч", callback_data="notify_on_2")],
    [InlineKeyboardButton("⏸ Выключить", callback_data="notify_off")],
])


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
        logger.info(f"Fetching {'fresh (forced)' if force else 'fresh'} full trends from YouTube API...")
        _cache["videos"] = fetch_trends(YOUTUBE_API_KEY, keywords=DEFAULT_KEYWORDS)
        _cache["fetched_at"] = now
    return _cache["videos"]


def _get_pulse_trends():
    """Лёгкий фетч на урезанном наборе ключевых слов — для частых автоматических проверок."""
    now = time.time()
    if not _pulse_cache["videos"] or (now - _pulse_cache["fetched_at"] > PULSE_CACHE_TTL_SECONDS):
        logger.info("Fetching pulse (lightweight) trends from YouTube API...")
        _pulse_cache["videos"] = fetch_trends(YOUTUBE_API_KEY, keywords=PULSE_KEYWORDS)
        _pulse_cache["fetched_at"] = now
    return _pulse_cache["videos"]


async def _send_html_report(message, html_content: str, filename: str, caption: str = None, reply_markup=None):
    buf = io.BytesIO(html_content.encode("utf-8"))
    buf.name = filename
    await message.reply_document(
        document=InputFile(buf, filename=filename),
        caption=caption,
        parse_mode=ParseMode.HTML if caption else None,
        reply_markup=reply_markup,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Слежу за русскоязычными твич-стримерами на YouTube — только реальные "
        "авторские каналы, без бойцов/единоборств и без нарезок чужого контента.\n\n"
        "📊 Тренды — таблица 100+ видео файлом, с превью и аватарами\n"
        "💡 Идеи — углы для видео + разбор подачи\n"
        "🎙️ Аналитика — мнение ИИ-аналитика по текущей картине\n"
        "📈 Рост каналов — кто реально растёт с начала отслеживания\n"
        "🔔 Уведомления — короткий пульс раз в 1-2 часа, без спама файлами\n\n"
        "Кнопки внизу экрана — не нужно печатать команды.",
        reply_markup=MAIN_MENU,
    )


async def _run_trends(chat_message, force: bool, with_analysis: bool = True):
    try:
        videos = _get_trends(force=force)
    except Exception as e:
        logger.exception("Failed to fetch trends")
        await chat_message.reply_text(f"Не получилось получить тренды.\n{_friendly_youtube_error(e)}")
        return

    if not videos:
        await chat_message.reply_text(format_trends_message(videos))
        return

    caption = format_trends_message(videos)
    commentary = None
    if with_analysis:
        breakout = storage.get_breakout_channels()
        commentary = generate_analyst_commentary(videos, breakout)

    html_report = build_trends_html(videos, analyst_commentary=commentary)
    await _send_html_report(chat_message, html_report, "trends.html", caption=caption, reply_markup=REFRESH_TRENDS_KEYBOARD)


async def trends_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("upload_document")
    await _run_trends(update.message, force=False)


async def _run_idea(chat_message, force: bool):
    try:
        videos = _get_trends(force=force)
    except Exception as e:
        logger.exception("Failed to fetch trends")
        await chat_message.reply_text(f"Не получилось получить тренды.\n{_friendly_youtube_error(e)}")
        return

    message = generate_ideas(videos)
    await chat_message.reply_text(
        message, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=REFRESH_IDEA_KEYBOARD
    )

    if videos:
        breakout = storage.get_breakout_channels()
        commentary = generate_analyst_commentary(videos, breakout)
        style_report = build_style_report_html(videos, analyst_commentary=commentary)
        await _send_html_report(chat_message, style_report, "style_analysis.html")


async def idea_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    await _run_idea(update.message, force=False)


async def analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")
    try:
        videos = _get_trends()
    except Exception as e:
        logger.exception("Failed to fetch trends")
        await update.message.reply_text(f"Не получилось получить тренды.\n{_friendly_youtube_error(e)}")
        return

    breakout = storage.get_breakout_channels()
    commentary = generate_analyst_commentary(videos, breakout)
    has_key = bool((os.getenv("ANTHROPIC_API_KEY") or "").strip())
    prefix = "🎙️ <b>ИИ-анализ</b>\n\n" if has_key else "🎙️ <b>Анализ</b> (подключи ANTHROPIC_API_KEY для более глубокого ИИ-разбора)\n\n"
    await update.message.reply_text(prefix + commentary, parse_mode=ParseMode.HTML)


async def breakout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channels = storage.get_breakout_channels()
    started = storage.tracking_started_date()

    if not channels:
        await update.message.reply_text(
            "Пока нет данных о росте каналов. Бот собирает снепшот подписчиков при каждом "
            "запросе трендов — статистика появится через день-два после начала работы бота.\n\n"
            "Это честное ограничение: YouTube API не отдаёт историю подписчиков за прошлые "
            "периоды, поэтому рост можно считать только с даты, когда бот начал следить за каналом."
        )
        return

    lines = [f"📈 <b>Каналы с наибольшим ростом</b> (отслеживание с {started})\n"]
    for i, ch in enumerate(channels[:20], 1):
        sign = "+" if ch["growth_abs"] >= 0 else ""
        lines.append(
            f"{i}. <b>{ch['channel_title']}</b>\n"
            f"   {sign}{ch['growth_abs']:,} подписчиков ({sign}{ch['growth_pct']:.1f}%) "
            f"за {ch['days_tracked']}д · сейчас {ch['last_subs']:,}"
            .replace(",", " ")
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def notify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    settings = storage.get_notify_settings(chat_id)
    status = "включены" if settings["enabled"] else "выключены"
    await update.message.reply_text(
        f"🔔 Сейчас уведомления {status}"
        + (f" (раз в {settings['interval_hours']:.0f}ч)" if settings["enabled"] else "")
        + "\n\nПульс — это короткое сообщение о том, что изменилось в трендах: новые видео "
        "в HOT, кто резко набирает обороты. Не файл, не спам — 30 секунд на прочтение.",
        reply_markup=NOTIFY_KEYBOARD,
    )


async def notify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = str(update.effective_chat.id)

    if query.data == "notify_off":
        storage.set_notify(chat_id, False)
        await query.answer("Уведомления выключены")
        await query.edit_message_text("🔕 Уведомления выключены. Включить снова — /notify")
        return

    interval = 1.0 if query.data == "notify_on_1" else 2.0
    storage.set_notify(chat_id, True, interval)
    await query.answer(f"Уведомления включены, раз в {interval:.0f}ч")
    await query.edit_message_text(
        f"🔔 Уведомления включены — раз в {interval:.0f}ч буду присылать короткий пульс трендов.\n"
        "Выключить в любой момент — /notify"
    )


async def refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Обновляю прямо сейчас...")
    await query.message.chat.send_action("upload_document")
    if query.data == "refresh_trends":
        await _run_trends(query.message, force=True)
    elif query.data == "refresh_idea":
        await _run_idea(query.message, force=True)


# --- Кнопки главного меню (обычный текст, а не команды) ---

async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📊 Тренды":
        await trends_command(update, context)
    elif text == "💡 Идеи":
        await idea_command(update, context)
    elif text == "🎙️ Аналитика":
        await analysis_command(update, context)
    elif text == "📈 Рост каналов":
        await breakout_command(update, context)
    elif text == "🔔 Уведомления":
        await notify_command(update, context)


# --- Фоновая проверка "пульса" ---

def _build_pulse_message(new_videos: list, prev_state: dict) -> str:
    """Сравнивает текущие видео с прошлым снепшотом, формирует короткий пульс."""
    lines = []

    new_hot = [v for v in new_videos if v.bucket == "HOT" and v.video_id not in prev_state]
    if new_hot:
        lines.append("🔥 <b>Новое в HOT:</b>")
        for v in new_hot[:3]:
            lines.append(f"• «{v.title[:70]}» — {v.channel}, {v.views:,} просмотров".replace(",", " "))

    movers = []
    for v in new_videos:
        prev_views = prev_state.get(v.video_id)
        if prev_views is not None and v.views > prev_views:
            movers.append((v, v.views - prev_views))
    movers.sort(key=lambda pair: pair[1], reverse=True)
    if movers:
        lines.append("\n📈 <b>Быстрее всего растут:</b>")
        for v, delta in movers[:3]:
            lines.append(f"• «{v.title[:70]}» — +{delta:,} просмотров с прошлой проверки".replace(",", " "))

    small_new = [v for v in new_videos if v.is_small_channel_big_views and v.video_id not in prev_state]
    if small_new:
        lines.append("\n🚀 <b>Новый выстрел маленького канала:</b>")
        for v in small_new[:2]:
            lines.append(f"• «{v.title[:70]}» — {v.channel} ({v.subscriber_count:,} подписчиков)".replace(",", " "))

    if not lines:
        return ""
    return "⚡ <b>Пульс трендов</b>\n\n" + "\n".join(lines)


async def pulse_tick(context: ContextTypes.DEFAULT_TYPE):
    """Каждые PULSE_TICK_SECONDS проверяет все чаты с включёнными уведомлениями."""
    enabled_chats = storage.get_all_enabled_notify_chats()
    if not enabled_chats:
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    due_chats = []
    for ch in enabled_chats:
        last_sent = ch["last_sent_at"]
        interval = max(ch["interval_hours"], MIN_NOTIFY_INTERVAL_HOURS)
        if last_sent is None:
            due_chats.append(ch)
            continue
        last_dt = datetime.datetime.fromisoformat(last_sent)
        if (now - last_dt).total_seconds() >= interval * 3600:
            due_chats.append(ch)

    if not due_chats:
        return

    try:
        videos = _get_pulse_trends()
    except Exception:
        logger.exception("Pulse fetch failed")
        return

    if not videos:
        return

    for ch in due_chats:
        chat_id = ch["chat_id"]
        prev_state = storage.get_pulse_state(chat_id)
        message = _build_pulse_message(videos, prev_state)

        top_by_views = sorted(videos, key=lambda v: v.views, reverse=True)[:40]
        storage.set_pulse_state(chat_id, {v.video_id: v.views for v in top_by_views})
        storage.mark_notify_sent(chat_id, now.isoformat())

        if not message:
            continue
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=message, parse_mode=ParseMode.HTML,
                reply_markup=REFRESH_TRENDS_KEYBOARD,
            )
        except TelegramError:
            logger.exception(f"Failed to send pulse to chat {chat_id}")


async def send_daily_digest(context: ContextTypes.DEFAULT_TYPE):
    if not DIGEST_CHAT_ID:
        return
    try:
        videos = _get_trends(force=True)
        caption = "☀️ Утренняя сводка трендов\n\n" + format_trends_message(videos)
        if not videos:
            await context.bot.send_message(chat_id=DIGEST_CHAT_ID, text=caption)
            return
        breakout = storage.get_breakout_channels()
        commentary = generate_analyst_commentary(videos, breakout)
        html_report = build_trends_html(videos, analyst_commentary=commentary)
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
    app.add_handler(CommandHandler("analysis", analysis_command))
    app.add_handler(CommandHandler("breakout", breakout_command))
    app.add_handler(CommandHandler("notify", notify_command))
    app.add_handler(CallbackQueryHandler(refresh_callback, pattern="^refresh_"))
    app.add_handler(CallbackQueryHandler(notify_callback, pattern="^notify_"))
    app.add_handler(MessageHandler(filters.Regex("^(📊 Тренды|💡 Идеи|🎙️ Аналитика|📈 Рост каналов|🔔 Уведомления)$"), menu_router))
    app.add_error_handler(error_handler)

    if DIGEST_CHAT_ID:
        app.job_queue.run_daily(send_daily_digest, time=datetime.time(hour=10, minute=0))
        logger.info(f"Daily digest scheduled at 10:00 for chat {DIGEST_CHAT_ID}")

    app.job_queue.run_repeating(pulse_tick, interval=PULSE_TICK_SECONDS, first=60)
    logger.info(f"Pulse checker scheduled every {PULSE_TICK_SECONDS // 60} min (per-chat interval from /notify)")

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
