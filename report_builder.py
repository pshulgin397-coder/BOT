"""
Генерирует самодостаточный HTML-файл с анимированной таблицей трендов.
Отправляется ботом как документ — открывается в любом браузере, не требует интернета
после загрузки (кроме шрифта Google Fonts, если он есть под рукой; без него тоже работает).
"""

import datetime
import html


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _fmt_num(n) -> str:
    if n is None:
        return "—"
    return f"{n:,}".replace(",", " ")


_CSS = """
:root {
  --bg: #0f1117; --panel: #171a23; --panel-2: #1d212c;
  --ink: #e8eaf0; --muted: #8b91a3; --line: #262b38;
  --hot: #ff4d6d; --rising: #4dabff; --small: #ffd166;
  --good: #4dd68c;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 28px 20px 60px;
  background: var(--bg); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
h1 { font-size: 22px; margin: 0 0 4px; }
.meta { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
.stat-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 26px; }
.stat {
  background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 10px 16px; font-size: 13px;
}
.stat b { font-size: 16px; display: block; }
.stat.hot b { color: var(--hot); }
.stat.rising b { color: var(--rising); }
.stat.small b { color: var(--small); }

section { margin-bottom: 34px; }
h2 { font-size: 16px; margin: 0 0 12px; display: flex; align-items: center; gap: 8px; }
.pulse-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--hot);
  animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(1.4); }
}

.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 14px; }
table { border-collapse: collapse; width: 100%; min-width: 900px; font-size: 13px; }
thead th {
  position: sticky; top: 0; background: var(--panel-2); color: var(--muted);
  text-align: left; padding: 10px 12px; font-weight: 600; border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
tbody td {
  padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top;
}
tbody tr { background: var(--panel); opacity: 0; animation: rowIn 0.4s ease forwards; }
@keyframes rowIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
tbody tr:hover { background: var(--panel-2); }
a { color: var(--rising); text-decoration: none; }
a:hover { text-decoration: underline; }
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 100px; font-size: 11px;
  font-weight: 700; margin-right: 4px; margin-bottom: 2px;
}
.badge.hot { background: rgba(255,77,109,0.15); color: var(--hot); }
.badge.rising { background: rgba(77,171,255,0.15); color: var(--rising); }
.badge.small { background: rgba(255,209,102,0.18); color: var(--small); }
.note { display: inline-block; font-size: 11px; color: var(--muted); background: var(--panel-2);
  border-radius: 8px; padding: 2px 7px; margin: 1px 3px 1px 0; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
"""


def _row_html(i: int, v, delay_step: float = 0.015) -> str:
    badges = f'<span class="badge hot">HOT</span>' if v.bucket == "HOT" else f'<span class="badge rising">RISING</span>'
    if v.is_small_channel_big_views:
        badges += '<span class="badge small">🚀 SMALL→BIG</span>'

    notes_html = "".join(f'<span class="note">{_esc(n)}</span>' for n in v.style_notes)
    vps = v.views_per_subscriber
    vps_str = f"{vps:.1f}×" if vps is not None else "—"

    return f"""<tr style="animation-delay:{i * delay_step:.3f}s">
  <td class="num">{i + 1}</td>
  <td><a href="{v.url}" target="_blank" rel="noopener">{_esc(v.title)}</a><br>{badges}</td>
  <td>{_esc(v.channel)}</td>
  <td class="num">{_fmt_num(v.views)}</td>
  <td class="num">{_fmt_num(v.subscriber_count)}</td>
  <td class="num">{vps_str}</td>
  <td class="num">{_fmt_num(round(v.velocity))}/ч</td>
  <td class="num">{v.engagement_rate * 100:.1f}%</td>
  <td>{notes_html or "—"}</td>
</tr>"""


def build_trends_html(videos: list, title: str = "Тренды YouTube — русский сегмент стриминга") -> str:
    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    hot = [v for v in videos if v.bucket == "HOT"]
    rising = [v for v in videos if v.bucket == "RISING"]
    small = sorted(
        [v for v in videos if v.is_small_channel_big_views],
        key=lambda v: (v.views_per_subscriber or 0), reverse=True
    )

    small_section = ""
    if small:
        rows = "".join(_row_html(i, v) for i, v in enumerate(small[:25]))
        small_section = f"""
<section>
  <h2><span class="pulse-dot"></span>🚀 Маленькие каналы, но большие просмотры ({len(small)})</h2>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>#</th><th>Видео</th><th>Канал</th><th class="num">Просмотры</th>
        <th class="num">Подписчики</th><th class="num">Просм./Подп.</th>
        <th class="num">Скорость</th><th class="num">Вовлечён.</th><th>Заметки по подаче</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</section>"""

    all_rows = "".join(_row_html(i, v) for i, v in enumerate(videos))

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head><body>
<h1>{_esc(title)}</h1>
<div class="meta">Сформировано: {now_str} · только русский сегмент · глубина поиска 72ч</div>

<div class="stat-row">
  <div class="stat"><b>{len(videos)}</b>всего проанализировано</div>
  <div class="stat hot"><b>{len(hot)}</b>🔥 HOT</div>
  <div class="stat rising"><b>{len(rising)}</b>📈 RISING</div>
  <div class="stat small"><b>{len(small)}</b>🚀 маленький канал → большие просмотры</div>
</div>
{small_section}
<section>
  <h2><span class="pulse-dot"></span>Полная таблица ({len(videos)} позиций, сортировка по скорости роста)</h2>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>#</th><th>Видео</th><th>Канал</th><th class="num">Просмотры</th>
        <th class="num">Подписчики</th><th class="num">Просм./Подп.</th>
        <th class="num">Скорость</th><th class="num">Вовлечён.</th><th>Заметки по подаче</th>
      </tr></thead>
      <tbody>{all_rows}</tbody>
    </table>
  </div>
</section>
</body></html>"""
