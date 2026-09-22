"""
Поиск и анализ трендовых видео на YouTube — русский сегмент, ниша стриминга/медиа-личностей.

Логика:
1. Ищем свежие видео по расширенному набору ключевых слов (только русский язык/регион).
2. Для каждого видео тянем: просмотры, лайки, комментарии, длительность, теги,
   а также число подписчиков канала.
3. Считаем:
   - velocity = просмотров в час с момента публикации (сигнал "разгоняется быстрее обычного")
   - engagement_rate = (лайки + комментарии) / просмотры (сигнал "залипательности")
   - views_per_subscriber = просмотры / подписчики канала (сигнал "выстрелило относительно размера канала")
4. Формируем эвристические заметки о подаче: формат (Shorts/длинное), приёмы в заголовке
   (КАПС, вопрос, восклицание, эмодзи), уровень вовлечённости.

Важно понимать ограничение: это анализ метаданных (что отдаёт YouTube API), а не разбор
монтажа по кадрам или содержания ролика — такой анализ видео API не даёт в принципе.
"""

import datetime
import re
from dataclasses import dataclass, field
from typing import Optional

from googleapiclient.discovery import build

# Ключевые слова сегмента — под "русскоязычный стриминг + медиа-личности".
# Дополняй именами конкретных стримеров/блогеров, за которыми следишь —
# так выдача станет точнее под твою тему.
DEFAULT_KEYWORDS = [
    "стример", "стримеры", "твич стрим", "разборка стримера", "срач стримеров",
    "скандал стример", "летсплей тренд", "блогер стример", "донат стрим",
    "стрим драма", "ютубер скандал", "блогер разоблачение", "стример новости",
    "трэш стрим", "ссора блогеров", "реакция на стрим", "звездная болезнь блогер",
    "стрим ситуация", "медиа персона разбор", "блогер извинения",
]

LOOKBACK_HOURS = 72                # глубина поиска по времени публикации
HOT_VIEWS_THRESHOLD = 150_000      # порог "уже хайповое" по абсолютным просмотрам
RESULTS_PER_KEYWORD = 10           # результатов на ключевое слово (следи за квотой API)
TARGET_MIN_VIDEOS = 100            # к какому минимуму стремимся при сборе

# Маленьким считаем канал с подписчиками меньше этого порога
SMALL_CHANNEL_SUBSCRIBER_THRESHOLD = 50_000
# И при этом просмотры должны быть минимум в столько раз больше подписчиков
SMALL_CHANNEL_VIEW_MULTIPLIER = 5
# Плюс минимальный абсолютный порог просмотров, чтобы не ловить шум
SMALL_CHANNEL_MIN_VIEWS = 15_000

CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")
LATIN_RE = re.compile(r"[a-zA-Z]")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)


@dataclass
class TrendVideo:
    title: str
    channel: str
    channel_id: str
    video_id: str
    views: int
    likes: int
    comments: int
    published_at: datetime.datetime
    hours_since_published: float
    velocity: float
    keyword: str
    duration_seconds: int
    tags: list = field(default_factory=list)
    subscriber_count: Optional[int] = None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def bucket(self) -> str:
        return "HOT" if self.views >= HOT_VIEWS_THRESHOLD else "RISING"

    @property
    def is_short(self) -> bool:
        return self.duration_seconds > 0 and self.duration_seconds <= 60

    @property
    def engagement_rate(self) -> float:
        if self.views <= 0:
            return 0.0
        return (self.likes + self.comments) / self.views

    @property
    def views_per_subscriber(self) -> Optional[float]:
        if not self.subscriber_count:
            return None
        return self.views / self.subscriber_count

    @property
    def is_small_channel_big_views(self) -> bool:
        if self.subscriber_count is None:
            return False
        if self.subscriber_count >= SMALL_CHANNEL_SUBSCRIBER_THRESHOLD:
            return False
        if self.views < SMALL_CHANNEL_MIN_VIEWS:
            return False
        vps = self.views_per_subscriber or 0
        return vps >= SMALL_CHANNEL_VIEW_MULTIPLIER

    @property
    def style_notes(self) -> list:
        """Эвристические заметки о подаче — на основе метаданных, не содержания видео."""
        notes = []

        if self.is_short:
            notes.append("Shorts (до 60с)")
        elif self.duration_seconds > 0:
            minutes = self.duration_seconds / 60
            if minutes <= 5:
                notes.append("короткий формат (≤5 мин)")
            elif minutes >= 25:
                notes.append("длинный формат (25+ мин)")

        title = self.title
        letters = [c for c in title if c.isalpha()]
        if letters:
            caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if caps_ratio > 0.4:
                notes.append("заголовок КАПСОМ")
        if "?" in title:
            notes.append("вопрос в заголовке")
        if "!" in title:
            notes.append("восклицание в заголовке")
        if EMOJI_RE.search(title):
            notes.append("эмодзи в заголовке")

        er = self.engagement_rate
        if er >= 0.05:
            notes.append("высокая вовлечённость (лайки+комменты)")
        elif er > 0 and er < 0.01:
            notes.append("низкая вовлечённость")

        if self.is_small_channel_big_views:
            notes.append("🚀 маленький канал, но выстрелило")

        return notes


def is_probably_russian(text: str) -> bool:
    """Грубый фильтр 'только русский сегмент': кириллицы должно быть заметно больше латиницы."""
    cyr = len(CYRILLIC_RE.findall(text))
    lat = len(LATIN_RE.findall(text))
    if cyr == 0:
        return False
    return cyr >= lat


def _parse_dt(iso_string: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(iso_string.replace("Z", "+00:00"))


def _parse_duration(iso_duration: str) -> int:
    """PT1H2M10S -> секунды. Возвращает 0, если не удалось распарсить."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def fetch_trends(api_key: str, keywords=None, lookback_hours: int = LOOKBACK_HOURS,
                  results_per_keyword: int = RESULTS_PER_KEYWORD) -> list:
    """Тянет свежие видео русского сегмента и считает метрики трендовости."""
    keywords = keywords or DEFAULT_KEYWORDS
    youtube = build("youtube", "v3", developerKey=api_key)

    published_after = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=lookback_hours)
    ).isoformat().replace("+00:00", "Z")

    seen_video_ids = set()
    raw_items = []  # (video_id, keyword)

    for keyword in keywords:
        search_resp = youtube.search().list(
            q=keyword,
            part="snippet",
            type="video",
            order="viewCount",
            publishedAfter=published_after,
            maxResults=results_per_keyword,
            relevanceLanguage="ru",
            regionCode="RU",
        ).execute()

        for item in search_resp.get("items", []):
            vid = item["id"]["videoId"]
            if vid not in seen_video_ids:
                seen_video_ids.add(vid)
                raw_items.append((vid, keyword))

    if not raw_items:
        return []

    keyword_by_id = dict(raw_items)
    all_video_ids = [vid for vid, _ in raw_items]

    now = datetime.datetime.now(datetime.timezone.utc)
    videos_by_channel: dict = {}
    prelim: list = []

    for chunk in _chunks(all_video_ids, 50):
        stats_resp = youtube.videos().list(
            part="statistics,snippet,contentDetails",
            id=",".join(chunk),
        ).execute()

        for item in stats_resp.get("items", []):
            snippet = item["snippet"]
            title = snippet["title"]
            if not is_probably_russian(title):
                continue

            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0)) if "likeCount" in stats else 0
            comments = int(stats.get("commentCount", 0)) if "commentCount" in stats else 0
            published_at = _parse_dt(snippet["publishedAt"])
            hours_since = max((now - published_at).total_seconds() / 3600, 0.5)
            velocity = views / hours_since
            duration_seconds = _parse_duration(content.get("duration", ""))
            channel_id = snippet["channelId"]

            tv = TrendVideo(
                title=title,
                channel=snippet["channelTitle"],
                channel_id=channel_id,
                video_id=item["id"],
                views=views,
                likes=likes,
                comments=comments,
                published_at=published_at,
                hours_since_published=hours_since,
                velocity=velocity,
                keyword=keyword_by_id.get(item["id"], ""),
                duration_seconds=duration_seconds,
                tags=snippet.get("tags", []) or [],
            )
            prelim.append(tv)
            videos_by_channel.setdefault(channel_id, []).append(tv)

    # Подтягиваем число подписчиков пачками по 50 каналов
    channel_ids = list(videos_by_channel.keys())
    for chunk in _chunks(channel_ids, 50):
        ch_resp = youtube.channels().list(
            part="statistics",
            id=",".join(chunk),
        ).execute()
        for item in ch_resp.get("items", []):
            cid = item["id"]
            stats = item.get("statistics", {})
            if stats.get("hiddenSubscriberCount"):
                sub_count = None
            else:
                sub_count = int(stats["subscriberCount"]) if "subscriberCount" in stats else None
            for tv in videos_by_channel.get(cid, []):
                tv.subscriber_count = sub_count

    prelim.sort(key=lambda v: v.velocity, reverse=True)
    return prelim


def format_trends_message(videos: list, limit: int = 12) -> str:
    """Короткое текстовое summary для подписи к файлу (не вся таблица — она в HTML-документе)."""
    if not videos:
        return "Свежих трендовых видео не нашлось. Попробуй позже или расширь список ключевых слов."

    hot = [v for v in videos if v.bucket == "HOT"]
    rising = [v for v in videos if v.bucket == "RISING"]
    small = [v for v in videos if v.is_small_channel_big_views]

    return (
        f"Проанализировано видео: {len(videos)}\n"
        f"🔥 HOT: {len(hot)} · 📈 RISING: {len(rising)} · 🚀 маленький канал/большие просмотры: {len(small)}\n\n"
        f"Полная таблица — во вложении."
    )
