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
from sector import CON_HOT, HOT_BREADTH, HOT_PCT
from .board_table import board_table
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


def _why(r, gate) -> str:
    """驱动列的第二行：把「差在哪」直接写出来。

    只写「概念」两个字会让人以为"这只票没有行业"——用户 2026-11-02 就是这么
    读错的（沈阳机床被当成"没有行业"，实际是行业只排到中位）。所以单边一定
    标明另一项差多少：行业＋2.01% ＜ 门槛＋3.58%，或 概念 8.3 ＜ 12.5。
    """
    i = r.get("industry") or {}
    d = r.get("drive")
    pr = (i.get("pct_rank") or 0.0) * 100
    br = i.get("breadth")
    if d == "行业":
        return "概念 %s ＜ %.1f" % (trim(r["concept"], 1), CON_HOT)
    if d == "概念":
        if pr < HOT_PCT * 100:
            if gate is not None and i.get("pct") is not None:
                return "行业 %s ＜ 门槛 %s" % (signed(i["pct"], 2) + "%",
                                              signed(gate, 2) + "%")
            return "行业分位 %.0f%% ＜ %.0f%%" % (pr, HOT_PCT * 100)
        if br is not None and br < HOT_BREADTH:
            return "广度 %.0f%% ＜ %.0f%%" % (br * 100, HOT_BREADTH * 100)
        return "行业未达热门槛"
    return ""


def _chain(labels) -> str:
    """行业链小字：机械设备 › 通用设备 › 机床工具。一级到三级都摆出来，
    用户才知道「机床工具」是怎么来的，不是系统随手挑的一个词。"""
    if not labels:
        return ""
    return " › ".join(esc(x) for x in labels)


def _drive_table(rows, stocks, title: str, sub: str, empty_text: str, gate=None) -> str:
    if not rows:
        return card(title, empty(empty_text), sub)
    body_rows = []
    for r in rows:
        i = r.get("industry") or {}
        why = _why(r, gate)
        chain = _chain((i.get("labels") or {}).get("ind") or [])
        con = i.get("best", {}).get("con")
        cpct = i.get("con_pct")
        cnote = ("%d 个概念板块" % len((i.get("labels") or {}).get("con") or [])
                 if (i.get("labels") or {}).get("con") else "无概念板块")
        # 归因主线：行业/概念之上那一层。机床这类票的行业是「机床工具」，
        # 但市场买卖它的理由是「机器人」——这层关系 F10 里没有，靠产业链人工映射。
        thm = (r.get("theme") or {})
        chain_note = ("机器人链" if "robot" in (thm.get("chain") or []) else "")
        tcell = ('<b>%s</b>' % esc(thm.get("main_name") or "—")) if thm.get("main") else \
                '<span class="sub">—</span>'
        if chain_note:
            tcell += '<div class="sub"><span class="tag n">%s</span></div>' % chain_note
        body_rows.append("<tr>%s%s%s%s%s%s%s%s</tr>" % (
            td('<a class="sl" href="/s/%s">%s</a>' % (esc(r["code"]),
                                                     esc(r.get("name") or r["code"])), left=True),
            td("<b>%s</b>%s" % (esc(i.get("name") or "—"),
                               '<div class="sub">%s</div>' % chain if chain else ""), left=True),
            td(_pct_cell(i.get("pct"))),
            td(tcell, left=True),
            td(('<b class="%s">%s %s%%</b><div class="sub">%s</div>'
                % ("red" if num(cpct) >= 0 else "green", esc(con or "—"),
                   signed(cpct, 2) if cpct is not None else "—", esc(cnote)))
               if con else '<span class="sub">—</span>', left=True),
            td("<b>%s</b><span class=\"sub\">/25</span>" % trim(r["concept"], 1)),
            td('<b class="big">%s</b>' % trim(r["total"], 1)),
            td('<span class="%s">%s</span>%s'
               % (DRIVE_CLS.get(r["drive"], ""), esc(r["drive"]),
                  '<div class="sub">%s</div>' % esc(why) if why else "")),
        ))
    return card(title, table(["股票", "行业（最细一级）", "行业涨幅", "归因主线",
                              "最热概念板块", "概念 /25", "总分 /120", "驱动"],
                             "".join(body_rows), "l l r l l l r l"), sub)


def _note(data) -> str:
    m = (data.get("industry") or {}).get("meta") or {}
    n_code = m.get("n_code") or 0
    n_ok = m.get("n_matched") or 0
    miss = max(0, n_code - n_ok)
    cover = ("%d 只票全部对上行业指数" % n_ok if miss == 0
             else "%d 只票里 %d 只能对上行业指数，其余 %d 只当日无行情（停牌/新股），"
                  "页面标「无行业数据」而不是判成行业弱" % (n_code, n_ok, miss))
    return card("口径说明", (
        '<div class="dv-detail">'
        "<b>行业分类</b>取东财行业板块（含一/二/三级共 %d 个），个股归属来自 <b>F10「所属板块」</b>："
        "一只票通常挂 3 层行业（如 机械设备 › 通用设备 › 机床工具）＋若干概念板块，"
        "打分用的是<b>最细那一级</b>——通用设备全市场 212 只、天天贴着大盘中位，"
        "机床工具只有 19 只，异动才看得见。实测池内 %s。<br>"
        "<b>概念板块</b>与行业板块是同一套接口（m:90+t:3，531 个）、同一份字段、同一个打分函数，"
        "所以 /concept 的概念板块榜与本页的行业榜列完全一致。<br>"
        "<b>行业分（0~14）</b>＝涨幅分位 7 + 上涨广度分位 4 + 主力净额分位 3。"
        "三项都用<b>全市场行业排名</b>而不是绝对涨幅：普涨日 +3%% 只是中位数，"
        "全场下跌时 +0.5%% 就已经最强，绝对数会随大盘漂。<br>"
        "<b>行业热</b>判据＝涨幅分位 ≥ 85%% 且 板块内上涨家数过半（分位极高时可豁免广度）。"
        "<b>概念热</b>判据＝概念分 ≥ 12.5/25（过半）。<br>"
        "<b>双轮共振 +6</b>＝行业热与概念热<b>同时</b>成立。只热一边不给分——"
        "给了就等于给所有概念热票普涨一次分，榜单会整体通胀，反而看不出双轮的稀缺。<br>"
        "<b>单边不是「没有另一项」</b>：标「概念」只表示行业没到热门槛（页面上把该行业的涨幅与"
        "今天的门槛并排写出来），行业归属与行业分照样计入总分；标「行业」同理，"
        "代表没有故事热起来，不是这只票没有概念标签。<br>"
        "<b>上涨广度</b>已做小样本收缩（1 涨 0 跌不算 100%%），并按全市场分位展示；"
        "括号里的原始值就是板块的涨跌家数比。<br>"
        "<b>较昨日</b>要等历史积累：每天收盘留一份行业涨幅快照，第二天起才会显示差值，"
        "没有昨天的数据就显示「—」，不编造「加速」。"
        % (m.get("n_blocks") or 0, cover)
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

    gate = sm.get("hot_gate_pct")
    gate_txt = ("今天行业热门槛＝指数 %s%%（全市场 %d 个板块的 85%% 分位，中位 %s%%）"
                % (signed(gate, 2), sm.get("n_blocks") or 0,
                   signed(sm.get("median_pct"), 2) if sm.get("median_pct") is not None else "—")
                if gate is not None else "行业热门槛按涨幅分位计")
    return page("行业 · A 股全景", "/industry", "".join([
        head,
        degr,
        '<div class="card">%s</div>' % kpi,
        board_table(rows, "行业热度榜",
                    "只列池内有成员的行业 · 共 %d 个 · 热度分＝涨幅 45 + 广度 25 + 涨停 20 "
                    "+ 成员均涨 10（与 /concept 的概念板块榜同一套算法）" % len(rows)),

        _drive_table(double, stocks, "双轮驱动<span>行业在加速，概念也在热</span>",
                     "两类逻辑同时成立", "今天没有双轮驱动的票——行业与概念没有同时热的那一只。",
                     gate),
        '<div class="cols">%s%s</div>' % (
            _drive_table(ind_only[:10], stocks, "行业单边<span>概念没热</span>",
                         "行业在动，但没有故事把票串起来 · " + gate_txt,
                         "没有行业单边的票。", gate),
            _drive_table(con_only[:10], stocks, "概念单边<span>行业没热</span>",
                         "有故事，但所属行业只是跟随大盘、没到自己热 · " + gate_txt
                         + " · 行业列照旧给出归属与分位，不是「没有行业」",
                         "没有概念单边的票。", gate)),
        _note(data),
    ]), subtitle="本地 · 数据真值",
        tail=footer("数据来源：东财行业板块行情（m:90+t:2）· 个股所属行业（f100）· "
                    "概念标签（同花顺）· 人气与排名（yjj798/renqibang、yjj79819/tdx）",
                    "行业与概念是两套口径，页面分别标注，不合并成一个「热度」。"))
