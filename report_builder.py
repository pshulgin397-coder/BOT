"""
Генерирует самодостаточный HTML-файл с анимированной таблицей трендов —
превью видео, аватары каналов, полоски вовлечённости, hero-карточки топ-видео.

Отправляется ботом как документ — открывается в любом браузере. Использует внешние
картинки (превью с i.ytimg.com) и Google Fonts — это обычная веб-страница в браузере
пользователя, а не встроенный предпросмотр, так что внешние ресурсы загружаются нормально.
"""

import datetime
import html


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _fmt_num(n) -> str:
    if n is None:
        return "—"
    return f"{n:,}".replace(",", " ")


def _fmt_compact(n) -> str:
    """1234567 -> 1.2M, 45300 -> 45.3K — компактный формат для hero-карточек."""
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&family=Inter:wght@400;500;600&display=swap');

:root {
  --bg: #0b0d13; --panel: #151824; --panel-2: #1b1f2e; --panel-3: #21263a;
  --ink: #eef0f7; --muted: #8b91a8; --line: #262b3d;
  --hot: #ff4d6d; --rising: #4dabff; --small: #ffd166; --good: #4dd68c;
  --grad1: #ff4d6d; --grad2: #8b5cf6; --grad3: #4dabff;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 20px 70px;
  background:
    radial-gradient(circle at 10% -10%, rgba(139,92,246,0.12), transparent 40%),
    radial-gradient(circle at 90% 0%, rgba(255,77,109,0.10), transparent 40%),
    var(--bg);
  color: var(--ink);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
h1 {
  font-family: 'Manrope', sans-serif; font-weight: 800; font-size: 26px; margin: 0 0 4px;
  background: linear-gradient(90deg, #fff, #c9ccdb);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.meta { color: var(--muted); font-size: 13px; margin-bottom: 22px; }

.stat-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 28px; }
.stat {
  background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 12px 18px; font-size: 13px; min-width: 120px;
}
.stat b { font-family: 'Manrope', sans-serif; font-size: 20px; display: block; font-weight: 800; }
.stat.hot b { color: var(--hot); }
.stat.rising b { color: var(--rising); }
.stat.small b { color: var(--small); }

.analyst-box {
  background: linear-gradient(135deg, rgba(139,92,246,0.12), rgba(255,77,109,0.08));
  border: 1px solid rgba(139,92,246,0.25); border-radius: 18px;
  padding: 20px 22px; margin-bottom: 30px; font-size: 14px; line-height: 1.7;
}
.analyst-box .label {
  font-family: 'Manrope', sans-serif; font-weight: 800; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.06em; color: #c4b5fd; margin-bottom: 10px;
  display: flex; align-items: center; gap: 6px;
}

section { margin-bottom: 36px; }
h2 {
  font-family: 'Manrope', sans-serif; font-weight: 700; font-size: 16px; margin: 0 0 14px;
  display: flex; align-items: center; gap: 8px;
}
.pulse-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--hot);
  animation: pulse 1.6s ease-in-out infinite; flex-shrink: 0;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(1.4); }
}

/* Hero-карточки топ видео */
.hero-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px; margin-bottom: 8px;
}
.hero-card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 16px;
  overflow: hidden; opacity: 0; animation: cardIn 0.5s cubic-bezier(.22,1,.36,1) forwards;
  transition: transform 0.25s ease, border-color 0.25s ease;
}
.hero-card:hover { transform: translateY(-3px); border-color: rgba(139,92,246,0.4); }
@keyframes cardIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
.hero-thumb { width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; background: var(--panel-2); }
.hero-body { padding: 12px 14px 14px; }
.hero-title {
  font-size: 13px; font-weight: 600; line-height: 1.35; margin: 0 0 8px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.hero-title a { color: var(--ink); text-decoration: none; }
.hero-title a:hover { color: var(--rising); }
.hero-meta { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--muted); }
.hero-avatar { width: 18px; height: 18px; border-radius: 50%; object-fit: cover; flex-shrink: 0; }
.hero-stats { display: flex; justify-content: space-between; margin-top: 8px; font-size: 11.5px; }
.hero-velocity { color: var(--hot); font-weight: 700; }

.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 16px; background: var(--panel); }
table { border-collapse: collapse; width: 100%; min-width: 1050px; font-size: 12.5px; }
thead th {
  position: sticky; top: 0; background: var(--panel-3); color: var(--muted);
  text-align: left; padding: 11px 12px; font-weight: 700; border-bottom: 1px solid var(--line);
  white-space: nowrap; font-family: 'Manrope', sans-serif; font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.04em;
}
tbody td { padding: 9px 12px; border-bottom: 1px solid var(--line); vertical-align: middle; }
tbody tr { background: var(--panel); opacity: 0; animation: rowIn 0.4s ease forwards; }
@keyframes rowIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
tbody tr:hover { background: var(--panel-2); }
a { color: var(--rising); text-decoration: none; }
a:hover { text-decoration: underline; }

.video-cell { display: flex; align-items: center; gap: 10px; min-width: 260px; }
.row-thumb { width: 64px; height: 36px; border-radius: 6px; object-fit: cover; flex-shrink: 0; background: var(--panel-2); }
.video-cell-text { min-width: 0; }
.video-cell-title { display: block; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 260px; }

.channel-cell { display: flex; align-items: center; gap: 7px; }
.channel-avatar { width: 22px; height: 22px; border-radius: 50%; object-fit: cover; flex-shrink: 0; }

.badge {
  display: inline-block; padding: 2px 8px; border-radius: 100px; font-size: 10.5px;
  font-weight: 700; margin-right: 4px; margin-top: 3px;
}
.badge.hot { background: rgba(255,77,109,0.15); color: var(--hot); }
.badge.rising { background: rgba(77,171,255,0.15); color: var(--rising); }
.badge.small { background: rgba(255,209,102,0.18); color: var(--small); }
.note {
  display: inline-block; font-size: 10.5px; color: var(--muted); background: var(--panel-3);
  border-radius: 8px; padding: 2px 7px; margin: 1px 3px 1px 0;
}
.num { text-align: right; font-variant-numeric: tabular-nums; }

.bar-track { width: 70px; height: 5px; border-radius: 3px; background: var(--panel-3); overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, var(--grad2), var(--grad1)); }
"""


def _bar(pct: float) -> str:
    pct = max(0, min(100, pct))
    return f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.0f}%"></div></div>'


def _row_html(i: int, v, delay_step: float = 0.012, max_velocity: float = 1) -> str:
    badges = '<span class="badge hot">HOT</span>' if v.bucket == "HOT" else '<span class="badge rising">RISING</span>'
    if v.is_small_channel_big_views:
        badges += '<span class="badge small">🚀 SMALL→BIG</span>'

    notes_html = "".join(f'<span class="note">{_esc(n)}</span>' for n in v.style_notes)
    vps = v.views_per_subscriber
    vps_str = f"{vps:.1f}×" if vps is not None else "—"
    velocity_pct = (v.velocity / max_velocity * 100) if max_velocity else 0
    thumb = f'<img class="row-thumb" src="{_esc(v.thumbnail_url)}" alt="" loading="lazy">' if v.thumbnail_url else '<div class="row-thumb"></div>'
    avatar = f'<img class="channel-avatar" src="{_esc(v.channel_avatar_url)}" alt="" loading="lazy">' if v.channel_avatar_url else ""

    return f"""<tr style="animation-delay:{i * delay_step:.3f}s">
  <td class="num">{i + 1}</td>
  <td><div class="video-cell">{thumb}<div class="video-cell-text">
    <a class="video-cell-title" href="{v.url}" target="_blank" rel="noopener">{_esc(v.title)}</a>
    {badges}
  </div></div></td>
  <td><div class="channel-cell">{avatar}<span>{_esc(v.channel)}</span></div></td>
  <td class="num">{_fmt_num(v.views)}</td>
  <td class="num">{_fmt_num(v.subscriber_count)}</td>
  <td class="num">{vps_str}</td>
  <td>{_bar(velocity_pct)}<div class="num" style="font-size:10.5px;color:var(--muted);margin-top:2px;">{_fmt_num(round(v.velocity))}/ч</div></td>
  <td class="num">{v.engagement_rate * 100:.1f}%</td>
  <td>{notes_html or "—"}</td>
</tr>"""


def _hero_card(i: int, v) -> str:
    thumb = f'<img class="hero-thumb" src="{_esc(v.thumbnail_url)}" alt="" loading="lazy">' if v.thumbnail_url else '<div class="hero-thumb"></div>'
    avatar = f'<img class="hero-avatar" src="{_esc(v.channel_avatar_url)}" alt="" loading="lazy">' if v.channel_avatar_url else ""
    return f"""<div class="hero-card" style="animation-delay:{i*0.06:.2f}s">
  {thumb}
  <div class="hero-body">
    <p class="hero-title"><a href="{v.url}" target="_blank" rel="noopener">{_esc(v.title)}</a></p>
    <div class="hero-meta">{avatar}<span>{_esc(v.channel)}</span></div>
    <div class="hero-stats">
      <span>{_fmt_compact(v.views)} просм.</span>
      <span class="hero-velocity">{_fmt_compact(round(v.velocity))}/ч</span>
    </div>
  </div>
</div>"""


def _table_section(title_html: str, videos: list, max_velocity: float) -> str:
    rows = "".join(_row_html(i, v, max_velocity=max_velocity) for i, v in enumerate(videos))
    return f"""
<section>
  <h2><span class="pulse-dot"></span>{title_html}</h2>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>#</th><th>Видео</th><th>Канал</th><th class="num">Просмотры</th>
        <th class="num">Подписчики</th><th class="num">Просм./Подп.</th>
        <th>Скорость</th><th class="num">Вовлечён.</th><th>Заметки по подаче</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</section>"""


def build_trends_html(videos: list, title: str = "Тренды YouTube — твич-стримеры",
                       analyst_commentary: str = None) -> str:
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    hot = [v for v in videos if v.bucket == "HOT"]
    rising = [v for v in videos if v.bucket == "RISING"]
    small = sorted(
        [v for v in videos if v.is_small_channel_big_views],
        key=lambda v: (v.views_per_subscriber or 0), reverse=True
    )
    max_velocity = max((v.velocity for v in videos), default=1) or 1

    top_movers = sorted(videos, key=lambda v: v.velocity, reverse=True)[:6]
    hero_html = "".join(_hero_card(i, v) for i, v in enumerate(top_movers))

    analyst_html = ""
    if analyst_commentary:
        analyst_html = f"""
<div class="analyst-box">
  <div class="label">🎙️ Мнение аналитика</div>
  {_esc(analyst_commentary).replace(chr(10)+chr(10), '<br><br>').replace(chr(10), '<br>')}
</div>"""

    small_section = ""
    if small:
        small_section = _table_section(f"🚀 Маленькие каналы, но большие просмотры ({len(small)})", small[:25], max_velocity)

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head><body>
<h1>{_esc(title)}</h1>
<div class="meta">Сформировано: {now_str} · только твич-стримеры, русский сегмент · глубина поиска 72ч</div>

<div class="stat-row">
  <div class="stat"><b>{len(videos)}</b>всего проанализировано</div>
  <div class="stat hot"><b>{len(hot)}</b>🔥 HOT</div>
  <div class="stat rising"><b>{len(rising)}</b>📈 RISING</div>
  <div class="stat small"><b>{len(small)}</b>🚀 маленький канал → большие просмотры</div>
</div>
{analyst_html}
<section>
  <h2><span class="pulse-dot"></span>⚡ Топ-6 по скорости роста прямо сейчас</h2>
  <div class="hero-grid">{hero_html}</div>
</section>
{small_section}
{_table_section(f"Полная таблица ({len(videos)} позиций, сортировка по скорости роста)", videos, max_velocity)}
</body></html>"""
