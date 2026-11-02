# -*- coding: utf-8 -*-
"""通用渲染件：数与金额格式化、转义、涨跌标色、SVG 折线、表格/卡片外壳。

全部纯函数，不读盘不联网，方便单测。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------- 数与文本
def esc(s) -> str:
    """HTML 转义。个股名/板块名会出现 & < > " 等字符。"""
    return (str("" if s is None else s)
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def num(v, d=0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return d
    return f if math.isfinite(f) else d


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def rnd(v, d=0):
    """对齐 JS 的 Math.round：四舍五入（.5 向上）。
    Python 内置 round() 是银行家舍入（22.5→22），与线上页面对拍会差 1 分，
    所以这里必须自己实现，不能图省事用 round()。"""
    p = 10 ** d
    x = num(v) * p
    n = math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)
    val = n / p
    return int(val) if d == 0 else val


def trim(x, d=1) -> str:
    """按 JS 的数字习惯输出：49.0 → "49"，1.40 → "1.4"（不补零、不留小数点）。
    直接 str(float) 会出 "49.0"，与线上页面并排比会显得不一致。"""
    s = ("%." + str(d) + "f") % rnd(x, d)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def signed(v, d=2) -> str:
    n = rnd(v, d)
    s = trim(n, d)
    return ("+" if num(n) > 0 else "") + s


def yi(v) -> str:
    """金额口径与 d 站一致：万亿/亿/万/整数。"""
    v = num(v, None)
    if v is None or v == 0:
        return "—"
    a = abs(v)
    if a >= 1e12:
        return "%s 万亿" % rnd(v / 1e12, 2)
    if a >= 1e10:
        return "%s 亿" % rnd(v / 1e8, 0)
    if a >= 1e8:
        return "%s 亿" % rnd(v / 1e8, 2)
    if a >= 1e4:
        return "%s 万" % rnd(v / 1e4, 0)
    return str(rnd(v, 0))


def bj_time(iso) -> str:
    """ISO 时间 → 北京时间字符串。解析不了就原样返回。"""
    if not iso:
        return "—"
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(CST).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(iso)


# ---------------------------------------------------------------- 颜色
def temp_color(score) -> str:
    s = num(score)
    if s >= 70:
        return "#d9363e"
    if s >= 55:
        return "#e8804a"
    if s >= 45:
        return "#c9a227"
    if s >= 30:
        return "#3f9d76"
    return "#12a35c"


def pct_span(v) -> str:
    if v is None:
        return ""
    cls = "red" if num(v) >= 0 else "green"
    return '<b class="%s">%s%%</b>' % (cls, signed(v, 1))


# ---------------------------------------------------------------- 组件
def card(title: str, body: str, sub: str = "") -> str:
    h = '<h2>%s' % title
    if sub:
        h += "<span>%s</span>" % sub
    return '<div class="card">%s</h2>%s</div>' % (h, body)


def table(headers, rows_html: str, aligns=None, empty: str = "暂无数据", span=None) -> str:
    """headers: ["板块","涨停"]；aligns: "l r r"（l=左对齐）。"""
    al = (aligns or "").split()
    ths = []
    for i, h in enumerate(headers):
        cls = ' class="l"' if i < len(al) and al[i] == "l" else ""
        ths.append("<th%s>%s</th>" % (cls, esc(h)))
    if not rows_html:
        rows_html = '<tr><td colspan="%d" class="empty">%s</td></tr>' % (
            span or len(headers), esc(empty))
    return ('<div class="tscroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
            % ("".join(ths), rows_html))


def td(v, cls="", left=False):
    c = []
    if left:
        c.append("l")
    if cls:
        c.append(cls)
    attr = ' class="%s"' % " ".join(c) if c else ""
    return "<td%s>%s</td>" % (attr, v)


def grid4(cells) -> str:
    """cells: [(k, v_html, n_html)]，不足 4 个自动补齐。"""
    out = []
    for k, v, n in cells[:4]:
        out.append('<div class="cell"><div class="k">%s</div><div class="v">%s</div>'
                   '<div class="n">%s</div></div>' % (esc(k), v, n))
    return '<div class="grid4">%s</div>' % "".join(out)


def warn(html: str) -> str:
    return '<div class="warn">%s</div>' % html


def tabset(set_id: str, items, active: str = "", base: str = "/",
           param: str = "t") -> str:
    """页内分栏：items = [(key, 标签, 角标, 面板 html), ...]，第一个是默认栏。

    为什么用「真实 href + 服务端定 active」而不是纯前端隐藏：
    复盘页/榜单页都会有人从收藏夹、微信里点进来，也有浏览器插件禁用 JS。
    真实链接保证这些情况下照样能切、刷新停在原栏、后退回上一栏；
    脚本只负责把整页刷新降级成原地切换（见 theme.PAGE_JS）。

    active 落空（别人手改 ?t=xxx）时退回第一栏，不白屏。
    """
    items = list(items)
    keys = [x[0] for x in items]
    act = active if active in keys else (keys[0] if keys else "")
    bar = []
    for k, label, note, _html in items:
        cls = ' class="on"' if k == act else ""
        tail = ("<i>%s</i>" % esc(note)) if note else ""
        bar.append('<a%s href="%s?%s=%s" data-k="%s">%s%s</a>'
                   % (cls, esc(base), esc(param), esc(k), esc(k), esc(label), tail))
    panes = []
    for k, _label, _note, html in items:
        panes.append('<section class="tp%s" data-k="%s">%s</section>'
                     % (" on" if k == act else "", esc(k), html))
    return ('<div class="tabsbox" data-tabs="%s"><div class="tabs2">%s</div>'
            '<div class="tpanes">%s</div></div>'
            % (esc(set_id), "".join(bar), "".join(panes)))


def empty(text="暂无数据") -> str:
    return '<div class="empty">%s</div>' % esc(text)


# ---------------------------------------------------------------- SVG 折线
def line_chart(rows, key, color, unit="", w=640, h=150, invert=False) -> str:
    """纯 SVG 折线，零依赖。invert=True 时 Y 轴倒置（用于"排名"这种越小越好的指标）。"""
    if not rows:
        return ""
    vals = [num(r.get(key), None) for r in rows]
    vals = [v for v in vals if v is not None]
    if not vals:
        return ""
    mn, mx = min(vals), max(vals)
    if mn == mx:
        mn, mx = mn - 1, mx + 1
    pad = (mx - mn) * 0.12
    mn, mx = mn - pad, mx + pad

    PL, PR, PT, PB = 34, 12, 12, 24
    iw, ih = w - PL - PR, h - PT - PB
    n = len(rows)

    def px(i):
        return PL + iw / 2 if n == 1 else PL + i / (n - 1) * iw

    def py(v):
        t = (v - mn) / (mx - mn)
        return PT + (t if invert else 1 - t) * ih

    pts = []
    for i, r in enumerate(rows):
        v = num(r.get(key), None)
        if v is not None:
            pts.append((px(i), py(v)))
    if not pts:
        return ""

    d = "".join(("%s%.1f %.1f " % ("M" if i == 0 else "L", x, y))
                for i, (x, y) in enumerate(pts))
    area = ""
    if len(pts) > 1:
        area = (d + "L%.1f %.1f L%.1f %.1f Z"
                % (pts[-1][0], PT + ih, pts[0][0], PT + ih))

    tick_vals = [mx, (mx + mn) / 2, mn]
    grid = ""
    for tv in tick_vals:
        y = py(tv)
        grid += ('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" style="stroke:var(--track)"/>'
                 % (PL, y, w - PR, y))
        grid += ('<text x="%d" y="%.1f" font-size="10" text-anchor="end" style="fill:var(--muted)">%s</text>'
                 % (PL - 6, y + 3.5, rnd(tv, 0)))

    r = 1.6 if n > 30 else 2.8
    dots = "".join('<circle cx="%.1f" cy="%.1f" r="%s" fill="%s"/>' % (x, y, r, color)
                   for x, y in pts)

    last_v = num(rows[-1].get(key), None)
    lbl = ""
    if last_v is not None:
        lbl = ('<text x="%d" y="%d" font-size="11" text-anchor="end" style="fill:var(--muted)">最新 %s%s</text>'
               % (w - PR, PT - 1, rnd(last_v, 1), unit))
    x1 = ('<text x="%d" y="%d" font-size="10" style="fill:var(--muted)">%s</text>'
          % (PL, h - 6, esc(str(rows[0].get("date", ""))[5:])))
    x2 = ""
    if n > 1:
        x2 = ('<text x="%d" y="%d" font-size="10" text-anchor="end" style="fill:var(--muted)">%s</text>'
              % (w - PR, h - 6, esc(str(rows[-1].get("date", ""))[5:])))

    return ('<svg viewBox="0 0 %d %d" preserveAspectRatio="none" style="height:150px">'
            '<path d="%s" fill="%s" opacity="0.07"/>%s'
            '<path d="%s" fill="none" stroke="%s" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
            '%s%s%s%s</svg>') % (w, h, area, color, grid, d, color, dots, lbl, x1, x2)


# ---------------------------------------------------------------- 排名历史柱条
def rank_tier_color(r) -> str:
    """名次分档色（z.legaga.top 同款语义：越靠前越红热，越靠后越灰冷）。
    两个主题都用这套中间亮度色——在浅底和深底上都有足够对比度。"""
    r = num(r, 9999)
    if r <= 3:
        return "#e23c3e"
    if r <= 10:
        return "#f0854d"
    if r <= 30:
        return "#e0b23c"
    if r <= 60:
        return "#3f9d76"
    if r <= 120:
        return "#4f83f1"
    return "#7b8493"


def rank_bars(rows, w=520, h=76, key="rank", show_n=True) -> str:
    """排名历史柱条：一根柱一个交易日，柱高＝名次（第 1 名最高，倒置），
    颜色按名次分档，柱下标名次数字。纯 SVG 零依赖。

    这是 z.legaga.top 排行榜「排名历史」列的同款形态：一眼看出
    「一路往前冲」（红柱逐日变高）还是「热度退了」（彩色变灰变矮）。
    """
    pairs = []
    for r in rows or []:
        v = num(r.get(key), None)
        if v is not None:
            pairs.append((str(r.get("date") or ""), num(v)))
    if not pairs:
        return ""
    mx = max(v for _, v in pairs)
    inner = h - 16                      # 底部留 16px 给名次数字
    bw = w / len(pairs)
    bar_w = min(bw - 2.0, 15.0)
    parts = ['<svg viewBox="0 0 %d %d" style="height:%dpx" class="rbars">' % (w, h, h)]
    for i, (d, v) in enumerate(pairs):
        x = i * bw + (bw - bar_w) / 2.0
        bh = max(4.0, (mx - v + 1.0) / mx * inner)
        parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="%s"/>'
                     % (x, inner - bh, bar_w, bh, rank_tier_color(v)))
        if show_n and bar_w >= 9:
            parts.append('<text x="%.1f" y="%d" font-size="8.5" text-anchor="middle" '
                         'style="fill:var(--muted)">%d</text>' % (x + bar_w / 2.0, h - 4, rnd(v)))
    parts.append("</svg>")
    # 首尾日期，让"32 根柱是哪段时间"不用猜
    if len(pairs) > 1 and pairs[0][0] and pairs[-1][0]:
        parts.append('<div class="sub" style="margin-top:2px">%s → %s（%d 个交易日）</div>'
                     % (esc(pairs[0][0][5:]), esc(pairs[-1][0][5:]), len(pairs)))
    return "".join(parts)
