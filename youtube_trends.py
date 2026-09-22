"""
Поиск и анализ трендовых видео на YouTube в сегменте стриминга.

Логика:
1. Ищем свежие видео по набору ключевых слов (стримеры, твич, срачи и т.д.)
2. Для каждого видео считаем "скорость набора просмотров" = просмотры / часы с публикации.
   Это грубый, но рабочий индикатор того, что видео разгоняется быстрее обычного,
   а не просто у него много просмотров, потому что оно старое.
3. Делим результаты на две группы:
   - HOT: уже много абсолютных просмотров — тема уже хайповая прямо сейчас
   - RISING: просмотров пока немного, но скорость набора высокая —
     кандидат на то, чтобы выстрелить в ближайшие дни
"""

import datetime
from dataclasses import dataclass
from googleapiclient.discovery import build

# Ключевые слова сегмента — под "стриминг + медиа-личности".
# Дополняй/меняй под себя: чем точнее слова, тем релевантнее выдача.
DEFAULT_KEYWORDS = [
    "стример",
    "стримеры",
    "твич стрим",
    "разборка стримера",
    "срач стримеров",
    "скандал стример",
    "летсплей тренд",
    "блогер стример",
]

# Видео, опубликованные позже этого срока, считаем "свежими" для анализа
LOOKBACK_HOURS = 72

# Порог абсолютных просмотров, выше которого тема считается уже "HOT"
HOT_VIEWS_THRESHOLD = 150_000

# Сколько видео запрашивать на каждое ключевое слово (следи за квотой API)
RESULTS_PER_KEYWORD = 8


@dataclass
class TrendVideo:
    title: str
    channel: str
    video_id: str
    views: int
    published_at: datetime.datetime
    hours_since_published: float
    velocity: float  # просмотров в час
    keyword: str

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    @property
    def bucket(self) -> str:
        return "HOT" if self.views >= HOT_VIEWS_THRESHOLD else "RISING"


def _parse_dt(iso_string: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(iso_string.replace("Z", "+00:00"))


def fetch_trends(api_key: str, keywords=None, lookback_hours: int = LOOKBACK_HOURS,
                  results_per_keyword: int = RESULTS_PER_KEYWORD) -> list[TrendVideo]:
    """Тянет свежие видео по ключевым словам и считает скорость набора просмотров."""
    keywords = keywords or DEFAULT_KEYWORDS
    youtube = build("youtube", "v3", developerKey=api_key)

    published_after = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=lookback_hours)
    ).isoformat().replace("+00:00", "Z")

    seen_video_ids = set()
    all_videos: list[TrendVideo] = []

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

        video_ids = [
            item["id"]["videoId"]
            for item in search_resp.get("items", [])
            if item["id"]["videoId"] not in seen_video_ids
        ]
        if not video_ids:
            continue

        stats_resp = youtube.videos().list(
            part="statistics,snippet",
            id=",".join(video_ids),
        ).execute()

        now = datetime.datetime.now(datetime.timezone.utc)
        for item in stats_resp.get("items", []):
            vid = item["id"]
            if vid in seen_video_ids:
                continue
            seen_video_ids.add(vid)

            snippet = item["snippet"]
            stats = item.get("statistics", {})
            views = int(stats.get("viewCount", 0))
            published_at = _parse_dt(snippet["publishedAt"])
            hours_since = max((now - published_at).total_seconds() / 3600, 0.5)
            velocity = views / hours_since

            all_videos.append(TrendVideo(
                title=snippet["title"],
                channel=snippet["channelTitle"],
                video_id=vid,
                views=views,
                published_at=published_at,
                hours_since_published=hours_since,
                velocity=velocity,
                keyword=keyword,
            ))

    all_videos.sort(key=lambda v: v.velocity, reverse=True)
    return all_videos


def format_trends_message(videos: list[TrendVideo], limit: int = 12) -> str:
    """Форматирует список видео в читаемое сообщение для Telegram (HTML-разметка)."""
    if not videos:
        return "Свежих трендовых видео не нашлось. Попробуй позже или расширь список ключевых слов."

    hot = [v for v in videos if v.bucket == "HOT"][: limit // 2]
    rising = [v for v in videos if v.bucket == "RISING"][: limit // 2]

    lines = []

    if hot:
        lines.append("🔥 <b>Уже хайповое прямо сейчас</b>")
        for v in hot:
            lines.append(
                f"• <a href=\"{v.url}\">{v.title}</a>\n"
                f"  {v.channel} · {v.views:,} просмотров · {v.hours_since_published:.0f}ч назад"
                .replace(",", " ")
            )
        lines.append("")

    if rising:
        lines.append("📈 <b>Может выстрелить — растёт быстро</b>")
        for v in rising:
            lines.append(
                f"• <a href=\"{v.url}\">{v.title}</a>\n"
                f"  {v.channel} · {v.views:,} просмотров · {v.hours_since_published:.0f}ч назад"
                .replace(",", " ")
            )

    return "\n".join(lines)
