# -*- coding: utf-8 -*-
"""行业页 /industry：哪一片在整体动，以及「行业＋概念」双轮的票有哪些。

为什么单独一页
--------------
原站只有题材（/concept）。题材是**故事标签**，它天然偏向"有词可讲"的票：
挂了热门词的票看起来都热，而行业整体抬升、但没有新故事的票（影视院线集体复苏、
白酒全线提价）在题材页里几乎看不见。

这页回答三个不同的问题：
    1. 哪些行业今天在整体动（行业榜：指数涨幅＋上涨广度＋主力净额＋池内涨停）
    2. 哪些票是「行业＋概念」双轮（两个维度同时热 = 双重硬逻辑）
    3. 哪些只是单腿（只有行业、或只有概念）——单腿最容易一日游

口径写法
--------
行业涨幅用**申万行业指数**（东财行业板块，市值加权），广度用板块内上涨家数占比。
两者必须分开看：指数被几只权重拉起来、而多数票在跌的行业，广度会立刻暴露它。
两项都换算成全市场分位再打分——普涨日 +3% 只是中位数，全场下跌时 +0.5% 就已经最强。
"""
from __future__ import annotations

import score as scoring
from .components import card, empty, esc, grid4, num, signed, table, td, trim, yi
from .shell import footer, page

DRIVE_CLS = {"双轮": "red", "行业": "", "概念": "", "无": "sub"}


def _pct_cell(v) -> str:
    if v is None:
        return '<span class="sub">—</span>'
    return '<b class="%s">%s%%</b>' % ("red" if num(v) >= 0 else "green", signed(v, 2))


def _bar_cell(frac, label: str, color: str = "") -> str:
    """分位细条：数字后面跟一根条，扫一眼就知道在什么位置。"""
    f = max(0.0, min(1.0, num(frac)))
    return ('<div class="dcell"><b>%s</b>'
            '<div class="dbar"><i style="width:%.0f%%%s"></i></div></div>'
            % (esc(label), f * 100, (";background:%s" % color) if color else ""))


def _industry_table(rows, stocks) -> str:
    body_rows = []
    for r in rows:
        delta = r.get("delta")
        dcell = ('<span class="%s">%s pp</span>'
                 % ("red" if num(delta) >= 0 else "green", signed(delta, 2))
                 if delta is not None else '<span class="sub">—</span>')
        lu = ('<span class="tag n">%d</span>' % r["lu"]) if r["lu"] else '<span class="sub">0</span>'
        body_rows.append("<tr>%s%s%s%s%s%s%s%s%s%s%s</tr>" % (
            td('<span class="rk%s">%d</span>'
               % (" t1" if r["rank"] == 1 else (" t2" if r["rank"] == 2 else
                                                (" t3" if r["rank"] == 3 else "")), r["rank"])),
            td("<b>%s</b>%s" % (esc(r["name"]),
                               '<span class="tag n" style="margin-left:6px">热</span>'
                               if r["hot"] else ""), left=True),
            td(_pct_cell(r["pct"])),
            td(_bar_cell(r["pct_rank"], "%.0f%%" % (r["pct_rank"] * 100)), left=True),
            td("%s / %s" % (r["up"] if r["up"] is not None else "—",
                            r["down"] if r["down"] is not None else "—")),
            td(_bar_cell(r.get("breadth_rank") or 0,
                         "%.0f%%" % ((r.get("breadth") or 0) * 100)), left=True),
            td(yi(r["net"]) if r.get("net") is not None else '<span class="sub">—</span>'),
            td("%d 只" % r["n"]),
            td(lu),
            td(dcell),
            td(esc(r.get("leader") or "—"), left=True),
        ))
    body = table(["#", "行业", "指数涨幅", "涨幅分位", "涨 / 跌", "上涨广度", "主力净额",
                  "池内", "涨停", "较昨日", "领涨股"],
                 "".join(body_rows), "l l r l r l r r r r l")
    return card("行业热度榜<span>只列池内有成员的行业 · 共 %d 个 · 热度分＝涨幅 45 + 广度 25 "
                "+ 涨停 20 + 成员均涨 10</span>" % len(rows), body)


def _drive_table(rows, stocks, title: str, sub: str, empty_text: str) -> str:
    if not rows:
        return card(title, empty(empty_text), sub)
    body_rows = []
    for r in rows:
        i = r.get("industry") or {}
        e = stocks.get(r["code"]) or {}
        body_rows.append("<tr>%s%s%s%s%s%s%s</tr>" % (
            td('<a class="sl" href="/s/%s">%s</a>' % (esc(r["code"]), esc(r.get("name") or r["code"])),
               left=True),
            td(esc(i.get("name") or "—"), left=True),
            td(_pct_cell(i.get("pct"))),
            td(_bar_cell(i.get("pct_rank") or 0, "%.0f%%" % ((i.get("pct_rank") or 0) * 100)),
               left=True),
            td("<b>%s</b><span class=\"sub\">/25</span>" % trim(r["concept"], 1)),
            td('<b class="big">%s</b>' % trim(r["total"], 1)),
            td('<span class="%s">%s</span>' % (DRIVE_CLS.get(r["drive"], ""), esc(r["drive"]))),
        ))
    return card(title, table(["股票", "行业", "行业涨幅", "行业中位置", "概念 /25",
                              "总分 /120", "驱动"],
                             "".join(body_rows), "l l r l l r l"), sub)


def _note(data) -> str:
    m = (data.get("industry") or {}).get("meta") or {}
    return card("口径说明", (
        '<div class="dv-detail">'
        "<b>行业分类</b>取申万行业（东财行业板块，含二级与三级共 %d 个），个股归属来自行情接口的"
        "所属行业字段，不是按名字或概念猜的——实测池内 %d 只票里 %d 只能对上行业指数，"
        "剩下几只是当日无行情（停牌/新股），页面上标「无行业数据」而不是判成行业弱。<br>"
        "<b>行业分（0~14）</b>＝涨幅分位 7 + 上涨广度分位 4 + 主力净额分位 3。"
        "三项都用<b>全市场行业排名</b>而不是绝对涨幅：普涨日 +3%% 只是中位数，"
        "全场下跌时 +0.5%% 就已经最强，绝对数会随大盘漂。<br>"
        "<b>行业热</b>判据＝涨幅分位 ≥ 85%% 且 板块内上涨家数过半（分位极高时可豁免广度）。"
        "<b>概念热</b>判据＝概念分 ≥ 12.5/25（过半）。<br>"
        "<b>双轮共振 +6</b>＝行业热与概念热<b>同时</b>成立。只热一边不给分——"
        "给了就等于给所有概念热票普涨一次分，榜单会整体通胀，反而看不出双轮的稀缺。<br>"
        "<b>上涨广度</b>已做小样本收缩（1 涨 0 跌不算 100%%），并按全市场分位展示；"
        "括号里的原始值就是板块的涨跌家数比。<br>"
        "<b>较昨日</b>要等历史积累：每天收盘留一份行业涨幅快照，第二天起才会显示差值，"
        "没有昨天的数据就显示「—」，不编造「加速」。"
        % (m.get("n_blocks") or 0, m.get("n_code") or 0, m.get("n_matched") or 0)
    ), "数据来源：东财行业板块行情 · 个股所属行业")


def render(data, meta, sc=None) -> str:
    stocks = data.get("stocks") or {}
    sc = sc or scoring.build(data)
    sec = sc.get("sector") or {}
    rows = sec.get("rows") or []
    m = sc.get("meta") or {}
    sm = sec.get("meta") or {}
    ind_meta = (data.get("industry") or {}).get("meta") or {}

    ranked = sc.get("ranked") or []
    double = [r for r in ranked if r["drive"] == "双轮"]
    ind_only = [r for r in ranked if r["drive"] == "行业"]
    con_only = [r for r in ranked if r["drive"] == "概念"]

    top = rows[0] if rows else {}
    head = (
        '<div class="hero"><div class="eyebrow">行业维度 · 申万行业指数</div>'
        "<h1>哪一片在整体动</h1>"
        '<div class="meta">行情日 %s　·　行业 %d 个（池内命中 %d 个）　·　'
        "池内 %d 只有行业归属　·　刷新于 %s<br>"
        "行业＝这一片是不是整体在动；概念＝有没有一个故事把若干票串起来。"
        "两者同时热才算双重硬逻辑。</div></div>"
        % (esc(data.get("quote_date") or "—"), sm.get("n_blocks") or 0, len(rows),
           ind_meta.get("n_code") or sm.get("n_code") or 0,
           esc((meta.get("fetched_at") or "—").replace("T", " "))))

    kpi = grid4([
        ("今日行业热", "%d 个" % (sm.get("n_hot") or 0),
         "涨幅分位 ≥85% 且过半上涨"),
        ("双轮驱动", "%d 只" % (m.get("n_double") or 0),
         "行业热 × 概念热"),
        ("行业单边", "%d 只" % (m.get("n_ind_only") or 0), "只有行业在动"),
        ("最强行业", esc(top.get("name") or "—"),
         ("%s%% · %d 只涨停" % (signed(top.get("pct"), 2), top.get("lu") or 0))
         if top else "—"),
    ])

    degr = ""
    if data.get("degraded"):
        degr = ('<div class="card" style="padding:12px 14px"><div class="warn" style="margin:0">'
                "<b>部分数据源异常</b>：%s。相关榜单会缺行，不是页面坏了。</div></div>"
                % esc("；".join(data["degraded"])))

    return page("行业 · A 股全景", "/industry", "".join([
        head,
        degr,
        '<div class="card">%s</div>' % kpi,
        _industry_table(rows, stocks) if rows else card("行业热度榜", empty("今天没有行业数据")),
        _drive_table(double, stocks, "双轮驱动<span>行业在加速，概念也在热</span>",
                     "两类逻辑同时成立", "今天没有双轮驱动的票——行业与概念没有同时热的那一只。"),
        '<div class="cols">%s%s</div>' % (
            _drive_table(ind_only[:10], stocks, "只有行业<span>概念不热</span>",
                         "行业单边", "没有行业单边的票。"),
            _drive_table(con_only[:10], stocks, "只有概念<span>行业不热</span>",
                         "概念单边", "没有概念单边的票。")),
        _note(data),
    ]), subtitle="本地 · 数据真值",
        tail=footer("数据来源：东财行业板块行情（m:90+t:2）· 个股所属行业（f100）· "
                    "概念标签（同花顺）· 人气与排名（yjj798/renqibang、yjj79819/tdx）",
                    "行业与概念是两套口径，页面分别标注，不合并成一个「热度」。"))
