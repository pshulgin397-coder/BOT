"""
Превращает список трендовых видео в конкретные углы для контента.
Это шаблонная генерация (без внешнего ИИ) — быстро, бесплатно, без лишних API.
"""

import random
from youtube_trends import TrendVideo

HOT_TEMPLATES = [
    "Разбери, почему «{title}» ({channel}) набрало {views:,} просмотров всего за {hours:.0f}ч — что именно сделал автор правильно",
    "Сними реакцию/комментарий на «{title}» — тема ещё горячая, лови волну, пока не остыла",
    "Сделай видео-сравнение: как разные блогеры освещают то же событие, что и в «{title}»",
]

RISING_TEMPLATES = [
    "«{title}» от {channel} набирает обороты быстрее обычного — есть шанс успеть с похожим контентом до того, как тема станет перегретой",
    "Собери таймлайн истории вокруг «{title}» — зрители любят разборы полётов, когда ещё не всё ясно",
    "Сделай прогноз/мнение: выстрелит ли история из «{title}» дальше, и почему",
]


def generate_ideas(videos: list[TrendVideo], limit: int = 6) -> str:
    if not videos:
        return "Пока нет данных для идей — сначала вызови /trends."

    hot = [v for v in videos if v.bucket == "HOT"]
    rising = [v for v in videos if v.bucket == "RISING"]

    lines = ["💡 <b>Идеи для видео на основе текущих трендов</b>\n"]

    picks = []
    for v in hot[: limit // 2]:
        template = random.choice(HOT_TEMPLATES)
        picks.append(template.format(title=v.title, channel=v.channel, views=v.views, hours=v.hours_since_published))
    for v in rising[: limit // 2]:
        template = random.choice(RISING_TEMPLATES)
        picks.append(template.format(title=v.title, channel=v.channel, views=v.views, hours=v.hours_since_published))

    for i, idea in enumerate(picks, 1):
        lines.append(f"{i}. {idea.replace(',', ' ')}")

    return "\n\n".join(lines)
