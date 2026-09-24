"""
Превращает список трендовых видео в:
1. Короткий текстовый список идей (для сообщения в Telegram)
2. HTML-отчёт с анализом паттернов подачи: форматы, вовлечённость, частые приёмы
   в заголовках, отдельный блок про маленькие каналы с большими просмотрами,
   плюс мнение ИИ-аналитика (если подключён Anthropic API — см. analyst.py).

Это анализ метаданных (то, что реально отдаёт YouTube API), а не разбор монтажа
по кадрам или содержания ролика — такого YouTube API не даёт.
"""

import datetime
import random
from collections import Counter

from report_builder import _esc, _table_section, _CSS

HOT_TEMPLATES = [
    "Разбери, почему «{title}» ({channel}) набрало {views:,} просмотров всего за {hours:.0f}ч — что именно сработало",
    "Сними реакцию/комментарий на «{title}» — тема ещё горячая, лови волну, пока не остыла",
    "Сделай сравнение: как разные блогеры освещают то же событие, что и в «{title}»",
]

RISING_TEMPLATES = [
    "«{title}» от {channel} набирает обороты быстрее обычного — есть шанс успеть с похожим контентом до перегрева темы",
    "Собери таймлайн истории вокруг «{title}» — зрители любят разборы полётов, пока не всё ясно",
    "Сделай прогноз/мнение: выстрелит ли история из «{title}» дальше, и почему",
]

SMALL_CHANNEL_TEMPLATES = [
    "«{title}» — канал {channel} совсем небольшой, но видео разлетелось. Разбери, за счёт чего маленький канал обошёл крупных",
    "Возьми формат/подачу «{title}» за референс — она сработала даже без узнаваемости канала {channel}",
]

STOPWORDS = {
    "и", "в", "на", "с", "по", "не", "что", "как", "это", "за", "от", "для", "но",
    "а", "у", "к", "о", "из", "же", "то", "все", "его", "ее", "их", "или", "чем",
}


def generate_ideas(videos: list, limit: int = 6) -> str:
    """Короткий список идей для сообщения в Telegram."""
    if not videos:
        return "Пока нет данных для идей — сначала вызови /trends."

    hot = [v for v in videos if v.bucket == "HOT"]
    rising = [v for v in videos if v.bucket == "RISING"]
    small = [v for v in videos if v.is_small_channel_big_views]

    lines = ["💡 <b>Идеи для видео на основе текущих трендов</b>\n"]
    picks = []

    for v in small[:2]:
        template = random.choice(SMALL_CHANNEL_TEMPLATES)
        picks.append(template.format(title=v.title, channel=v.channel))
    for v in hot[: max(limit // 3, 1)]:
        template = random.choice(HOT_TEMPLATES)
        picks.append(template.format(title=v.title, channel=v.channel, views=v.views, hours=v.hours_since_published))
    for v in rising[: max(limit // 3, 1)]:
        template = random.choice(RISING_TEMPLATES)
        picks.append(template.format(title=v.title, channel=v.channel, views=v.views, hours=v.hours_since_published))

    for i, idea in enumerate(picks[:limit], 1):
        lines.append(f"{i}. {idea.replace(',', ' ')}")

    lines.append("\n📊 Полный разбор подачи (форматы, вовлечённость, паттерны заголовков) — во вложении.")
    return "\n\n".join(lines)


def _title_word_frequency(videos: list, top_n: int = 12) -> list:
    counter = Counter()
    for v in videos:
        words = [w.strip(".,!?«»\"'()").lower() for w in v.title.split()]
        for w in words:
            if len(w) >= 4 and w not in STOPWORDS and w.isalpha():
                counter[w] += 1
    return counter.most_common(top_n)


def build_style_report_html(videos: list, title: str = "Анализ подачи — твич-стримеры",
                             analyst_commentary: str = None) -> str:
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

    if not videos:
        return f"<!DOCTYPE html><html><body><h1>{_esc(title)}</h1><p>Нет данных — вызови /trends сначала.</p></body></html>"

    shorts = [v for v in videos if v.is_short]
    long_form = [v for v in videos if not v.is_short and v.duration_seconds > 0]
    hot = [v for v in videos if v.bucket == "HOT"]
    rising = [v for v in videos if v.bucket == "RISING"]
    small = sorted(
        [v for v in videos if v.is_small_channel_big_views],
        key=lambda v: (v.views_per_subscriber or 0), reverse=True
    )
    max_velocity = max((v.velocity for v in videos), default=1) or 1

    avg_er_hot = (sum(v.engagement_rate for v in hot) / len(hot) * 100) if hot else 0
    avg_er_rising = (sum(v.engagement_rate for v in rising) / len(rising) * 100) if rising else 0

    words = _title_word_frequency(videos)
    words_html = "".join(
        f'<span class="note" style="font-size:13px;padding:5px 10px;">{_esc(w)} · {c}</span>' for w, c in words
    )

    shorts_pct = (len(shorts) / len(videos) * 100) if videos else 0

    analyst_html = ""
    if analyst_commentary:
        analyst_html = f"""
<div class="analyst-box">
  <div class="label">🎙️ Мнение аналитика</div>
  {_esc(analyst_commentary).replace(chr(10)+chr(10), '<br><br>').replace(chr(10), '<br>')}
</div>"""

    small_section = ""
    if small:
        small_section = _table_section("🚀 Маленькие каналы, большие просмотры — референсы для формата", small[:20], max_velocity)

    detail_section = _table_section(f"Разбор по видео (топ {min(len(videos),60)} по скорости роста)", videos[:60], max_velocity)

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{_CSS}
.pattern-grid {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 14px 0 24px; }}
.callout {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; margin-bottom: 20px; font-size: 13px; color: var(--muted); line-height: 1.6; }}
</style>
</head><body>
<h1>{_esc(title)}</h1>
<div class="meta">Сформировано: {now_str} · анализ метаданных {len(videos)} видео (не разбор монтажа по кадрам — этого YouTube API не даёт)</div>

<div class="stat-row">
  <div class="stat"><b>{shorts_pct:.0f}%</b>из трендов — Shorts</div>
  <div class="stat"><b>{len(long_form)}</b>длинных видео в выборке</div>
  <div class="stat hot"><b>{avg_er_hot:.1f}%</b>ср. вовлечённость HOT</div>
  <div class="stat rising"><b>{avg_er_rising:.1f}%</b>ср. вовлечённость RISING</div>
</div>
{analyst_html}
<div class="callout">
  <b>Как читать:</b> вовлечённость = (лайки + комментарии) / просмотры — чем выше, тем сильнее
  видео цепляет тех, кто его уже посмотрел. Скорость — просмотров в час с публикации, показывает,
  что разгоняется быстрее обычного прямо сейчас. Заметки по подаче — эвристика по формату и
  заголовку (Shorts/длинное, КАПС, вопрос, эмодзи), не содержание или монтаж ролика.
</div>

<section>
  <h2>Частые слова в заголовках трендовых видео</h2>
  <div class="pattern-grid">{words_html or "недостаточно данных"}</div>
</section>

{small_section}
{detail_section}
</body></html>"""
