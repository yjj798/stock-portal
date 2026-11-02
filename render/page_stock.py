# -*- coding: utf-8 -*-
"""个股详情页 /s/<code>。

这一页就是最初需求里"能得到一只股票炒作的所有概念和异动"的落地形态：
    人名/代码/价格/涨幅
    一行摘要（¥5.91 95.2 216.4万·日 第7名 +110.1% 概念串 龙头 利多强）
    全部概念（可点回题材页）
    涨停原因（tdx 口径）
    评分拆解（每个因子怎么来的）
    资金与筹码（龙虎榜、量价、换手、位置）
    32 天人气排名轨迹（图）
    同花顺热榜名次（小时/日两口径）

明确不做的：K 线。那需要另一套行情源，且本站定位是"人气与概念"，不是看盘软件。
P3 会接 F10 全概念页（比当前 concept_all 更全）与逐股异动明细。
"""
from __future__ import annotations

import normalize
import score as scoring
from fetchers import abnormal
from .components import (esc, num, rnd, trim, signed, yi, card, table, td, grid4,
                         warn, empty, line_chart, rank_bars, temp_color)
from .shell import page, footer


def _pct(v):
    if v is None:
        return "—"
    c = "red" if num(v) >= 0 else "green"
    return '<b class="%s">%s%%</b>' % (c, signed(v, 2))


def _n(v, d=1, unit=""):
    if v is None:
        return "—"
    return trim(v, d) + unit


def _kpi(e) -> str:
    score = e.get("score")
    cells = [
        ("综合分", ('<span style="color:%s">%s</span>'
                    % (temp_color(score), trim(score, 1)) if score is not None else "—"),
         "人气榜自算 · 100 制"),
        ("同花顺热度", ("%.1f 万" % (num(e["ths_heat"]) / 1e4)) if e.get("ths_heat") else "—",
         "日热度" if (e.get("ths_heat_src") or "day") == "day" else "小时热度"),
        ("热度日环比", (('<span class="%s">%s%%</span>'
                        % ("red" if num(e.get("heat_growth")) >= 0 else "green",
                           signed(e.get("heat_growth"), 1)))
                       if e.get("heat_growth") is not None else "—"),
         "相对前一交易日"),
        ("人气名次", ("第 %s 名" % e["heat_rank"]) if e.get("heat_rank") else "—",
         "同花顺热度榜"),
    ]
    return grid4(cells)


def _concepts(e, data, tags=None) -> str:
    """全部概念 + 每个概念在本池里的成分数。

    为什么要标成分数：概念趋势只在「≥3 只成分且过半上升」时计分（见 score.py）。
    不标的话，用户看到「百草枯」会问"这么强的概念为什么不加分"——答案是池里只有
    这一只票在炒这个概念，凑不成板块，它加分只能加运气不能加趋势。
    """
    import collections
    cs = e.get("concepts") or normalize.split_concepts(e.get("concept_all"))
    hot_tag = (e.get("hot") or {}).get("concept_tag") or []
    if not cs and not hot_tag:
        return card("概念标签", empty("这只票今天没有抓到概念标签——通常意味着它没进异动榜。"))

    mem = collections.Counter(t for _c, ee in (data.get("stocks") or {}).items()
                              for t in scoring.tags_of(ee))
    tags = tags if tags is not None else {}
    chips = []
    for c in cs:
        n = mem.get(c, 1)
        g = tags.get(c)
        if g:
            cls, tip = "chip lead" if g["rising"] else "chip", "%d 只 · 升 %d%%" % (g["n"], g["up"] * 100)
        elif c in scoring.WIDE:
            cls, tip = "chip", "%d 只 · 泛标签不计" % n
        else:
            cls, tip = "chip", "%d 只 · 不足 3 只" % n
        chips.append('<a class="%s" href="/concept?c=%s" title="%s">%s<span class="sub">%s</span></a>'
                     % (cls, esc(c), esc(tip), esc(c), (" " + str(n)) if n else ""))
    extra = ""
    if hot_tag:
        extra = ('<div style="margin-top:12px" class="dv-detail">同花顺热榜另给的概念标签：%s'
                 "（与上面的口径不同源，两边不重合是正常的）</div>"
                 % "".join('<span class="chip">%s</span>' % esc(c) for c in hot_tag))
    return card("概念标签<span>%d 个 · 数字＝本池成分数</span>" % len(cs),
                '<div class="chips">%s</div>%s' % ("".join(chips), extra))


def _days_between(a: str, b: str):
    """两个 'YYYY-MM-DD' 差几天；解析不了返回 None。"""
    from datetime import date
    try:
        y1, m1, d1 = [int(x) for x in str(a).split("-")[:3]]
        y2, m2, d2 = [int(x) for x in str(b).split("-")[:3]]
        return (date(y1, m1, d1) - date(y2, m2, d2)).days
    except Exception:
        return None


def _reason_card(ab, quote_date: str = "") -> str:
    """上榜原因——同花顺给这只票写的「为什么涨/为什么热」。

    数据来自逐股异动接口的 reason 字段（ms.10jqka.com.cn/thsHotDetail 页面上
    那块 atom-clamp 文本就是它渲染出来的）。

    接口只保留**最近一次**异动，所以有三种情况必须区别对待，否则就是拿旧闻当新闻：
      当日          正常展示
      近 7 天内      展示，但明确标注"最近一次异动"并给出日期
      更早（含几年前）只留一行日期说明，不展示正文——那是历史，不是今天的上榜原因
    """
    title = "上榜原因<span>同花顺个股异动</span>"
    if not ab or not ab.get("reason"):
        return card(title, empty("同花顺今天没给这只票写上榜原因。"
                                 "通常意味着它当日没有触发异动（涨停/炸板/大幅波动等）。"))

    d = ab.get("date") or ""
    gap = _days_between(quote_date, d) if quote_date and d else None
    if gap is not None and gap > 7:
        return card("上榜原因<span>非当日</span>", empty(
            "该股最近一次异动在 %s，距行情日已 %d 天，不作为当日上榜原因展示。"
            % (d, gap)))

    ind, comp, disc = abnormal.split_reason(ab["reason"])
    tag = ('<span class="tag n">%s</span>' % esc(ab["tag_name"])) if ab.get("tag_name") else ""

    note = ""
    if gap is not None and gap > 0:
        note = ('<div class="warn" style="margin:0 0 12px">'
                "这不是 %s 当日的原因，而是该股<b>最近一次异动（%s）</b>的记录——"
                "说明它当天没触发新的异动。</div>" % (esc(quote_date), esc(d)))
    head = ('<span>同花顺个股异动 · %s%s</span>'
            % (tag, (' %s' % esc(d)) if d else ""))

    def block(t, text):
        if not text:
            return ""
        return ('<div class="rs-b"><div class="rs-t">%s</div>'
                '<div class="rs-x">%s</div></div>' % (esc(t), esc(text)))

    kw = ""
    if ab.get("keywords"):
        kw = ('<div class="chips" style="margin-top:10px">%s</div>'
              % "".join('<span class="chip">%s</span>' % esc(k) for k in ab["keywords"]))
    tail = ('<div class="sub" style="margin-top:10px">%s</div>' % esc(disc)) if disc else ""
    return ('<div class="card"><h2>上榜原因%s</h2>%s%s%s%s%s</div>'
            % (head, note,
               block("行业原因", ind), block("公司原因", comp), kw, tail))


def _score_card(x) -> str:
    """四维综合评分拆解 —— 这是本页的主评分，与「人气榜原始因子」是两套口径。

    每一项都必须把"分数从哪来"写在同一行：只给一个 28 分，读者无法判断
    是"名次涨得猛"还是"已经在第 5 名所以位置分高"，而这两件事的风险完全不同。
    """
    if not x:
        return ""
    t, c, r, m = x["trend"], x["concept"], x["reason"], x["money"]
    td_, cd, rd, md = x.get("trend_detail") or {}, x.get("concept_detail") or [], \
        x.get("reason_detail") or {}, x.get("money_detail") or {}

    def row(label, val, full, note):
        pct = max(0.0, min(1.0, num(val) / full)) * 100
        return ('<div class="srow"><div class="sl">%s</div>'
                '<div class="sv"><b>%s</b><span class="sub">/%d</span></div>'
                '<div class="sb"><i style="width:%.0f%%"></i></div>'
                '<div class="sx">%s</div></div>'
                % (esc(label), trim(val, 1), full, pct, note))

    # 趋势：把"快"和"稳"分开说——只有一样不算好形态
    seg = td_.get("seg") or td_.get("seq")
    if seg:
        steps = td_.get("steps") or (len(seg) - 1)
        tn = ("%d 步中 %d 步上升（稳 %.0f%%）· 日均 %.2f 对数名次 · "
              "第 %d 名 → 第 %d 名"
              % (steps, round(td_["mono"] * steps), td_["mono"] * 100,
                 td_["slope"], seg[0], seg[-1]))
        if td_.get("seq") and len(td_["seq"]) > len(seg):
            tn += "（起算点取启动前最差名次，前一段回撤不计入）"
    elif t.get("heat_growth") is not None:
        tn = ("无排名历史（不在 tdx 榜）· 用热度日环比 %s%% 代理，上限 21 分"
              % signed(t["heat_growth"], 1))
    else:
        tn = "无排名历史、无热度环比 —— 这一维计 0 分"

    if cd:
        cn = "、".join("%s（%d 只 · 升 %d%%）" % (d["tag"], d["n"], round(d["up"] * 100))
                       for d in cd)
    else:
        cn = "所属概念里没有 ≥3 只且过半在上升的 —— 孤例不算趋势"

    if rd.get("hard") is not None:
        rn = ("当日异动 · %s · 硬逻辑 %d 项（产能/订单/净利/研报…）· 情绪词 %d 个"
              % (rd.get("tag") or "—", rd["hard"], rd.get("soft") or 0))
    else:
        rn = rd.get("note") or "—"

    if md.get("amt_yi") is not None:
        mn = ("成交额 %.2f 亿 · 榜内分位 %.0f%% · 涨幅 %s%%"
              % (md["amt_yi"], md["amt_pct"] * 100, trim(x.get("_pct") or 0, 2)))
    else:
        mn = md.get("note") or "—"

    head = ('<div class="shd"><b>%s</b><span class="sub">/100</span>'
            '<em>全池第 %d 名（共 %d 只）</em></div>'
            % (trim(x["total"], 1), x.get("rank") or 0, x.get("_n") or 0))

    return card("综合评分<span>排名趋势 35 + 概念趋势 25 + 上榜原因 20 + 资金 20</span>",
                head + row("排名趋势", t["pts"], 35, esc(tn))
                + row("概念趋势", c, 25, esc(cn))
                + row("上榜原因", r, 20, esc(rn))
                + row("资金", m, 20, esc(mn))
                + '<div class="dv-detail" style="margin-top:10px">'
                "这是本机自算的口径，与下方「人气榜原始因子」不同源："
                "那套是上游按热度/动量/位置加权，抓不到「名次正在快速上冲」这件事，"
                "所以另算一套。两套并列展示，判断时以四维为主、原始因子作参照。"
                "</div>")


def _factors(e) -> str:
    rows_data = [
        ("L 位置分", e.get("L")), ("M 动量分", e.get("M")),
        ("连板加分", e.get("board_bonus")), ("龙虎榜因子", e.get("lhb_factor")),
        ("流通市值因子", e.get("mv_factor")), ("概念因子", e.get("concept_factor")),
        ("抱团因子", e.get("cluster_factor")), ("操作因子", e.get("op_factor")),
        ("位置因子", e.get("pos_factor")),
        ("综合原始分", e.get("composite")), ("相对分", e.get("rel_score")),
        ("最终得分", e.get("score_final")),
    ]
    cells = "".join("<div><span>%s</span><b>%s</b></div>" % (esc(k), esc(_n(v, 3)))
                    for k, v in rows_data)
    return card("评分拆解<span>人气榜各因子原值</span>",
                '<div class="kv">%s</div>'
                '<div class="dv-detail" style="margin-top:12px">'
                "L/M 是位置与动量分项（0–1），其余带 factor 的字段是乘数（1.0 表示不加不减）。"
                "最终得分＝这些因子加权后再归一化，所以它不是它们的简单连乘，别试图手算复现。"
                "</div>" % cells)


def _lhb_card(l, quote_date: str = "") -> str:
    """龙虎榜（个股上榜）—— 唯一能验证"资金是谁"的公开证据。

    两个源拼起来：次数/净买/上榜后表现来自东财全量明细（覆盖全池），
    机构席位只有同花顺个股上榜榜前 50 名公开。所以这里必须把
    「没上榜」和「有上榜但没有机构数据」画成两种状态，否则会把"没数据"读成"没机构"。
    """
    title = "龙虎榜<span>近 30 天 · 同花顺个股上榜 + 东财明细</span>"
    if not l or not l.get("n30"):
        return card(title, empty(
            "近 30 天没上过龙虎榜。上榜是交易所按「涨幅偏离 7%/换手 20%/振幅 15%」"
            "等条件触发的公开披露，没触发就没有数据——这不等于没有资金，只是没有公开席位。"))

    jg = l.get("jg_seats")
    net = l.get("net")
    cells = [
        ("30 日上榜", "%d 次" % l["n30"], "%d 个交易日" % (l.get("days") or 0)),
        ("机构席位", ("%d 席" % jg) if jg is not None else "—",
         "参与机构位数" if jg is not None else "仅前 50 名公开"),
        ("龙虎榜净买", ('<span class="%s">%s</span>'
                        % ("red" if (net or 0) >= 0 else "green", yi(net)))
         if net is not None else "—", "买入－卖出"),
        ("上榜后表现", ("1 日 %s%% / 5 日 %s%%"
                        % (signed(l["d1"], 2) if l.get("d1") is not None else "—",
                           signed(l["d5"], 2) if l.get("d5") is not None else "—")),
         "历次上榜平均"),
    ]
    body = grid4(cells)

    last = l.get("last") or {}
    if last.get("date"):
        body += ('<div class="pk-r" style="margin-top:12px">'
                 '<b>最近一次上榜 %s</b>　%s　<span class="sub">当日 %s%%　净买 %s</span></div>'
                 % (esc(last["date"]), esc(last.get("reason") or "—"),
                    signed(last.get("pct"), 2) if last.get("pct") is not None else "—",
                    yi(last.get("net"))))
    if l.get("reason_top") and l["reason_top"] != (last.get("reason") or ""):
        body += ('<div class="sub" style="margin-top:6px">30 天内最常见上榜原因：%s</div>'
                 % esc(l["reason_top"]))
    if jg is not None and (l.get("jg_buy") or l.get("jg_sell")):
        body += ('<div class="ln">机构专用：买入 %s　卖出 %s　净额 <b class="%s">%s</b>'
                 "　—— 机构净买为正说明这一轮是机构在接，为负说明机构在出。"
                 "</div>"
                 % (yi(l["jg_buy"]), yi(l["jg_sell"]),
                    "red" if (l.get("jg_net") or 0) >= 0 else "green",
                    yi(l.get("jg_net"))))
    if l.get("dates"):
        body += ('<div class="chips" style="margin-top:10px">%s</div>'
                 % "".join('<span class="chip">%s</span>' % esc(d[5:])
                           for d in l["dates"]))
    return card(title, body)


def _money(e) -> str:
    rows_data = [
        ("龙虎榜净额", yi(e.get("lhb_net"))), ("龙虎榜机构净额", yi(e.get("lhb_org_net"))),
        ("换手率", _n(e.get("turnover"), 2, "%")), ("换手比", _n(e.get("turnover_ratio"), 1, "%")),
        ("流通市值", _n(e.get("float_mv"), 2, " 亿")),
        ("60 日位置", _n(e.get("pos60"), 3)),
        ("10 日量比", _n(e.get("turn10_ratio"), 1, "%")),
        ("10 日热度变化", _n(e.get("heat_chg10"), 1, "%")),
        ("量价 30 日", ("%s 涨 / %s 跌 / %s 平"
                       % (e.get("vp_up"), e.get("vp_down"),
                          (e.get("vp30") or 0) - (e.get("vp_up") or 0) - (e.get("vp_down") or 0)))
         if e.get("vp30") else "—"),
    ]
    cells = "".join("<div><span>%s</span><b>%s</b></div>" % (esc(k), esc(v))
                    for k, v in rows_data)
    return card("资金与筹码", '<div class="kv">%s</div>' % cells)


def _tdx_card(e) -> str:
    t = e.get("tdx") or {}
    if not t:
        return card("第三方人气排名", empty("这只票不在 tdx 榜单里（该榜只收当日 TOP50 附近）。"))
    tr = t.get("trend5")
    if tr is None:
        arrow = '<span class="sub">历史不足</span>'
    elif tr < 0:
        arrow = '<b class="red">↑%d 名</b>' % abs(tr)
    elif tr > 0:
        arrow = '<b class="green">↓%d 名</b>' % tr
    else:
        arrow = '<span class="sub">持平</span>'
    cells = [
        ("当前排名", "第 %s 名" % (t.get("current_rank") or t.get("rank")), "tdx 口径"),
        ("5 日趋势", arrow, "负数=名次前进"),
        ("连板数", "%s" % (t.get("consecutive_boards") or 0), "板"),
        ("历史天数", "%s 天" % (t.get("hist_days") or 0), "排名序列长度"),
    ]
    reason = t.get("limit_up_reason")
    body = grid4(cells)
    if reason:
        body += ('<div class="pk-r" style="margin-top:12px"><b>涨停原因</b>　%s</div>'
                 % esc(reason))
    return card("第三方人气排名<span>tdx 仓库留存 · 数据源为同花顺热榜 API</span>", body)


def _hist_chart(e) -> str:
    """人气排名轨迹：z.legaga.top 同款柱条（用户指定，替代原折线）。
    柱高＝名次倒置（第 1 名最高），颜色按名次分档，柱下标当日名次。"""
    t = e.get("tdx") or {}
    rows = t.get("hist") or []
    if len(rows) < 2:
        return card("人气排名轨迹", empty("这只票没有排名历史（不在 tdx 榜单或历史文件缺失）。"))
    svg = rank_bars(rows, w=1100, h=120)
    return card("人气排名轨迹<span>%d 天 · 柱高＝名次（越前越高）· 红热灰冷</span>" % len(rows), svg)


def _hot_card(e) -> str:
    h = e.get("hot") or {}
    if not h:
        return card("同花顺热榜", empty("今天不在同花顺热榜（该榜盘中/日榜各 100 只）。"))
    rows = []
    pairs = [("盘中小时榜", h.get("hot_hour"), h.get("hot_hour_rate")),
             ("日榜", h.get("hot_day"), h.get("hot_day_rate"))]
    for label, order, rate in pairs:
        rows.append("<tr>%s%s%s</tr>" % (
            td(label, left=True),
            td("第 %s 名" % order if order else "未上榜"),
            td("%.1f 万" % (num(rate) / 1e4) if rate else "—")))
    body = table(["口径", "名次", "热度"], "".join(rows), "l r r")
    if h.get("popularity_tag"):
        body += ('<div class="pk-r" style="margin-top:12px">人气标签　<b>%s</b></div>'
                 % esc(h["popularity_tag"]))
    return card("同花顺热榜", body)


def render(code: str, e, data, meta) -> str:
    if e is None:
        body = (
            '<div class="hero"><div class="eyebrow">个股详情</div>'
            "<h1>没这只票的数据</h1>"
            '<div class="meta">代码 %s 不在今日合并数据里。合并范围＝人气榜 148 只 + tdx 榜单 43 只 + '
            "同花顺热榜 200 只，未覆盖全市场 5000 只。</div></div>"
            % esc(code)
            + card("换个入口", '<div class="search"><form method="get" action="/rank">'
                   '<input name="q" value="%s" placeholder="输入代码或中文名">'
                   '<button type="submit">搜索</button></form></div>'
                   '<div class="warn">想看全市场的任意个股，需要另接一份行情源（P4 待定），'
                   "当前版本不假装能查所有票。</div>" % esc(code)))
        return page("未找到 %s" % code, "/rank", body)

    name = e.get("name") or code
    pct = e.get("pct")

    # 四维评分只算一次：build 会遍历全池建标签池，个股页里调两次就白跑一遍。
    _sc_all = scoring.build(data)
    sc = (_sc_all.get("by_code") or {}).get(str(code).zfill(6)[:6])
    if sc:
        sc["_n"] = (_sc_all.get("meta") or {}).get("n") or 0
        sc["_pct"] = pct
    tags = ""
    if e.get("board_tag"):
        tags += '<span class="tag n">%s</span>' % esc(e["board_tag"])
    if e.get("limit_up"):
        tags += '<span class="tag n">涨停</span>'
    if e.get("launch"):
        tags += '<span class="tag">%s</span>' % esc(e["launch"])
    if e.get("is_leader"):
        tags += '<span class="tag n">概念龙头</span>'
    if e.get("benefit_lv"):
        tags += '<span class="tag">利多%s</span>' % esc(e["benefit_lv"])

    hero = (
        '<div class="hero"><div class="eyebrow">个股详情</div>'
        '<div class="hd"><h1>%s</h1><span class="c">%s</span>%s</div>'
        '<div class="hd" style="margin-top:10px"><span class="big %s">¥%.2f</span>'
        '<span class="big %s" style="font-size:19px">%s%%</span></div>'
        '<div class="ln">%s</div></div>'
        % (esc(name), esc(code),
           tags,
           "red" if num(pct) >= 0 else "green",
           num(e.get("price")),
           "red" if num(pct) >= 0 else "green",
           signed(pct, 2) if pct is not None else "—",
           esc(normalize.line(e))))

    body = "".join([
        hero,
        '<div class="card">%s</div>' % _kpi(e),
        # 四维评分紧随 KPI：这是本页的主评分，回答"它在全池排第几、为什么"。
        _score_card(sc),
        # 上榜原因紧跟在分数后面：用户点进个股页第一个想知道的不是"它多少分"，
        # 而是"它凭什么涨"。这段来自同花顺逐股异动的 reason 字段。
        _reason_card((data.get("abnormal") or {}).get(code), data.get("quote_date") or ""),
        _concepts(e, data, (_sc_all.get("tags") or {})),
        _tdx_card(e),
        _hot_card(e),
        _hist_chart(e),
        _lhb_card((data.get("lhb") or {}).get(code), data.get("quote_date") or ""),
        _money(e),
        _factors(e),
    ])
    return page("%s %s · A 股全景" % (name, code), "/rank", body,
                subtitle="本地 · 数据真值",
                tail=footer("数据来源：人气榜（yjj798/renqibang）· tdx（yjj79819/tdx）· 同花顺热榜",
                            "K 线不在此页——本站定位是人气与概念聚合，不是看盘软件。"))
