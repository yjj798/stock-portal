# -*- coding: utf-8 -*-
"""榜单页 /rank：综合分 TOP10 + 一张合并人气榜 + 全站搜索。

人气榜为什么合并成一张：tdx 仓库（yjj79819/tdx）README 第一句就是
「基于同花顺热榜 API 的股票热度排名系统」——名字里的 tdx 只是仓库名，
数据是同花顺热榜的二次加工。原来分成「热榜 TOP20」和「tdx 排名」两块，
同一只票在两块里各出现一次，纯属重复。现在一行看完：名次 + 排名历史
（tdx 留存，同花顺官方不提供）+ 此刻热榜名次/热度/人气标签 + 涨停原因。
"""
from __future__ import annotations

import normalize
import score as scoring
from .components import (esc, rnd, trim, signed, yi, num, card, table, td, warn, empty,
                         rank_bars, tabset)
from .shell import page, footer

RANK_DAYS = 10       # 「10 日排名」列/趋势列取最近 10 个交易日


def _link(code, name):
    if not code:
        return esc(name or "—")
    return '<a class="sl" href="/s/%s">%s</a>' % (esc(code), esc(name or code))


def _rk(i):
    cls = " t1" if i == 1 else (" t2" if i == 2 else (" t3" if i == 3 else ""))
    return '<span class="rk%s">%d</span>' % (cls, i)


def _pct(v):
    if v is None:
        return "—"
    c = "red" if num(v) >= 0 else "green"
    return '<b class="%s">%s%%</b>' % (c, signed(v, 2))


def _search_box(q: str, tab: str = "score") -> str:
    # 搜索后仍留在原来那一栏：结果条固定在分栏上方，两栏都能看到，
    # 但不带 t 的话一次搜索就会把人踢回第一栏。
    return ('<form class="search" method="get" action="/rank">'
            '<input type="hidden" name="t" value="%s">'
            '<input name="q" value="%s" placeholder="输入代码或中文名，例如 002172 / 澳洋健康" '
            'autocomplete="off"><button type="submit">搜索</button></form>') % (esc(tab), esc(q))


def render_search(hits, q) -> str:
    if not q:
        return ""
    if not hits:
        return card("搜索「%s」" % esc(q),
                    empty("没有匹配的股票。可试 6 位代码或名字的一部分。"),
                    "代码 / 中文名双向")
    rows = []
    for e in hits:
        tdx = e.get("tdx") or {}
        rows.append(
            '<div class="pk"><div class="pk-h">%s'
            '<span class="pk-c">%s</span>'
            '<span class="pk-s" style="color:var(--up)">%s</span></div>'
            '<div class="pk-m">%s</div>'
            '%s</div>'
            % (_link(e["code"], e.get("name")),
               esc(e["code"]),
               trim(e.get("score"), 1) if e.get("score") is not None else "—",
               _meta_line(e),
               ('<div class="pk-r">%s</div>' % esc(tdx["limit_up_reason"]))
               if tdx.get("limit_up_reason") else ""))
    return card("搜索「%s」<span>%d 条</span>" % (esc(q), len(hits)), "".join(rows),
                "代码 / 中文名双向")


def _meta_line(e) -> str:
    bits = []
    if e.get("price") is not None:
        bits.append("¥%.2f" % float(e["price"]))
        bits.append(_pct(e.get("pct")))
    if e.get("ths_heat"):
        bits.append("%.1f万·%s" % (float(e["ths_heat"]) / 1e4,
                                   "日" if (e.get("ths_heat_src") or "day") == "day" else "时"))
    if e.get("heat_rank"):
        bits.append("热度第 %d" % e["heat_rank"])
    if e.get("heat_growth") is not None:
        bits.append("日环比 %s%%" % signed(e["heat_growth"], 1))
    if e.get("board_tag"):
        bits.append(esc(e["board_tag"]))
    tdx = e.get("tdx") or {}
    if tdx.get("rank"):
        bits.append("排名第 %d" % tdx["rank"])
    if e.get("benefit_lv"):
        bits.append("利多" + esc(e["benefit_lv"]))
    return "　".join(bits)


def _concept_line(e) -> str:
    cs = e.get("concepts") or normalize.split_concepts(e.get("concept_all"))
    if not cs and (e.get("hot") or {}).get("concept_tag"):
        cs = (e.get("hot") or {})["concept_tag"]
    if not cs:
        return '<span class="sub">—</span>'
    out = []
    for c in cs[:6]:
        cls = "chip lead" if e.get("is_leader") and c == cs[0] else "chip"
        out.append('<a class="%s" href="/concept?c=%s">%s</a>'
                   % (cls, esc(c), esc(c)))
    return '<div class="chips">%s</div>' % "".join(out)


# ---------------------------------------------------------------- 三区
def _heat_cell(e) -> str:
    """热度值带口径标记：绝大多数是日热度（万·日），少数是小时热度（万·时）。
    两种口径差一个数量级，不标的话并排看会误读。"""
    if not e.get("ths_heat"):
        return '<span class="sub">—</span>'
    unit = "·时" if (e.get("ths_heat_src") or "day") == "hour" else "·日"
    return "%.1f万<span class='sub'>%s</span>" % (float(e["ths_heat"]) / 1e4, unit)


def _c6(c):
    """'002172.SZ' → '002172'。榜单条目带交易所后缀，索引是裸 6 位，不转就查不到。"""
    s = "".join(ch for ch in str(c or "") if ch.isdigit())
    return s.zfill(6)[:6] if s else ""


def _dim(v, full, note="") -> str:
    """四维分项格：主数字 + 占比细条 + 一句原始读数。
    单看一个 28 分没有意义，必须同时给出满分（/35）和它从哪来。"""
    pct = max(0.0, min(1.0, num(v) / full)) if full else 0
    bar = ('<div class="dbar"><i style="width:%.0f%%"></i></div>' % (pct * 100))
    return ('<div class="dcell"><b>%s</b><span class="sub">/%d</span>%s'
            '%s</div>') % (trim(v, 1), full, bar,
                           ('<div class="dnote">%s</div>' % note) if note else "")


def _sec_composite(data, sc) -> str:
    """综合分 TOP12 —— 四维加权（趋势 35 + 概念 25 + 原因 20 + 资金 20）。

    为什么是 12 而不是 10：新模型把「排名攀升」放在第一权重，
    而这类票经常是"趋势极强但资金盘子小"，正好卡在 10~12 名之间
    （实测 002088 鲁阳节能：5 日从 1572 名冲到 29 名，趋势分全榜第 7，
    但成交额只有 1.27 亿 → 资金分 7.1，总分 64.5 排第 11）。
    只取 10 条会恰好把这些票全部切掉，等于模型白改。

    「10 日排名」列：柱条画最近 10 个交易日，起算点取这 10 天里最差的那天，
    和趋势分（取近 5 步）不是同一个窗口——两处都各自标了窗口天数，
    因为一只票"5 步在冲"和"10 日在涨"本来就是两个信息。
    """
    stocks = data.get("stocks") or {}
    rows = []
    for x in (sc.get("ranked") or [])[:12]:
        code = x["code"]
        e = stocks.get(code) or {}
        tr = x.get("trend_detail") or {}
        hist = (e.get("tdx") or {}).get("hist") or []
        seq10 = [h["rank"] for h in hist if h.get("rank")][-RANK_DAYS:]
        trace = ""
        if len(seq10) >= 2:
            i0 = seq10.index(max(seq10))
            if i0 >= len(seq10) - 1:      # 一路在退 → 首日当起点，让叙述读得通
                i0 = 0
            seg10 = seq10[i0:]
            trace = ('<div class="rwrap">%s</div>'
                     '<div class="dnote">10 日：%d → <b>%d</b>（%d 个交易日）</div>'
                     % (rank_bars([{"date": "", "rank": r} for r in seq10], w=210, h=46),
                        seg10[0], seg10[-1], len(seq10)))
        else:
            hg = x["trend"].get("heat_growth")
            trace = ('<div class="dnote">无排名历史<br>热度环比 %s%%</div>'
                     % signed(hg, 1) if hg is not None else '<span class="sub">—</span>')
        cnotes = "、".join(d["tag"] for d in (x.get("concept_detail") or [])[:2]) or "无上升概念"
        rd = x.get("reason_detail") or {}
        rnote = ("硬逻辑 %d 项" % rd["hard"]) if rd.get("hard") is not None \
            else rd.get("note", "—")
        md = x.get("money_detail") or {}
        mnote = ("%.2f 亿 · 分位 %.0f%%" % (md["amt_yi"], md["amt_pct"] * 100)
                 if md.get("amt_yi") is not None else md.get("note", "—"))
        pct = e.get("pct")
        rows.append("<tr>%s%s%s%s%s%s%s%s%s%s</tr>" % (
            td(_rk(x["rank"])),
            td(_link(code, x.get("name")), left=True),
            td("¥%.2f" % float(e["price"]) if e.get("price") is not None else "—"),
            td(_pct(pct)),
            td('<b class="big">%s</b>' % trim(x["total"], 1)),
            td(_dim(x["trend"]["pts"], 35,
                    ("%.2f/日" % tr["slope"]) if tr.get("slope") is not None else "代理"),
               left=True),
            td(_dim(x["concept"], 25, cnotes), left=True),
            td(_dim(x["reason"], 20, rnote), left=True),
            td(_dim(x["money"], 20, mnote), left=True),
            td(trace, left=True),
        ))
    body = table(["#", "股票", "价格", "涨幅", "综合分", "趋势 /35", "概念 /25",
                  "原因 /20", "资金 /20", "10 日排名"],
                 "".join(rows), "l r r r r l l l l l")
    meta = sc.get("meta") or {}
    return card("综合分 TOP12<span>排名趋势 35 + 概念趋势 25 + 上榜原因 20 + 资金 20"
                "　·　%d 只有排名历史 / 共 %d 只</span>"
                % (meta.get("n_with_hist", 0), meta.get("n", 0)), body)


def _hot_cell(x) -> str:
    """同花顺热榜信息压成一列：名次 · 热度 · 人气标签。没有就 —。"""
    if not x:
        return '<span class="sub">—</span>'
    bits = []
    if x.get("order"):
        bits.append("第 %s 名" % x["order"])
    if x.get("rate"):
        bits.append("%s万" % trim(x["rate"] / 1e4, 1))
    if x.get("popularity_tag"):
        bits.append('<span class="tag n">%s</span>' % esc(x["popularity_tag"]))
    return " ".join(bits) or '<span class="sub">—</span>'


def _d10(e):
    """近 10 个交易日的名次变化：返回 (前进名次数, 10 日前名次, 当前名次) 或 None。

    负数=名次前进（好事）。用 hist 自己算，不再用 tdx 只给 5 步的 trend5——
    "5 日"和"10 日"是两个尺度，混用会让同一列的数字对不上。
    """
    hist = [h["rank"] for h in ((e.get("tdx") or {}).get("hist") or []) if h.get("rank")]
    if len(hist) < 3:
        return None
    now = hist[-1]
    ago = hist[-RANK_DAYS] if len(hist) >= RANK_DAYS else hist[0]
    return now - ago, ago, now


def _trend10(e) -> str:
    d = _d10(e)
    if d is None:
        return '<span class="sub">—</span>'
    delta, ago, now = d
    if delta == 0:
        return '<span class="sub">持平</span>'
    if delta < 0:
        return '<span class="arw red">↑%d</span>' % abs(delta)
    return '<span class="arw green">↓%d</span>' % delta


def _lhb_cell(l) -> str:
    """近 30 天上榜：次数 + 机构席位。两个字段来源不同（次数同花顺/东财，机构只同花顺），
    所以用不同样式分开画——不能让人以为"没有机构"和"没上榜"是同一件事。"""
    if not l or not l.get("n30"):
        return '<span class="sub">未上榜</span>'
    out = ['<b>%d</b><span class="sub">次</span>' % l["n30"]]
    if l.get("jg_seats") is None:
        out.append('<span class="sub">—</span>')
    elif l["jg_seats"]:
        out.append('<span class="tag n">机构 %d 席</span>' % l["jg_seats"])
    else:
        out.append('<span class="sub">无机构</span>')
    return " ".join(out)


def _net_cell(l) -> str:
    if not l or l.get("net") is None:
        return '<span class="sub">—</span>'
    v = l["net"]
    return '<b class="%s">%s</b>' % ("red" if v >= 0 else "green", yi(v))


def _sec_board(data, kind: str) -> str:
    """一张表打完人气榜 —— 这里原来有「同花顺热榜 TOP20」和「tdx 人气排名」两块，
    内容高度重合（tdx 的数据本身就是抓同花顺热榜 API 二次加工的，见 README），
    所以合并：tdx 提供排名与 30 天历史，热榜只补「此刻名次/热度/人气标签」一列。

    排序＝tdx 名次；热榜 TOP20 里没进 tdx 榜的票追加在表尾（名次列标「热」），
    这样不丢任何一只票，也不会让同一只票出现两次。

    涨停原因列已去掉：那一列和个股详情页的「上榜原因」重复，而详情页给的是
    行业原因＋公司原因全文，表格里的缩写版除了占宽度没有额外信息。
    让出来的宽度给了龙虎榜——那是详情页也没有的独立证据（近 30 天上榜次数、
    机构席位、净买额），判断"资金是不是真在里面"靠它。
    """
    stocks = data.get("stocks") or {}
    lhb = data.get("lhb") or {}
    hot = (data.get("hot_hour") if kind != "day" else data.get("hot_day")) or []
    hot_by = {_c6(x.get("code")): x for x in hot}
    tdx_top = data.get("tdx_top") or []
    tdx_codes = {_c6(x.get("code")) for x in tdx_top}

    rows = []
    n_hist = 0
    seen = set()   # 源数据里偶有同一只票重复出现（实测 002172 出现两次，同为第 4 名），渲染层去重
    for x in tdx_top:
        code = _c6(x.get("code"))
        if code in seen:
            continue
        seen.add(code)
        e = stocks.get(code) or {}
        tdx_bits = e.get("tdx") or {}
        hist = tdx_bits.get("hist") or []
        if len(hist) >= 2:
            n_hist += 1
        rows.append("<tr>%s%s%s%s%s%s%s%s%s</tr>" % (
            td(_rk(x.get("current_rank") or x.get("rank") or 0)),
            td(_link(code, x.get("name")), left=True),
            td(_pct(x.get("change_pct"))),
            td(yi(x.get("turnover"))),
            td(_trend10(e)),
            td('<div class="rwrap">%s</div>'
               % (rank_bars(hist, w=560, h=68) or '<span class="sub">无历史</span>'), left=True),
            td(_hot_cell(hot_by.get(code)), left=True),
            td(_lhb_cell(lhb.get(code)), left=True),
            td(_net_cell(lhb.get(code))),
        ))

    extra = [x for x in hot[:20] if _c6(x.get("code")) not in tdx_codes]
    for x in extra:
        code = _c6(x.get("code"))
        rows.append("<tr>%s%s%s%s%s%s%s%s%s</tr>" % (
            td('<span class="rk">热</span>'),
            td(_link(code, x.get("name")), left=True),
            td(_pct(x.get("pct"))),
            td('<span class="sub">—</span>'),
            td('<span class="sub">—</span>'),
            td('<span class="sub">仅在同花顺热榜，不在 tdx 榜（该榜只留进过前 50 的票）</span>', left=True),
            td(_hot_cell(x), left=True),
            td(_lhb_cell(lhb.get(code)), left=True),
            td(_net_cell(lhb.get(code))),
        ))

    body = table(["#", "股票", "涨幅", "成交额", "10日趋势", "30日名次",
                  "同花顺热榜", "30日上榜", "龙虎榜净买"],
                 "".join(rows), "l r r r r l l l r")
    seg = ('<div class="seg"><a class="%s" href="/rank?t=hot&amp;hot=hour">盘中小时榜</a>'
           '<a class="%s" href="/rank?t=hot&amp;hot=day">日榜</a></div>'
           % ("on" if kind != "day" else "", "on" if kind == "day" else ""))
    # 标题只留「人气榜」四个字：原来的"49 只 · 42 只有排名历史 · 热榜已并入"
    # 是给开发者看的自证，不是用户要看的信息；计数挪到卡片右上角的 span 里。
    return ('<div class="card"><h2>人气榜<span>%d 只 · %d 只有排名历史</span>%s</h2>%s</div>'
            % (len(tdx_top) + len(extra), n_hist, seg, body))


def _note_score() -> str:
    """综合榜口径（原来和人气榜共用一个 3000 字的说明卡，两栏都读得费劲）。"""
    return card("口径说明", (
        '<div class="dv-detail">'
        "<b>综合分</b>是本机自算的四维加权，满分 100："
        "<b>排名趋势 35</b>（日均对数改善 14 + 连续上升占比 11 + 当前名次 10）"
        "＋<b>概念趋势 25</b>（所属概念中正在上升的强度，标签成分少于 3 只不计）"
        "＋<b>上榜原因 20</b>（当日异动里的硬逻辑项数：产能/订单/净利/研报…）"
        "＋<b>资金 20</b>（成交额分位 12 + 涨幅 6 + 换手率 2）。<br>"
        "「趋势」用对数名次差算速度——1900 名到 600 名与 60 名到 20 名在信息量上不可比，"
        "取对数才公平；「稳」看 5 步里有几步在降，来回震荡只得一半分。<br>"
        "<b>10 日排名</b>画最近 10 个交易日的名次柱（柱高=名次，越前越高），"
        "与趋势计分窗口（近 5 步）不是同一段，两处各自标了天数。<br>"
        "<b>概念标签</b>里「三季报扭亏 / 减亏」计入趋势，「三季报增长 / 大增」不计——"
        "前者是从亏到盈的拐点（全池只有 4 只），后者是普遍现象（20 只），"
        "算进去等于给大盘加分。<br>"
        "只有 tdx 榜上的票有 30 天名次序列，其余票用热度日环比代理，"
        "且最高只给 21 分（35×0.6）——单点环比证明不了连续上升。<br>"
        "点任意股票进详情页，能看到完整的四维评分拆解、全部概念与排名轨迹。"
        "</div>"), "四维综合分 · 满分 100")


def _note_hot() -> str:
    """人气榜口径：一列一列说清数据从哪来、缺了是什么。"""
    return card("口径说明", (
        '<div class="dv-detail">'
        "<b>30 日上榜 / 机构席位 / 龙虎榜净买</b>来自龙虎榜：次数与净买取近 30 天全量，"
        "机构席位（参与机构位数＋机构专用买卖）只有同花顺个股上榜榜前 50 名公开，"
        "其余显示「—」——那是没有数据，不是没有机构。"
        "「未上榜」是另一件事：近 30 天一次没进榜。<br>"
        "<b>热度</b>单位「万·日」＝同花顺日热度 ÷ 1万；日环比是相对前一交易日。"
        "小时榜取盘中数据，两者差一个数量级，列里已标口径。<br>"
        "<b>排名与历史</b>来自开源仓库 tdx —— 它名字里的 tdx 是仓库名，"
        "<b>数据其实是抓同花顺热榜 API 再二次加工</b>（过滤 ST/亏损股、留存 30 天排名历史），"
        "所以和同花顺热榜同源，本页已合并成一张表，不重复列两遍。"
        "热榜 TOP20 里没进 tdx 榜的票接在表尾（名次列标「热」），不丢票也不重复。<br>"
        "点任意股票进详情页，能看到完整的四维评分拆解、全部概念与排名轨迹。"
        "</div>"), "龙虎榜 · 热度 · 排名来源")


def _src_note(data) -> str:
    """行情与人气两个时点不一致时，如实标出来。"""
    qd = str(data.get("quote_date") or "")
    rd = str(data.get("renqi_date") or "")
    if not rd or not qd or rd == qd:
        return ""
    return ('<div class="meta" style="margin-top:4px;opacity:.85">'
            '<b>价格 / 涨幅 / 成交额 / 换手</b>＝%s 实时行情；'
            '<b>热度 / 综合分 / 概念 / 排名历史</b>＝人气榜源 %s 收盘口径'
            '（该源盘中不更新，收盘后自动补齐）。</div>'
            % (esc(qd), esc(rd)))


def render(data, meta, q: str = "", hot: str = "hour", tab: str = "") -> str:
    stocks = data.get("stocks") or {}
    hits = normalize.search(stocks, q) if q else []
    tab = tab if tab in ("score", "hot") else "score"

    head = (
        '<div class="hero"><div class="eyebrow">A 股榜单 · 三源对照</div>'
        "<h1>今天该看什么</h1>"
        '<div class="meta">行情日 %s　·　数据时点 %s　·　本页 %d 只个股　·　刷新于 %s</div>'
        % (esc(data.get("quote_date") or "—"),
           esc(data.get("updated_at") or "—"),
           len(stocks),
           esc((meta.get("fetched_at") or "—").replace("T", " ")))
        # 人气榜是收盘后源：盘中它的热度/综合分还没更新，价格却是实时的。
        # 两个时点必须分开写，否则页面会"看起来全都是今天"。
        + _src_note(data)
        + _search_box(q, tab) + "</div>")

    degr = ""
    if data.get("degraded"):
        degr = ('<div class="card" style="padding:12px 14px"><div class="warn" '
                'style="margin:0"><b>部分数据源异常</b>：%s。相关榜单会缺行，不是页面坏了。</div></div>'
                % esc("；".join(data["degraded"])))

    # 两栏：综合榜与人气榜本来就是两种问法——「谁的分数在涨」和「谁在被看」。
    # 挤在一页里要先滚完 12 行四维拆解才看到人气榜，等于把第二张榜藏起来了。
    hot_list = (data.get("hot_hour") if hot != "day" else data.get("hot_day")) or []
    tdx_codes = {_c6(x.get("code")) for x in (data.get("tdx_top") or [])}
    n_hot = len(data.get("tdx_top") or []) + len(
        [x for x in hot_list[:20] if _c6(x.get("code")) not in tdx_codes])

    tabs_html = tabset("rank", [
        ("score", "四维综合榜", "12 只", _sec_composite(data, scoring.build(data)) + _note_score()),
        ("hot", "人气榜", "%d 只" % n_hot, _sec_board(data, hot) + _note_hot()),
    ], tab, "/rank")

    body = "".join([
        head,
        degr,
        # 搜索结果放在分栏之上：它是一次主动查询的答案，不属于任何一栏
        render_search(hits, q),
        tabs_html,
    ])
    return page("榜单 · A 股全景", "/rank", body,
                subtitle="本地 · 数据真值",
                tail=footer("数据来源：人气榜（yjj798/renqibang）· tdx 排名与历史（yjj79819/tdx，"
                            "数据源为同花顺热榜 API）· 同花顺热榜（dq.10jqka.com.cn）· "
                            "龙虎榜（同花顺个股上榜 ggph ＋ 东财龙虎榜明细）",
                            "本页只做汇总展示，不构成投资建议。"))
