"""
Генерирует профессиональный аналитический комментарий по трендам.

Два режима:
1. Если задан ANTHROPIC_API_KEY — реальный анализ от Claude: боту передаётся сводка
   цифр (не сырые видео поштучно — экономим токены), и он пишет комментарий как
   ютуб-аналитик и контентмейкер, живым языком, с конкретными рекомендациями.
2. Без ключа — качественный, но шаблонный анализ на основе тех же цифр (без Anthropic
   SDK и без затрат — работает всегда "из коробки").

Получить ключ: console.anthropic.com → Get API keys → Create key.
Стоимость: анализ на модели claude-haiku-4-5 стоит доли цента за вызов — этого
достаточно для регулярных вызовов (даже раз в час).
"""

import os


def _build_data_summary(videos: list, breakout_channels: list = None) -> str:
    """Компактная сводка цифр для передачи в LLM — не тратим токены на сырые данные."""
    if not videos:
        return "Данных нет."

    hot = [v for v in videos if v.bucket == "HOT"]
    rising = [v for v in videos if v.bucket == "RISING"]
    small = sorted(
        [v for v in videos if v.is_small_channel_big_views],
        key=lambda v: (v.views_per_subscriber or 0), reverse=True
    )[:8]
    shorts_pct = (sum(1 for v in videos if v.is_short) / len(videos) * 100) if videos else 0
    avg_er = sum(v.engagement_rate for v in videos) / len(videos) * 100 if videos else 0

    top_movers = sorted(videos, key=lambda v: v.velocity, reverse=True)[:10]

    lines = [
        f"Всего видео в выборке: {len(videos)}. HOT: {len(hot)}, RISING: {len(rising)}.",
        f"Доля Shorts: {shorts_pct:.0f}%. Средняя вовлечённость (лайки+комменты/просмотры): {avg_er:.1f}%.",
        "",
        "Топ-10 по скорости роста просмотров в час:",
    ]
    for v in top_movers:
        lines.append(
            f"- «{v.title}» ({v.channel}, {v.subscriber_count or '?'} подписчиков): "
            f"{v.views} просмотров за {v.hours_since_published:.0f}ч, "
            f"{v.velocity:.0f}/ч, вовлечённость {v.engagement_rate*100:.1f}%, "
            f"формат: {'Shorts' if v.is_short else f'{v.duration_seconds//60}мин'}"
        )

    if small:
        lines.append("\nМаленькие каналы с непропорционально большими просмотрами:")
        for v in small:
            lines.append(
                f"- «{v.title}» ({v.channel}, {v.subscriber_count} подписчиков): "
                f"{v.views} просмотров ({v.views_per_subscriber:.1f}x к размеру канала)"
            )

    if breakout_channels:
        lines.append("\nКаналы с наибольшим ростом подписчиков за отслеживаемый период:")
        for ch in breakout_channels[:8]:
            lines.append(
                f"- {ch['channel_title']}: +{ch['growth_abs']} подписчиков "
                f"({ch['growth_pct']:.1f}%) за {ch['days_tracked']}д"
            )

    return "\n".join(lines)


def _fallback_commentary(videos: list, breakout_channels: list = None) -> str:
    """Шаблонный анализ без внешнего ИИ — работает всегда, без ключа и без затрат."""
    if not videos:
        return "Недостаточно данных для анализа."

    hot = [v for v in videos if v.bucket == "HOT"]
    rising = [v for v in videos if v.bucket == "RISING"]
    small = [v for v in videos if v.is_small_channel_big_views]
    shorts_pct = (sum(1 for v in videos if v.is_short) / len(videos) * 100) if videos else 0

    parts = []

    if shorts_pct > 60:
        parts.append(
            f"Shorts сейчас — {shorts_pct:.0f}% трендовых видео в нише. Если ты ещё не делаешь "
            "короткий формат, это самый быстрый способ попасть в выдачу новичку без подписчиков."
        )
    elif shorts_pct < 30:
        parts.append(
            f"Только {shorts_pct:.0f}% трендов — Shorts. Сейчас в нише выигрывает длинный формат "
            "с реальным разбором, а не короткие нарезки — аудитория явно хочет контекст, а не хайлайты."
        )

    if small:
        top_small = max(small, key=lambda v: v.views_per_subscriber or 0)
        parts.append(
            f"Обрати внимание на «{top_small.channel}» — канал с {top_small.subscriber_count} "
            f"подписчиками собрал {top_small.views} просмотров на одном видео "
            f"({top_small.views_per_subscriber:.1f}x к размеру канала). Это значит: тема или подача "
            "важнее раскрученности канала — у тебя как у новичка есть реальный шанс."
        )

    if hot and rising:
        parts.append(
            f"Сейчас {len(hot)} тем уже раскачаны (конкуренция высокая, но и спрос подтверждён), "
            f"и {len(rising)} только набирают обороты — по ним ещё можно успеть первым."
        )

    if breakout_channels:
        top_growth = breakout_channels[0]
        parts.append(
            f"Быстрее всех растёт «{top_growth['channel_title']}»: "
            f"+{top_growth['growth_abs']} подписчиков за {top_growth['days_tracked']}д. "
            "Стоит посмотреть, что именно они делают в последних видео."
        )

    if not parts:
        parts.append("Пока рано делать выводы — данных недостаточно для уверенного анализа.")

    return "\n\n".join(parts)


def generate_analyst_commentary(videos: list, breakout_channels: list = None) -> str:
    """
    Возвращает текст профессионального анализа. Использует Claude API, если задан
    ANTHROPIC_API_KEY, иначе — резервный шаблонный анализ (тоже полезный, просто менее гибкий).
    """
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return _fallback_commentary(videos, breakout_channels)

    try:
        import anthropic
    except ImportError:
        return _fallback_commentary(videos, breakout_channels) + (
            "\n\n(Хочешь живой ИИ-анализ — установи пакет anthropic: pip install anthropic)"
        )

    model = (os.getenv("ANTHROPIC_MODEL") or "claude-haiku-4-5-20251001").strip()
    data_summary = _build_data_summary(videos, breakout_channels)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=700,
            system=(
                "Ты — профессиональный YouTube-аналитик и контентмейкер. Тебе передают сводку "
                "цифр по трендовым видео русскоязычных твич-стримеров на YouTube. Дай короткий "
                "(4-6 предложений), конкретный, полезный анализ для человека, который только "
                "начинает вести свой блог в этой нише: что сейчас реально работает, на что "
                "обратить внимание, какие форматы/темы имеют смысл прямо сейчас. Без общих фраз "
                "и воды — только то, что видно из цифр. Пиши по-русски, неформально, по делу."
            ),
            messages=[{"role": "user", "content": data_summary}],
        )
        text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        return "\n".join(text_blocks).strip() or _fallback_commentary(videos, breakout_channels)
    except Exception as e:
        return _fallback_commentary(videos, breakout_channels) + f"\n\n(ИИ-анализ временно недоступен: {e})"
