# -*- coding: utf-8 -*-
"""题材页 /concept：概念总榜 + 单概念成分。

概念总榜的口径见 score.concept_board：五项因子（涨停 30 / 上升广度 25 /
人气总量 20 / 赚钱效应 15 / 龙头高度 10），本页只负责把分项摊开给人看，
并把"为什么这个排第一"写成可核对的数字，而不是一句结论。
"""
from __future__ import annotations

import score as scoring
from .components import esc, num, rnd, trim, signed, card, table, td, empty
from .shell import page, footer

# 分项配色：涨停红（资金投票）、上升橙（趋势）、人气金（关注度）、
# 涨幅蓝（赚钱效应）、龙头紫（高度）。绿在 A 股语义里是跌，不拿来当正项色。
SUB_COLOR = {"lu": "#d9363e", "up": "#e8804a", "heat": "#c9a227",
             "rise": "#2563eb", "lead": "#7c3aed"}
SUB_NAME = {"lu": "涨停", "up": "上升", "heat": "人气", "rise": "涨幅", "lead": "龙头"}

EXPLAIN = """<div class="dv-detail">
<b>涨停 30</b>：取<b>全市场涨停梯队</b>（当日 49 只涨停股）按概念归属计数，
与人气榜 concept_stats 的涨停数取较大值；高度分 ≥3 板 8 分 / 2 板 5 分 / 1 板 2 分。
涨停是资金用真金白银投的票，所以权重最高。<br>
<b>上升广度 25</b>：成分里近 5 步名次在升的比例，但要做<b>贝叶斯收缩</b>
(up×n + 0.5×8) ÷ (n+8)——3 只票全升只能得 0.6，24 只里 23 只升才接近 0.9。
旧口径用 min(n,10) 截断样本量，等于把 14 只和 25 只看成一样大，
结果「14 只全升」压过了「24 只里 10 只涨停」——这是被踩掉的坑。<br>
<b>人气 20</b>：Σ 1/√(成员人气名次)。开根号是为了既不放弃「成员多＝关注度总量大」，
也不让只数线性膨胀。<br>
<b>赚钱效应 15</b>：成员均涨幅（-2% 以下 0 分，+8% 以上满分）。
<b>只统计有涨幅数据的成员</b>，样本少于 3 只给中性半分并标「样本不足」——
缺失不能当 0 算，否则概念均涨幅会被系统性拉低（实测 CPO 14 只里只有 2 只有涨幅，
把缺失当 0 会算出 +0.71%，真实这两只是 +4.05% 和 +5.89%）。<br>
<b>龙头高度 10</b>：概念内最好人气名次，第 1 名满分，200 名开外 0 分。<br>
<b>入榜只数 ≠ 概念总规模</b>：分母只统计当日抓到人气数据的个股（约 167 只）。
同花顺全市场一个概念动辄几十上百只，本池只看得见「今天有人气的那部分」，
所以「入榜 14 只」不能读成「这个概念只有 14 只票」。<br>
<b>泛标签</b>（业绩增长 / 高股息 / 三季报增长 / 超跌反弹等）与
<b>行情描述型标签</b>（「CPO板块下跌」这类异动原因）不参与概念榜——
前者指向不具体，后者根本不是概念。<br>
五项分相加＝概念分，鼠标悬停分值条可看拆解数字。
</div>"""


def _link(code, name):
    if not code:
        return esc(name or "—")
    return '<a class="sl" href="/s/%s">%s</a>' % (esc(code), esc(name or code))


def _bar(sub, total, width=118):
    """5 段堆叠条：一眼看出这个概念的分数是靠什么撑起来的。"""
    segs = []
    for k in ("lu", "up", "heat", "rise", "lead"):
        w = (sub[k] / 100.0) * width
        if w <= 0:
            continue
        segs.append('<i style="width:%.1fpx;background:%s"></i>' % (w, SUB_COLOR[k]))
    tip = " · ".join("%s %s" % (SUB_NAME[k], trim(sub[k], 1)) for k in SUB_NAME)
    return ('<div class="row" style="gap:8px;justify-content:flex-end">'
            '<span style="display:inline-flex;height:8px;border-radius:4px;overflow:hidden;'
            'background:var(--track);width:%dpx" title="%s">%s</span>'
            '<b style="font-variant-numeric:tabular-nums;min-width:34px;text-align:right">%s</b></div>'
            % (width, esc(tip), "".join(segs), trim(total, 1)))


def _members(codes, stocks, limit=None, leader=""):
    if not codes:
        return '<span class="sub">—</span>'
    rows = sorted(codes, key=lambda c: (stocks[c].get("heat_rank") or 999))[:limit or len(codes)]
    out = []
    for c in rows:
        e = stocks.get(c) or {}
        cls = "chip lead" if (e.get("name") or "") == leader else "chip"
        out.append('<a class="%s" href="/s/%s" title="人气第 %s 名">%s'
                   '<span style="opacity:.5;font-size:10px"> %s</span></a>'
                   % (cls, esc(c), esc(e.get("heat_rank") or "—"),
                      esc(e.get("name") or c), esc(e.get("heat_rank") or "—")))
    more = ""
    if limit and len(codes) > limit:
        more = '<span class="sub">　等 %d 只</span>' % len(codes)
    return '<div class="chips">%s%s</div>' % ("".join(out), more)


def _detail(r, stocks) -> str:
    """单概念展开：五因子各自打了多少分 + 全部成分。"""
    sub = r["sub"]
    kv = [
        ("入榜只数", "%d 只" % r["n"]),
        ("涨停 / 最高板", "%d 只 / %d 板" % (r["limit_up"], r["max_board"])),
        ("上升广度", "%d%%（收缩后 %d%%）" % (round(r["up"] * 100), round(r["up_adj"] * 100))),
        ("成员均涨幅", ("%s%%" % signed(r["avgpct"], 2)) if r["avgpct"] is not None
         else "样本不足（仅 %d 只有涨幅）" % r["n_pct"]),
        ("人气最好名次", "第 %s 名（%s）" % (r["best_rank"] or "—", r["best_name"] or "—")),
        ("人气总量", "%.2f" % r["heat"]),
        ("龙头", r["leader"] or "—"),
        ("强/弱/净", "%s / %s / %s" % (r["strong"] or "—", r["weak"] or "—", r["net"] or "—")),
        ("概念分", "%s / 100" % trim(r["total"], 1)),
    ]
    kvhtml = "".join("<div><span>%s</span><b>%s</b></div>" % (esc(k), esc(v)) for k, v in kv)
    bars = []
    for k in ("lu", "up", "heat", "rise", "lead"):
        full = scoring.CON_W[k]
        bars.append(
            '<div class="srow" style="display:flex;align-items:center;gap:9px;margin:5px 0">'
            '<span style="width:56px;color:var(--t2);font-size:12px">%s</span>'
            '<span style="flex:0 0 300px;height:7px;background:var(--track);border-radius:4px;'
            'overflow:hidden"><i style="display:block;height:100%%;width:%.0f%%;background:%s"></i></span>'
            '<span style="font-variant-numeric:tabular-nums;font-size:12px">%s / %s</span></div>'
            % (SUB_NAME[k], sub[k] / full * 100, SUB_COLOR[k], trim(sub[k], 1), int(full)))
    body = ('<div class="kv">%s</div><div style="margin-top:14px">%s</div>'
            '<div style="margin-top:14px">%s</div>'
            % (kvhtml, "".join(bars), _members(r["codes"], stocks)))
    return card("%s<span>概念分 %s · 第 %d 名 · 按人气名次排成分</span>"
                % (esc(r["concept"]), trim(r["total"], 1), r["rank"]), body, "")


def render(data, meta, q: str = "", c: str = "") -> str:
    stocks = data.get("stocks") or {}
    sc = scoring.build(data)
    try:
        from store import load_snapshot
        _d8, snap = load_snapshot(None)
    except Exception:
        snap = None
    rows = scoring.concept_board(stocks, snap, data.get("concept_stats"))

    # 概念 → 板块热度的桥：只做展示提示，不参与概念分（两边口径不同，混用会算错）
    n_rising = sum(1 for r in rows if r["up"] >= 0.5)

    head = ('<div class="hero"><div class="eyebrow">A 股题材 · 人气聚合</div>'
            "<h1>今天的钱在哪些概念里</h1>"
            '<div class="meta">行情日 %s　·　概念 %d 个（其中 %d 个过半成分在升）　·　'
            '标签来自 %d 只个股的归属统计<br>'
            "排序＝涨停 30 + 上升广度 25 + 人气 20 + 赚钱效应 15 + 龙头高度 10"
            "</div></div>" % (esc(data.get("quote_date") or "—"), len(rows), n_rising, len(stocks)))

    picked = None
    if c:
        for r in rows:
            if r["concept"] == c:
                picked = r
                break
        if picked is None:
            codes = [k for k, e in stocks.items() if c in scoring.tags_of(e)]
            picked = {"concept": c, "n": len(codes), "codes": codes, "rank": 0,
                      "total": 0.0, "sub": {k: 0 for k in SUB_NAME},
                      "limit_up": 0, "max_board": 0, "up": 0, "up_adj": 0,
                      "avgpct": None, "n_pct": 0, "best_rank": None, "best_name": "",
                      "heat": 0, "leader": "", "strong": None, "weak": None, "net": None}

    trs = []
    for r in rows:
        rise = ("%s%%" % signed(r["avgpct"], 1) if r["avgpct"] is not None
                else '<span class="sub" title="只有 %d 只有涨幅数据，样本不足则给中性分">样本不足</span>'
                % r["n_pct"])
        rise_cls = "" if r["avgpct"] is None else ("red" if r["avgpct"] > 0 else "green")
        trs.append("<tr>%s%s%s%s%s%s%s%s</tr>" % (
            td("%d" % r["rank"]),
            td('<a class="sl" href="/concept?c=%s">%s</a>' % (esc(r["concept"]), esc(r["concept"])),
               left=True),
            td("%d 只" % r["n"]),
            td("%d 只%s" % (r["limit_up"], " · %d 板" % r["max_board"] if r["max_board"] >= 2 else ""),
               "red" if r["limit_up"] else ""),
            td('<b class="%s">%s %d%%</b><div class="dnote">%d/%d 只在升 · 收缩 %d%%</div>'
               % ("red" if r["up"] >= 0.6 else ("green" if r["up"] < 0.35 else ""),
                  "↑" if r["up"] >= 0.6 else ("→" if r["up"] >= 0.35 else "↓"),
                  round(r["up"] * 100), round(r["up"] * r["n"]), r["n"],
                  round(r["up_adj"] * 100)), left=True),
            td('<span class="%s">%s</span>' % (rise_cls, rise)),
            td("第 %s" % r["best_rank"] if r["best_rank"] else "—"),
            td(_bar(r["sub"], r["total"]), left=True),
        ))
    tbl = table(["#", "概念", "入榜", "涨停 / 高度", "上升广度", "成员均涨幅", "人气最佳", "概念分（拆解）"],
                "".join(trs), "l l r l l r r l")

    body = "".join([
        head,
        _detail(picked, stocks) if picked else "",
        card("概念总榜<span>%d 个概念 · 点概念看全部成分与五项拆解</span>" % len(rows), tbl),
        card("口径说明｜为什么不是「谁上升占比高谁第一」", EXPLAIN),
    ])
    return page("题材 · A 股全景", "/concept", body,
                subtitle="本地 · 数据真值",
                tail=footer("数据来源：人气榜概念聚合（yjj798/renqibang）· 全市场涨停梯队（55188）",
                            "本页只做汇总展示，不构成投资建议。"))
