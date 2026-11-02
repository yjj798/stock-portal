# -*- coding: utf-8 -*-
"""简报页 /brief —— 指数收盘 + 未来事件日历 + 多空基调（原 gh-pages brief.html 的浅色重做）。

这一页的价值只有一块是不可替代的：**未来事件日历**。
指数收盘本站别处也有、多空基调是弱信号，但「下周有什么」算不出来，
只能靠外部简报源。

数据性质必须写在页面上（否则读者会把它当行情数据用）：
源是 jixiangying/finance-auto-gen 的 **AI 生成**早晚报，
指数点位可以与行情接口对拍，事件日历只能人工核。所以页脚与卡片都在标出处。
"""
from __future__ import annotations

from datetime import date

from .components import card, empty, esc, pct_span, rnd, signed, table, td, trim
from .shell import footer, page

# 展示顺序：A 股 → 港股 → 美股。不按字母、不按涨跌幅，固定顺序才不会每次看都换位置
ORDER = ["上证指数", "深证成指", "创业板指", "科创50", "沪深300",
         "恒生指数", "恒生科技", "道琼斯", "标普500", "纳斯达克"]

EXTRA_CSS = """
<style>
.ixg{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.ix{background:var(--soft2);border:1px solid var(--line);border-radius:10px;padding:11px 13px}
.ix .k{font-size:11.5px;color:var(--muted)}
.ix .v{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums;margin-top:3px}
.ix .p{font-size:12px;font-variant-numeric:tabular-nums;margin-top:2px}
.ix .d{font-size:10.5px;color:var(--muted);margin-top:2px}
@media(max-width:900px){.ixg{grid-template-columns:repeat(2,1fr)}}
.ev-day{display:inline-block;min-width:82px;font-variant-numeric:tabular-nums}
.ev-left{font-size:11px;color:var(--tag2ck);background:var(--tag2bg);border-radius:4px;
  padding:0 6px;margin-left:6px}
.tone-bar{display:flex;height:10px;border-radius:6px;overflow:hidden;margin:10px 0 6px}
.tone-bar i{display:block;height:100%}
</style>
"""


def _index_grid(ix) -> str:
    if not ix:
        return empty("最新一篇里没有解析到指数点位。")
    cells = []
    for name in ORDER:
        x = ix.get(name)
        if not x:
            continue
        pct = x.get("pct")
        p = pct_span(pct) if pct is not None else '<span class="sub">无涨跌幅</span>'
        cells.append('<div class="ix"><div class="k">%s</div>'
                     '<div class="v">%s</div><div class="p">%s</div>'
                     '<div class="d">%s</div></div>'
                     % (esc(name), trim(x.get("close"), 2), p, esc(x.get("as_of") or "")))
    # 源里可能还有本表没列的指数，补在最后而不是丢掉
    for name, x in ix.items():
        if name in ORDER:
            continue
        pct = x.get("pct")
        cells.append('<div class="ix"><div class="k">%s</div><div class="v">%s</div>'
                     '<div class="p">%s</div><div class="d">%s</div></div>'
                     % (esc(name), trim(x.get("close"), 2),
                        pct_span(pct) if pct is not None else '<span class="sub">—</span>',
                        esc(x.get("as_of") or "")))
    return '<div class="ixg">%s</div>' % "".join(cells)


def _events(evs) -> str:
    if not evs:
        return empty("简报里没有解析到未来事件——可能是最新一篇为周末/节假日版，"
                     "或事件写法超出解析规则（见 brief_parse.parse_events）。")
    today = date.today()
    rows = []
    for e in evs:
        try:
            d = date.fromisoformat(e["date"])
            left = (d - today).days
        except Exception:
            left = None
        tag = ""
        if left is not None:
            tag = ('<span class="ev-left">%s</span>'
                   % ("今天" if left == 0 else ("%d 天后" % left)))
        rows.append("<tr>%s%s%s</tr>" % (
            td('<span class="ev-day">%s</span>%s' % (esc(e["date"]), tag), left=True),
            td(esc(e.get("title") or ""), left=True),
            td('<span class="sub">%s</span>' % esc(e.get("from") or ""), left=True)))
    return table(["日期", "事件", "出处"], "".join(rows), "l l l")


def _tone(t) -> str:
    bull, bear = int(t.get("bull") or 0), int(t.get("bear") or 0)
    tot = bull + bear
    if not tot:
        return empty("最新一篇里没有出现多空情绪词。")
    bp = bull / tot * 100
    skew = t.get("skew") or 0
    mood = ("偏多" if skew >= 30 else "偏空" if skew <= -30 else "中性")
    return ('<div class="tone-bar"><i style="width:%.1f%%;background:var(--up)"></i>'
            '<i style="width:%.1f%%;background:var(--down)"></i></div>'
            '<div class="kv"><div><span>看多词</span><b class="red">%d</b></div>'
            "<div><span>看空词</span><b class=\"green\">%d</b></div>"
            "<div><span>基调</span><b>%s（%s）</b></div></div>"
            '<div class="ln" style="margin-top:10px">这是对摘要区做<b>词频统计</b>的粗指标'
            "（看多词 %d 个 / 看空词 %d 个），不是观点。它只能说明这篇的语气，"
            "不能说明持仓该怎么摆——AI 写稿的用词习惯会让它系统性偏某一边。</div>"
            % (bp, 100 - bp, bull, bear, esc(mood), signed(skew, 1), bull, bear))


def _reports(rs) -> str:
    if not rs:
        return empty("没有抓到任何简报篇目。")
    rows = []
    for r in rs[:12]:
        rows.append("<tr>%s%s%s%s%s</tr>" % (
            td(esc(r.get("date") or ""), "sub"),
            td('<span class="tag">%s</span>' % ("晚报" if r.get("session") == "evening" else "早报")),
            td(esc(r.get("title") or "")[:78], left=True),
            td("%d 个" % len(r.get("indices") or {})),
            td("%d 条" % len(r.get("events") or []))))
    return table(["日期", "场次", "标题", "指数", "事件"], "".join(rows), "l l l r r")


def render(br=None) -> str:
    if not br:
        body = card("简报", empty(
            "还没有简报快照（data/live/brief.json）。跑一次 python refresh.py，"
            "它会抓最近几天的早晚报并解析。"))
        return page("简报", "/brief", body,
                    tail=footer("数据源：jixiangying/finance-auto-gen（AI 生成，仅作叙事参考）",
                                "本页只做汇总展示，不构成投资建议。"))

    latest = br.get("latest") or {}
    day = latest.get("date") or "—"
    sess = "晚报" if latest.get("session") == "evening" else "早报"
    head = ('<div class="hero"><div class="eyebrow">简报 · %s %s</div>'
            '<div class="hd"><h1>%s</h1>'
            '<span class="c">%d 篇已解析 · 未来事件 %d 条 · 源：finance-auto-gen（AI 生成）</span>'
            "</div></div>"
            % (esc(day), esc(sess), esc(latest.get("title") or "—"),
               len(br.get("reports") or []), len(br.get("events") or [])))

    body = "".join([
        head,
        card("指数收盘<span>点位与涨跌幅抽自简报原文，涨红跌绿</span>",
             _index_grid(br.get("indices") or {})),
        card("未来事件日历<span>只留今天及以后的日子 · 事件源不可替代</span>",
             _events(br.get("events") or [])),
        card("多空基调<span>摘要区词频，弱信号</span>", _tone(br.get("tone") or {})),
        card("最近篇目<span>点标题看不到全文——原文在源仓库，本站只做结构化</span>",
             _reports(br.get("reports") or [])),
        card("口径说明", (
            '<div class="dv-detail">'
            "<b>这个源是 AI 生成的复盘早晚报，不是行情数据。</b>"
            "本站只用它三样：指数收盘（可与行情接口对拍）、未来事件日历（本站算不出来）、"
            "多空词频（弱背景）。<br>"
            "指数用「指数名 → 就近 40 字内出现 N 点」配对，并排除「沪指险失 3600 点」"
            "这类关口描述——按句取第一个数字会把整句的涨跌幅配错，这是第一版踩过的坑。<br>"
            "事件日历取最近 6 篇的并集，且只保留日期 ≥ 今天：旧篇里已过去的事件自然淘汰，"
            "新篇没提到的旧事件也不会被硬留下来。<br>"
            "多空基调是摘要区的<b>词频</b>，不是编辑观点，更不是仓位建议。"
            "源换了文风，这个数就会整体漂移。"
            "</div>")),
    ])
    return page("简报 · %s" % day, "/brief", body,
                extra_head=EXTRA_CSS,
                tail=footer("数据源：jixiangying/finance-auto-gen（AI 生成，仅作叙事参考）"
                            "· 指数点位可与行情接口对拍，事件日历请以官方公告为准",
                            "本页只做汇总展示，不构成投资建议。"))
