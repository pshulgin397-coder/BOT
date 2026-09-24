"""
Жёсткая фильтрация: оставляем только твич-стримеров (реальных людей, ведущих
свой канал), убираем бойцов/единоборства и нарезки/компиляции чужого контента.

Два уровня проверки:
1. По официальным topic-категориям канала (YouTube отдаёт ссылки на Wikipedia-темы
   через channels().list(part="topicDetails")) — надёжнее, чем текстовые слова.
2. Резервные текстовые паттерны — на случай, если topicDetails пустой (бывает у
   части каналов).
"""

import re

# Тематики единоборств/спорта, которые надо исключить (Wikipedia-категории из topicDetails)
FIGHTER_TOPIC_HINTS = [
    "Boxing", "Mixed_martial_arts", "Professional_wrestling", "Wrestling",
    "Kickboxing", "Contact_sport", "Combat_sport",
]

# Резервные текстовые паттерны (если topicDetails недоступен)
FIGHTER_WORD_RE = re.compile(
    r"\b(боец|бойцы|боксёр|боксер|бокс|mma|ufc|уфс|ринг|нокаут|поединок|"
    r"единоборств|кулачный бой|турнир по боксу)\b",
    re.IGNORECASE,
)

# Нарезки/компиляции чужого контента — не авторский канал стримера
CLIP_TITLE_RE = re.compile(
    r"\b(нарезка|нарезки|подборка|подборки|приколы со стрима|смешные моменты|"
    r"best moments|highlights|хайлайты|compilation|компиляция|топ моментов)\b",
    re.IGNORECASE,
)
CLIP_CHANNEL_RE = re.compile(
    r"(нарезк|клипы|moments|highlights|compilation|подборк)",
    re.IGNORECASE,
)

# Сигнал "это про твич-стриминг" — требуем хотя бы один такой признак
STREAM_SIGNAL_RE = re.compile(
    r"\b(твич|twitch|стрим|стример|стримит|стримерш)\w*\b",
    re.IGNORECASE,
)


def channel_is_fighter_related(topic_categories: list) -> bool:
    for url in topic_categories or []:
        for hint in FIGHTER_TOPIC_HINTS:
            if hint in url:
                return True
    return False


def is_fighter_related(video) -> bool:
    if channel_is_fighter_related(getattr(video, "topic_categories", [])):
        return True
    return bool(FIGHTER_WORD_RE.search(video.title) or FIGHTER_WORD_RE.search(video.channel))


def is_clip_or_compilation(video) -> bool:
    if CLIP_TITLE_RE.search(video.title):
        return True
    if CLIP_CHANNEL_RE.search(video.channel):
        return True
    return False


def has_streamer_signal(video) -> bool:
    haystack = video.title + " " + " ".join(video.tags or []) + " " + video.keyword
    return bool(STREAM_SIGNAL_RE.search(haystack))


def passes_streamer_filter(video) -> bool:
    """True — видео реально про твич-стримера, не про бойца и не нарезка чужого контента."""
    if is_fighter_related(video):
        return False
    if is_clip_or_compilation(video):
        return False
    if not has_streamer_signal(video):
        return False
    return True
