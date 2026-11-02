# -*- coding: utf-8 -*-
"""驱动词页 /drivers —— 「为什么涨」的逐股归因 + 主线聚类。

数据来自 reasons_core 抓的同花顺逐股异动（keywordList + reason），
口径与旧 d 站「涨停驱动词 TOP20」同源，但这里是全量（不截 20）。

三个结论用词有严格定义，不能混：
    · 广度线 = 成员最多的**具体**驱动词（剔泛词）——钱扎堆的地方
    · 高度线 = 撑起**最高连板**的那个词——决定次日风向标归属
    · 暗线   = 55188 板块榜里查不到的具体词——游资抱团但站外看不见

为什么不做「热度环比」：本站只有当天一份快照，没有历史序列，
任何「比昨天更热」的说法都无从验证。驱动词只能讲**今天谁被什么解释**。
"""
from __future__ import annotations

import reasons_core
from .components import card, empty, esc, table, td
from .shell import footer, page


def _board_tag(b) -> str:
    b = int(b or 1)
    if b <= 1:
        return '<span class="tag">首板</span>'
    return '<span class="%s">%d 板</span>' % ("tag n" if b >= 3 else "tag", b)


def _kw_chips(words, limit=4) -> str:
    ws = [w for w in (words or []) if w][:limit]
    if not ws:
        return '<span class="sub">无驱动词</span>'
    return "".join('<span class="chip">%s</span>' % esc(w) for w in ws)


def _line_broad(b) -> str:
    tail = "是今天最有共识的一条线。" if b["count"] >= 4 else "只数不算多，共识偏弱。"
    return "<b>%s</b>：%d 只涨停票用它解释，最高 %d 板。%s" % (
        esc(b["keyword"]), b["count"], b["max_board"], tail)


def _line_high(h, same) -> str:
    if same:
        return ("广度线与高度线是同一条（<b>%s</b>），说明这条线既有宽度又有高度，"
                "这种结构最扎实。" % esc(h["keyword"]))
    return ("<b>%s</b>：撑起 %d 板最高标。次日风向标看这条线的接力，"
            "不看涨停家数。" % (esc(h["keyword"]), h["max_board"]))


def _line_hidden(hid) -> str:
    if not hid:
        return "今日没有「站外看不见」的独立题材——具体驱动词都能在板块榜里找到对应行业。"
    names = "、".join("<b>%s</b>（%d 只）" % (esc(d["keyword"]), d["count"]) for d in hid)
    return ("以下具体词在 55188 板块榜里<b>查不到</b>，属游资自造题材、站外看不见：%s。" % names)


def _sec_summary(rd) -> str:
    """三句话结论。每一句都能回溯到 drivers 里的一个字段，没有数据就不输出。"""
    sm = reasons_core.summarize(rd, top=6)
    if not sm:
        return empty("这份缓存里没有驱动词聚类结果。")
    cov = sm["coverage"]
    b, h, hid = sm["broad"], sm["high"], sm["hidden"]
    same = bool(b and h and b["keyword"] == h["keyword"])

    items = []
    if b:
        items.append(("广度线", _line_broad(b)))
    if h:
        items.append(("高度线", _line_high(h, same)))
    items.append(("暗线", _line_hidden(hid)))

    body = "".join(
        '<div class="nar-i"><div class="nar-n">%d</div><div>'
        '<div class="nar-t">%s</div><div class="nar-v">%s</div></div></div>'
        % (i, esc(k), v) for i, (k, v) in enumerate(items, 1))
    return ('<div class="dv-cov">驱动词覆盖 <b>%d/%d</b>（%.0f%%）· '
            "过期跳过 %d 条（同一天没再异动的票抓到的上次记录，不予采信）</div>%s"
            % (cov["hit_same_day"], cov["pool"], cov["rate"],
               cov.get("stale_skipped") or 0, body))


def _kw_table(rd) -> str:
    ds = rd.get("drivers") or []
    if not ds:
        return empty("没有驱动词。")
    rows = []
    for i, d in enumerate(ds, 1):
        tags = []
        if d.get("generic"):
            tags.append('<span class="tag">泛词·降权</span>')
        elif not d.get("in_sector_view") and d["count"] >= 2:
            tags.append('<span class="tag n">暗线</span>')
        elif d.get("in_sector_view"):
            tags.append('<span class="sub">板块榜已有</span>')
        names = "".join('<a class="chip" href="/s/%s">%s</a>' % (esc(s["code"]), esc(s["name"]))
                        for s in (d.get("stocks") or [])[:8])
        more = len(d.get("stocks") or []) - 8
        if more > 0:
            names += '<span class="sub">等 %d 只</span>' % more
        rows.append("<tr>%s%s%s%s%s</tr>" % (
            td(str(i), "sub"),
            td("<b>%s</b>" % esc(d["keyword"]), left=True),
            td("%d 只" % d["count"]),
            td(_board_tag(d["max_board"])),
            td(names + " " + " ".join(tags), left=True)))
    return table(["#", "驱动词", "成员", "最高", "成分股 / 标记"],
                 "".join(rows), "r l r r l")


def _stock_table(rd) -> str:
    recs = sorted(rd.get("records") or [],
                  key=lambda r: (-int(r.get("board") or 1), r.get("code") or ""))
    if not recs:
        return empty("没有逐股异动记录。")
    rows = []
    for r in recs:
        reason = (r.get("reason") or "").strip()
        first = reason.split("\n")[0][:60] if reason else ""
        cell = ('<span style="color:var(--t3);font-size:11.5px">%s</span>' % esc(first)
                if first else '<span class="sub">—</span>')
        rows.append(
            '<tr><td class="l"><a class="sl" href="/s/%s">%s</a>'
            '<span class="sub"> %s</span></td>%s%s%s</tr>' % (
                esc(r["code"]), esc(r["name"]), esc(r["code"]),
                td(_board_tag(r.get("board"))),
                td(_kw_chips(r.get("keywords")), left=True),
                td(cell, left=True)))
    return table(["股票", "板数", "驱动词（同花顺 keywordList）", "异动原因首句"],
                 "".join(rows), "l r l l")


def render(data=None, meta=None, rd=None) -> str:
    rd = rd or {}
    day = rd.get("trade_date") or "—"
    ds = rd.get("drivers") or []
    n_spec = sum(1 for d in ds if not d.get("generic"))
    n_dark = sum(1 for d in ds if not d.get("generic")
                 and not d.get("in_sector_view") and d["count"] >= 2)

    if not rd:
        body = card("驱动词", empty(
            "还没有驱动词缓存。在工程目录跑一次 python refresh.py，"
            "它会顺带抓当天涨停股的异动原因并聚类。"))
        return page("驱动词", "/drivers", body,
                    tail=footer("数据源：同花顺逐股异动 dq.10jqka.com.cn",
                                "本页只做汇总展示，不构成投资建议。"))

    head = ('<div class="hero"><div class="eyebrow">驱动词 · %s</div>'
            '<div class="hd"><h1>今天为什么涨</h1>'
            '<span class="c">%d 个驱动词 · 具体 %d 个 · 暗线 %d 个 · '
            "覆盖 %d 只涨停股的异动原因</span></div></div>"
            % (esc(day), len(ds), n_spec, n_dark, len(rd.get("records") or [])))

    body = "".join([
        head,
        card("三句话结论<span>广度 / 高度 / 暗线 —— 每句都能回溯到一条记录</span>",
             _sec_summary(rd)),
        card("驱动词聚类<span>按「只数 + 最高板×0.5」排序，泛词权重 0.35</span>",
             _kw_table(rd)),
        card("逐股异动原因<span>%d 只 · 首句预览，全文点股票进详情页</span>"
             % len(rd.get("records") or []), _stock_table(rd)),
        card("口径说明", (
            '<div class="dv-detail">'
            "数据来自同花顺逐股异动接口（dq.10jqka.com.cn），字段 <b>keywordList</b> 是"
            "「个股驱动」维度，比 55188 的行业板块细一级：同一只票 55188 只标「大消费」，"
            "这里能给到「青啤拟入主」。<br>"
            "该接口<b>每股只保留最近一次异动</b>，不能回看历史。所以："
            "①只采信 <b>date == 当日</b> 的记录，抓到几天前的一律丢弃（见上方「过期跳过」）；"
            "②序列只能每日采集逐日沉淀，事后补不回来。<br>"
            "<b>泛词</b>（三季报增长 / 国企改革 / 回购 / 超跌反弹等）指不向具体产业，"
            "聚类打分权重降到 0.35，也不参与「暗线」判定——它们数量最多、解释力最弱，谁都能挂。<br>"
            "<b>暗线</b>＝在 55188 板块榜里查不到的具体词。它不是「更好的题材」，"
            "只是「站外看不见」，往往意味着盘子小、靠游资，波动也更大。<br>"
            "本页只讲今天谁被什么解释，<b>不做热度环比</b>——只有当天一份快照、"
            "没有历史序列，任何「比昨天更热」的说法都无从验证。"
            "</div>")),
    ])
    return page("驱动词 · %s" % day, "/drivers", body,
                tail=footer("数据源：同花顺逐股异动（dq.10jqka.com.cn/fuyao/transaction_history）"
                            "· 板块口径对照 55188",
                            "本页只做汇总展示，不构成投资建议。"))
