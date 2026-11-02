# -*- coding: utf-8 -*-
"""主线页 /theme —— 行业与概念之上的那一层：今天到底在炒哪条消息。

为什么需要这一页（用户 2026-11-02）
------------------------------------
"AI 短剧、AI 漫剧、AI 视频、出版传媒……其实是同一条消息，你把它们分成十几个
细支，概念就分散了，集中度在细支里体现不出来。就像机器人——马斯克一句话带动
整条链；羊字辈就是过羊年。归因能归到一条消息，才能判断这波还有多高。"

实测当天池内 140 只票、401 个标签，同一条消息被拆成 17 个名字，最大的"短剧游戏"
只有 8 只、最小的只有 1 只。逐个看，谁都像小概念；并起来是 30 只、涨停 19 只。

所以本页回答三个问题：
    ① 今天有几条主线，哪条最强（热度分 + 涨停 + 高度）
    ② 每条主线是哪些细支并起来的（证据链，标出各自几只）
    ③ 这条主线的逻辑是什么、成员是谁、落在哪些行业

⚠️ `catalyst` 是人工整理的题材逻辑，不是抓来的新闻原文。本项目没接新闻源，
   所以页面明确写"消息面由细支共振反推"，不让读者误以为是新闻抓取。
"""
from __future__ import annotations

import news as news_mod
import score as scoring
from .components import card, empty, esc, num, signed, table, td

TIER_CLS = {"强": "tag n", "中": "tag", "弱": "tag"}


def _load_attr(data) -> dict:
    """涨停池（东财）单独存在 attr.json，不在 bundle 里——关键词榜要它判"其中几只涨停"。
    读不到就算了，news.build 会用 bundle 里的 limit_up/board_tag 兜底。"""
    try:
        import store
        at, _ = store.load_attr()
        return at or {}
    except Exception:  # noqa: BLE001
        return {}


def _score_cell(r) -> str:
    sub = r.get("sub") or {}
    bits = " · ".join("%s %.0f" % (k, num(v)) for k, v in
                      (("涨停", sub.get("lu")), ("广度", sub.get("up")),
                       ("人气", sub.get("heat")), ("赚钱", sub.get("rise")),
                       ("龙头", sub.get("lead"))) if v is not None)
    return ('<b class="big">%s</b><div class="sub">%s</div>'
            % ("%.1f" % r["total"], esc(bits)))


def _pct_cell(v) -> str:
    if v is None:
        return '<span class="sub">—</span>'
    return '<b class="%s">%s%%</b>' % ("red" if num(v) >= 0 else "green", signed(v, 2))


def _main_table(rows) -> str:
    trs = []
    for r in rows:
        best = (r.get("blocks") or [{}])[0]
        trs.append("<tr>%s%s%s%s%s%s%s%s%s</tr>" % (
            td('<span class="rk%s">%d</span>'
               % (" t1" if r["rank"] == 1 else (" t2" if r["rank"] == 2 else
                                                (" t3" if r["rank"] == 3 else "")), r["rank"])),
            td('<b>%s</b><div class="sub">%s</div>'
               % (esc(r["name"]), esc(r.get("short") or "")), left=True),
            td('<b class="%s">%s</b>' % ("red" if r["total"] >= 80 else "", "%.1f" % r["total"])),
            td("%d<span class=\\\"sub\\\"> 只</span>" % r.get("n", 0)),
            td('<span class="tag n">%d</span>' % r["lu"] if r["lu"] else '<span class="sub">0</span>'),
            td("%d 板" % r["max_board"] if r.get("max_board") else '<span class="sub">—</span>'),
            td(_pct_cell(r.get("avgpct"))),
            td(esc(r.get("best_name") or "—"), left=True),
            td(('<b class="%s">%s %s%%</b>'
                % ("red" if num(best.get("pct")) >= 0 else "green",
                   esc(best.get("name") or ""), signed(best.get("pct"), 2)))
               if best.get("pct") is not None else '<span class="sub">—</span>', left=True),
        ))
    return table(["#", "主线（消息面）", "热度分", "成员", "涨停", "最高", "成员均涨",
                  "龙头", "关联最强板块"], "".join(trs), "l l r r r r r l l")


def _evidence(r) -> str:
    ts = r.get("tags") or []
    if not ts:
        return ""
    chips = "".join(
        '<span class="chip"%s>%s<span class="sub"> %d</span></span>'
        % (' style="border-color:#d9534f"' if i == 0 else "", esc(t["tag"]), t["n"])
        for i, t in enumerate(ts[:14]))
    more = len(ts) - 14
    if more > 0:
        chips += '<span class="sub"> 等 %d 个细支</span>' % more
    merged = ('合并前是 <b>%d</b> 个细支，最大的那个只有 <b>%d</b> 只；'
              "并成一条主线后 <b>%d</b> 只、涨停 <b>%d</b> 只。"
              % (len(ts), ts[0]["n"] if ts else 0, r.get("n", 0), r.get("lu", 0)))
    return ('<div class="kv" style="margin:10px 0 6px"><div><span>证据链（同一条消息的细支）</span>'
            "<b>%s</b></div></div><div class=\"tags\">%s</div>"
            '<div class="sub" style="margin-top:6px">%s</div>' % (merged, chips, ""))


def _name_map(data, nw) -> dict:
    """代码 → 名字：人气池 → 涨停池 → 异动解析 stockName，三级兜底。"""
    d = {c: (e.get("name") or "") for c, e in ((data or {}).get("stocks") or {}).items()}
    for x in ((data or {}).get("zt_pool") or []):
        c = str(x.get("code") or "")
        d[c] = d.get(c) or (x.get("name") or "")
    for c, v in ((data or {}).get("abnormal") or {}).items():
        d[c] = d.get(c) or (v.get("stock_name") or "")
    return d


def _kw_table(nw, limit: int = 24, names=None, linkable=None) -> str:
    """消息面关键词榜：每个词挂了几只票、其中几只涨停、归到哪条主线。

    这张表是"同一条消息"的直接证据：AI短剧 9 只、AI漫剧 9 只、微短剧 5 只、
    AI影视 4 只——单看每个词都不大，四个词合成一条 AI 视频线就是 42 只。
    """
    rows = [r for r in (nw.get("keywords") or []) if r["n"] >= 2]
    if not rows:
        return card("今日关键词<span>来自异动解析</span>",
                    empty("今天没抓到带关键词的异动解析——先跑一次 refresh.py。"))
    trs = []
    for i, r in enumerate(rows[:limit], 1):
        pcts = r.get("avg_pct")
        # 只给"有页可点"的票加链接：热榜/龙虎榜里既不在池、今天也没涨停的票
        # 点开只有占位页，不如老老实实显示名字。
        nm_list = [(('<a class="sl" href="/s/%s">%s</a>' % (esc(c), esc(n or c)))
                    if (linkable is None or c in linkable) else esc(n or c))
                   for c, n in zip(r["codes"], r["names"])]
        nm = "、".join(nm_list[:4])
        more = len(nm_list) - 4
        if more > 0:
            nm += ' <span class="sub">等 %d 只</span>' % more
        trs.append("<tr>%s%s%s%s%s</tr>" % (
            td("%d" % i),
            td('<b>%s</b>' % esc(r["kw"]), left=True),
            td("%d<span class=\"sub\"> 挂 · 涨停 %d</span>" % (r["n"], r["n_zt"])),
            td(('<b class="%s">%s%%</b>' % ("red" if num(pcts) >= 0 else "green",
                                            signed(pcts, 2)))
               if pcts is not None else '<span class="sub">—</span>'),
            td((('<a class="sl" href="/theme">%s</a>' % esc(r["theme_name"]))
                if r.get("theme_name") else '<span class="sub">未归并</span>')
               + '<div class="sub">%s</div>' % nm, left=True),
        ))
    return card("今日关键词<span>从 %d 只票的异动解析里数出来的 · 按挂几只涨停股排</span>"
                % (nw.get("meta", {}).get("n_with_reason") or 0),
                table(["#", "关键词", "挂几只", "成员均涨", "归入主线 / 代表个股"],
                      "".join(trs), "l l r r l"))


def _live(nw, tid) -> str:
    """主线卡里的"实况消息面"：真实关键词 + 行业原因原文。"""
    v = (nw.get("themes") or {}).get(tid) or {}
    if not v:
        return ""
    kws = "".join('<span class="chip"%s>%s<span class="sub"> %d</span></span>'
                  % (' style="border-color:#d9534f"' if i == 0 else "",
                     esc(x["kw"]), x["n"])
                  for i, x in list(enumerate(v.get("kw") or []))[:10])
    parts = ['<div class="kv" style="margin:12px 0 6px"><div>'
             "<span>实况关键词（异动解析里原样出现的词）</span>"
             "<b>核心 %d 只 / 涨停 %d</b></div></div><div class=\"tags\">%s</div>"
             % (v.get("n_core") or 0, v.get("n_core_zt") or 0, kws)]
    if v.get("quote"):
        parts.append('<div class="dv-detail" style="margin-top:8px">'
                     "<b>行业原因原文（%d 只票共享同一段）</b>：%s</div>"
                     % (v.get("quote_n") or 0, esc(v["quote"][:220])))
    if v.get("comp_quote"):
        parts.append('<div class="dv-detail"><b>最典型的个股（%s）公司原因</b>：%s</div>'
                     % (esc(v.get("comp_name") or "—"), esc(v["comp_quote"][:180])))
    return "".join(parts)


def _members(r, sc, limit=16, names=None) -> str:
    by = (sc or {}).get("by_code") or {}
    zt = {str(x.get("code")): x for x in ((r.get("_zt") or {}).values())} if r.get("_zt") else {}
    names = names or {}

    def keyf(c):
        e = by.get(c) or {}
        return (-(e.get("total") or 0), -(int((r.get("_board") or {}).get(c) or 0)))

    core = [c for c in (r.get("core_codes") or [])]
    codes = sorted(core, key=keyf) or sorted([c for c in (r.get("codes") or [])], key=keyf)
    if not codes:
        return ""
    items = []
    for c in codes[:limit]:
        e = by.get(c) or {}
        nm = e.get("name") or names.get(c) or c
        sc_txt = ("%.0f" % (e["total"])) if e.get("total") is not None else "涨停"
        b = ""
        if e.get("board_tag"):
            b = '<span class="tag n">%s</span>' % esc(e["board_tag"])
        items.append('<a class="chip" href="/s/%s">%s <span class="sub">%s</span>%s</a>'
                     % (esc(c), esc(nm), sc_txt, b))
    more = len(codes) - limit
    tail = '<span class="sub"> 等 %d 只</span>' % more if more > 0 else ""
    return '<div class="tags">%s%s</div>' % ("".join(items), tail)


def _theme_card(r, sc, nw=None, names=None) -> str:
    blocks = r.get("blocks") or []
    bl = "".join(
        '<span class="chip">%s <span class="%s">%s%%</span><span class="sub"> %s/%s</span></span>'
        % (esc(b.get("name") or ""), "red" if num(b.get("pct")) >= 0 else "green",
           signed(b.get("pct"), 2) if b.get("pct") is not None else "—",
           b.get("up") if b.get("up") is not None else "—",
           b.get("down") if b.get("down") is not None else "—")
        for b in blocks[:8])
    inds = "".join('<span class="chip">%s <span class="sub">%d</span></span>'
                   % (esc(i.get("name") or ""), i.get("n") or 0)
                   for i in (r.get("industries") or [])[:6])
    parts = [
        '<div class="dv-detail"><b>消息面（人工整理，非新闻抓取）</b>：%s</div>'
        % esc(r.get("catalyst") or "—"),
        _evidence(r),
        _live(nw or {}, r["id"]),
        '<div class="kv" style="margin:10px 0 6px"><div><span>成员（按总分，核心 %d / 挂本线 %d）'
        "</span><b>%s</b></div></div>" % (r.get("n_core") or 0, r.get("n") or 0,
                                          esc("、".join(x for x in [r.get("best_name")] if x))),
        _members(r, sc, names=names),
    ]
    if inds:
        parts.append('<div class="kv" style="margin:10px 0 6px"><div><span>落在哪些行业</span>'
                     "<b>看得出一条消息穿过多少个行业</b></div></div>"
                     '<div class="tags">%s</div>' % inds)
    if bl:
        parts.append('<div class="kv" style="margin:10px 0 6px"><div><span>关联的东财概念板块'
                     "（含涨跌家数）</span><b>%d 个</b></div></div><div class=\"tags\">%s</div>"
                     % (r.get("n_blocks") or 0, bl))
    return card("%s<span>%s · 成员 %d 只 · 涨停 %d · 最高 %d 板</span>"
                % (esc(r["name"]), esc(r.get("short") or ""), r.get("n") or 0,
                   r.get("lu") or 0, r.get("max_board") or 0),
                "".join(parts), "热度 %.1f / 100 · %s" % (r["total"], r.get("tier") or ""))


def _note(sc, nw=None) -> str:
    m = (sc or {}).get("theme", {}).get("meta") or {}
    nm = (nw or {}).get("meta") or {}
    return card("口径说明", (
        '<div class="dv-detail">'
        "<b>为什么要有主线这一层</b>：行业回答「它在哪个产业」，概念回答「它挂哪个标签」，"
        "但真正决定今天涨不涨的是<b>一条消息</b>。消息落在数据里是十几个细支——"
        "AI 短剧、AI 漫剧、AI 视频、短剧游戏、出版传媒……逐个看都很小，"
        "并起来才是主线。本页做的就是并这件事。<br>"
        "<b>怎么并的</b>：每条主线一套关键词，对标签取<b>最长匹配</b>"
        "（「短剧互动游戏」命中「短剧」而不是「游戏」）；"
        "没命中任何主线的标签原样留在概念层，不硬塞。"
        "成员＝同花顺涨停原因/异动标签 <b>＋</b> 东财 F10 所属概念板块的并集。<br>"
        "<b>热度分（100 制）</b>＝涨停 30 + 上升广度 25 + 人气 20 + 赚钱效应 15 + 龙头 10，"
        "与概念总榜<b>同一套权重</b>，所以两张榜可以横向比。"
        "分档：<span class=\"tag n\">强</span> 分 ≥80 且涨停 ≥10；"
        "中 ≥65；其余弱。普涨日几乎所有线都过 50，所以门槛没用过半——"
        "那会让 12 条线全标成「热」，等于没标。<br>"
        "<b>核心 / 关联</b>：一只票只认一条主归属（它的细分标签最集中的那条，或产业链归到的线）。"
        "主归属在本线的算<b>核心成员</b>；被东财宽板块（AI应用 / AIGC 这类）带进来的算"
        "<b>关联成员</b>。龙头只在核心成员里按「板数 → 人气」选——"
        "拿人气榜第一名当龙头，会让五条线的龙头都是同一个名字。<br>"
        "<b>机器人这条线特殊</b>：东财<b>没有</b>「机器人」行业指数（行业 496 个里没有），"
        "机器人是概念板块 BK0800；机床、工控、减速器是它的上游。"
        "所以本站在 F10 原始行业链之上加了一层<b>产业链归属</b>（人工映射、页面标注）："
        "行业链最细级 ∈ 机床工具/自动化设备/通用设备… 且概念含机器人相关词，"
        "就认到机器人链上。原始行业照常显示，两个都看得到。<br>"
        "<b>消息面现在有两层来源</b>：上面每条线里「消息面（人工整理）」那段是小编写的逻辑，"
        "只讲这条线为什么成立；「实况关键词 / 行业原因原文」那两块是<b>抓来的原文</b>——"
        "同花顺对每只票的异动解析（AI 归纳公开信息，原文带免责声明），"
        "共 %d 只票、%d 个关键词，同一段行业原因被几只票共享就说明是同一个消息。<br>"
        "<b>为什么要把所有涨停股都去读一遍</b>：人气池只有 %d 只，而全市场涨停 %d 只，"
        "只读池子会漏掉大部分涨停股，消息面就数不出来。本页的并集＝"
        "人气池 ∪ 全市场涨停 ∪ 今日龙虎榜 ∪ 热榜 100。<br>"
        "<b>关键词榜不参与打分</b>：概念分仍只用标签口径，"
        "因为一改打分，全站 120 分制的每条阈值都要重标。这一层只回答"
        "「今天在炒哪条消息、有多大」，不回答「该给多少分」。<br>"
        "<b>当前 %d 条主线，%d 条达标强主线。</b>"
        % (nm.get("n_with_reason") or 0, nm.get("n_kw") or 0,
           len((sc or {}).get("by_code") or {}), nm.get("n_zt") or 0,
           m.get("n") or 0, m.get("n_hot") or 0)
    ), "数据来源：同花顺逐股异动 · 东财 F10 所属板块 · 东财概念板块行情")


def render(data=None, meta=None, sc=None) -> str:
    from .shell import footer, page

    # 不传 sc 就自己算：静态构建、serve 路由、验收脚本三条路径都只传 (data, meta)，
    # 少算这一步页面就静默退化成"还没有主线结果"（2026-11-02 踩过，静态页只剩空壳）。
    sc = sc or scoring.build(data or {})
    nw = news_mod.build(data or {}, attr=_load_attr(data),
                        main_of=(sc.get("theme") or {}).get("main_of"))
    nmap = _name_map(data or {}, nw)
    linkable = set((data or {}).get("stocks") or {}) | {
        str(x.get("code")) for x in ((data or {}).get("zt_pool") or [])}
    th = (sc.get("theme") or {})
    rows = th.get("rows") or []
    day = (data or {}).get("quote_date") or "—"
    n_stock = len((data or {}).get("stocks") or {})

    if not rows:
        body = card("主线", empty("还没有主线归并结果——先跑一次 python refresh.py。"))
        return page("主线", "/theme", body,
                    tail=footer("数据源：同花顺逐股异动 · 东财 F10", "不构成投资建议。"))

    hot = [r for r in rows if r.get("hot")]
    head = ('<div class="hero"><div class="eyebrow">主线 · %s</div>'
            '<div class="hd"><h1>今天在炒哪条消息</h1>'
            '<span class="c">%d 条主线 · 强 %d 条 · 覆盖 %d 只票 · '
            "最强 <b>%s</b>（%.1f 分）</span></div></div>"
            % (esc(day), len(rows), len(hot), n_stock,
               esc(rows[0]["name"]), rows[0]["total"]))

    top = rows[0]
    concl = ('<div class="nar-i"><div class="nar-n">1</div><div>'
             '<div class="nar-t">最强的线</div><div class="nar-v">'
             "<b>%s</b>：%d 只票、涨停 %d 只、最高 %d 板，龙头 <b>%s</b>。%s</div></div></div>"
             % (esc(top["name"]), top.get("n") or 0, top.get("lu") or 0,
                top.get("max_board") or 0, esc(top.get("best_name") or "—"),
                esc(top.get("catalyst") or "")))
    if len(rows) > 1:
        second = rows[1]
        concl += ('<div class="nar-i"><div class="nar-n">2</div><div>'
                  '<div class="nar-t">次强的线</div><div class="nar-v">'
                  "<b>%s</b>（%.1f 分，%d 只/涨停 %d）。"
                  "两条线是否共用成员：%s</div></div></div>"
                  % (esc(second["name"]), second["total"], second.get("n") or 0,
                     second.get("lu") or 0,
                     esc("是，有 %d 只重叠" % len(set(top["codes"]) & set(second["codes"]))
                         if set(top["codes"]) & set(second["codes"]) else "否，各自独立")))
    body = "".join([
        head,
        '<div class="card">%s</div>' % concl,
        card("主线热度榜<span>与概念总榜同一套权重，可直接横向比</span>",
             _main_table(rows)),
    ] + [_kw_table(nw, names=nmap, linkable=linkable)] + [_theme_card(r, sc, nw, nmap) for r in rows[:6]]
      + [_note(sc, nw)])

    return page("主线 · %s" % day, "/theme", body,
                tail=footer("数据源：同花顺逐股异动 · 东财 F10 所属板块 · 东财概念板块行情",
                            "消息面文字为人工整理，不构成投资建议。"))
