# -*- coding: utf-8 -*-
"""复盘页（/）与公众号版（/mp）。

版式与模块顺序严格对齐 d.legaga.top 现有页面（worker.mjs renderPage），
唯一新增是「涨停驱动词」卡片——那是 Python 链独有、d 站原本缺的模块。
"""
from __future__ import annotations

from sec_core import build_narrative, driver_summary, WIDE
from .components import (esc, num, rnd, trim, signed, yi, clamp, bj_time, temp_color,
                         pct_span, card, table, td, grid4, warn, empty, line_chart, tabset)
from .nav import nav
from .theme import THEME_BOOT, THEME_TOGGLE_JS


_DEFAULTS = {
    "breadth": {"up": 0, "down": 0, "flat": 0, "limit_up": 0, "limit_down": 0,
                "broken": 0, "suspended": 0, "amount": 0, "prev_amount": 0,
                "amount_change": 0},
    "sentiment": {"seal_rate": 0, "max_board": 0, "sprint_rate": 0, "continue_count": 0,
                  "top_board_stock": "", "main_net": 0},
    "ladder": [], "hot_sectors": [], "sector_flow": [], "blocks": [],
    "main_force": [], "themes": {"date": "", "items": []},
    "lhb": {"date": "", "count": 0, "org_count": 0, "seat_count": 0, "up": 0, "down": 0,
            "net_total": 0, "stocks": []},
    "sources": {}, "degraded": [],
}


def fill_defaults(snap: dict) -> dict:
    """把缺失的段补成空结构：某个上游接口挂掉时，页面显示"暂无"而不是 500。"""
    out = dict(snap)
    for k, v in _DEFAULTS.items():
        if out.get(k) is None:
            out[k] = v
    return out


# ---------------------------------------------------------------- 当日结论
# ---------------------------------------------------------------- 行业热度（v3 新增）
def _sector_mini(sc, limit: int = 8) -> str:
    """首页的行业热度小表：哪一片在整体动。

    数据来自 score.build 里顺带算好的 sector 行业榜（评分类口径，不是快照的
    精选板块）——放这里是为了和「下一交易日题材前瞻」形成故事/行业的对照：
    题材讲的是故事，行业讲的是这一片是不是真的在动。
    """
    rows = ((sc or {}).get("sector") or {}).get("rows") or []
    if not rows:
        return ""
    out = []
    for r in rows[:limit]:
        out.append("<tr>%s%s%s%s%s</tr>" % (
            td("<b>%s</b>%s" % (esc(r["name"]),
                                ' <span class="tag n">热</span>' if r["hot"] else ""),
               left=True),
            td('<b class="%s">%s%%</b>' % ("red" if num(r["pct"]) >= 0 else "green",
                                           signed(r["pct"], 2))),
            td("%s / %s" % (r["up"] if r["up"] is not None else "—",
                            r["down"] if r["down"] is not None else "—")),
            td(('%d' % r["lu"]) if r["lu"] else '<span class="sub">0</span>'),
            td(esc(r.get("leader") or "—"), left=True)))
    return table(["行业", "指数涨幅", "涨 / 跌", "池内涨停", "领涨股"],
                 "".join(out), "l r r r l")


def render_narrative(snap, dv) -> str:
    items = build_narrative(snap, dv)
    rows = []
    for i, (k, v) in enumerate(items, 1):
        rows.append(
            '<div class="nar-i"><div class="nar-n">%d</div><div class="nar-b">'
            '<div class="nar-t">%s</div><div class="nar-v">%s</div></div></div>'
            % (i, esc(k), v))
    return ('<div class="card nar"><h2>当日结论<span>规则自动生成 · 每句可回溯到字段</span></h2>'
            "%s%s</div>") % (
        "".join(rows),
        warn("以上由规则模板生成，不是模型撰写的判断。它只能归纳「今天发生了什么」，"
             "不能预判明天，也读不到政策、研报、公告这类盘外信息——那些仍然需要人看。"))


# ---------------------------------------------------------------- 观察池
def _card_a(x, seen, tier="a") -> str:
    price = ("收 %.2f　" % x["price"]) if x["price"] else ""
    key = (x["sector"], x["reason"])
    if not x["reason"]:
        rs = '<div class="pk-r" style="color:var(--muted)">无公开涨停原因</div>'
    elif key in seen:
        rs = '<div class="pk-r" style="color:var(--muted)">板块逻辑同上（%s）</div>' % esc(x["sector"])
    else:
        seen[key] = 1
        rs = ('<div class="pk-r">%s　<span style="color:var(--muted);font-size:11px">'
              "板块级逻辑</span></div>") % esc(x["reason"])
    c = "#d9363e" if x["score"] >= 75 else ("#e8804a" if x["score"] >= 60 else "#6b7280")
    sector = ("板块 %s%s" % (esc(x["sector"]),
                             "（第 %d）" % x["sector_rank"] if x["sector_rank"] else "")
              if x["sector"] else "板块 —")
    risks = ""
    if x["risks"]:
        risks = '<div class="pk-x">%s</div>' % "".join(
            "<i>%s</i>" % esc(r) for r in x["risks"])

    # 分数徽章：推荐序（综合 55% + 共振 45%）是排序依据，所以它最大；
    # 共振分是「今天这一板的质量」，四维分是「这波人气在不在上升」，两者都摊开给看。
    rec = x.get("rec")
    if rec is None:
        rec = x["score"]
    rc_ = "#d9363e" if rec >= 70 else ("#e8804a" if rec >= 60 else "#6b7280")
    badge = ('<span style="margin-left:auto;display:inline-flex;align-items:baseline;gap:5px">'
             '<b class="pk-rs" style="color:%s" title="推荐序 = 四维综合分×55%% + 共振分×45%%">%s</b>'
             '<i class="lb">推荐</i>'
             '<b class="pk-s">%d</b><i class="lb">共振</i>'
             % (rc_, trim(rec, 1), x["score"]))
    if x.get("sc") is not None:
        cls = "r" if x["sc"] >= 75 else ("o" if x["sc"] >= 60 else "g")
        badge += ('<span class="bs %s" title="四维综合分 · 全池第 %s 名 / %s 只">榜单 %s</span>'
                  % (cls, x.get("sc_rank") or "—", x.get("sc_n") or "—", trim(x["sc"], 1)))
    else:
        badge += ('<span class="bs g" title="不在人气/tdx 榜，四维分按 0 计">未入榜</span>')
    badge += "</span>"
    via = ('<span class="tag n">榜单通道</span>' if x.get("via") == "score" else "")
    chips = ""
    if x.get("sc_concepts"):
        chips = ('<div class="chips">%s</div>'
                 % "".join('<span class="chip">%s</span>' % esc(t)
                           for t in x["sc_concepts"]))
    return (
        '<div class="pk %s"><div class="pk-h"><span class="pk-n">%s</span>'
        '<span class="pk-c">%s</span>%s%s%s</div>'
        '<div class="pk-m"><b>%d 板</b>　首封 %s　%s%s</div>%s'
        '<div class="pk-w">%s</div>%s%s</div>'
    ) % (tier, esc(x["name"]), esc(x["code"]), via, badge,
         "", x["board"],
         esc(x["first"] or "—"), price, sector, rs,
         esc("　·　".join(x["why"]) or "—"), risks, chips)


def _card_c(x) -> str:
    price = ("收 %.2f　" % x["price"]) if x["price"] else ""
    tail = "" if x["sector_hot"] else "<i>无板块共振</i>"
    return (
        '<div class="pk c"><div class="pk-h"><span class="pk-n">%s</span>'
        '<span class="pk-c">%s</span><span class="pk-s" style="margin-left:auto;color:var(--acc)">%d</span></div>'
        '<div class="pk-m">%s%s　主力占比 %s%%（榜内第 %s）　%s</div>'
        '<div class="pk-w">%s</div>'
        '<div class="pk-x"><i>未涨停，承接要次日验证</i>%s</div></div>'
    ) % (esc(x["name"]), esc(x["code"]), x["score"], price, pct_span(x["pct"]),
         trim(x["mf_pct"], 1), x["rank"], esc(x["sector"] or ""),
         "行业命中当日热门板块，资金与题材同向" if x["sector_hot"] else "行业未进热门板块，属试盘性质",
         tail)


def render_picks(pk) -> str:
    if not pk:
        return ""
    rg = pk["regime"]
    rc = {"ice": "#12a35c", "cold": "#3f9d76", "mid": "#c9a227",
          "warm": "#e8804a", "hot": "#d9363e"}.get(rg["key"], "#6b7280")

    h = ['<div class="card"><h2>今日观察池<span>扫描 %d 只涨停</span></h2>' % pk["scanned"]]
    h.append('<div class="gate" style="border-left-color:%s">'
             '<div class="gate-h"><b style="color:%s">环境判定：%s</b>'
             '<span class="gate-pos">建议仓位 %s</span></div>'
             '<div class="gate-a">%s</div></div>'
             % (rc, rc, esc(rg["label"]), esc(rg["pos"]), esc(_ADVICE[rg["key"]])))

    if pk["sector_dist"]:
        colors = ["#d9363e", "#e8804a", "#c9a227", "#3f9d76", "#2563eb", "#7c3aed"]
        note = "　·　".join('<b style="color:%s">%s</b> %d'
                            % (colors[i % len(colors)], esc(d["name"]), d["n"])
                            for i, d in enumerate(pk["sector_dist"]))
        if len(pk["sector_dist"]) <= 2:
            note += "　—— 今日只有这几条线有板块效应"
        h.append('<div class="pk-note">入选分布：%s</div>' % note)

    seen = {}
    h.append('<div class="tier"><div class="tier-h a">A 档 · 主线共振'
             "<span>按推荐序排（四维综合分 55% + 共振分 45%）· 入选：连板 ≥ 2 + 板块前 6 + 共振 ≥ 55，"
             "或四维榜 ≥ 75 且名次在连续上升</span></div>")
    h.append("".join(_card_a(x, seen, "a") for x in pk["a"]) if pk["a"]
             else '<div class="pk-empty">今日无符合条件的主线标的——'
                  "连板股都不在热门板块里，也没有名次在冲的票，接力环境不佳。</div>")
    h.append("</div>")

    h.append('<div class="tier"><div class="tier-h b">B 档 · 首板共振'
             "<span>首板 + 共振分 ≥ 55</span></div>")
    h.append("".join(_card_a(x, seen, "b") for x in pk["b"]) if pk["b"]
             else '<div class="pk-empty">今日无高分首板——涨停质量普遍偏低。</div>')
    h.append("</div>")

    if pk["dropped"]:
        h.append('<div class="pk-note" style="background:var(--warnbg);border-color:var(--warnln)">另需单独盯：%s'
                 " 按规则不进 A 档，但它是全场高度的风向标——它次日能不能续，比任何分数都重要。</div>"
                 % "、".join("<b>%s</b>（%d 板 · 仅「%s」标签）"
                            % (esc(x["name"]), x["board"], esc(x["sector"]))
                            for x in pk["dropped"]))

    h.append('<div class="tier"><div class="tier-h c">C 档 · 资金异动'
             "<span>主力榜前列 + 上涨但未涨停</span></div>")
    h.append("".join(_card_c(x) for x in pk["c"]) if pk["c"]
             else '<div class="pk-empty">今日主力资金榜无「上涨但未涨停」的标的。</div>')
    h.append("</div>")

    h.append(warn(esc(pk["note"]) +
                  "<br><b>这不是推荐，是筛选结果。</b>共振分衡量「板块 + 资金 + 时间 + 高度」的当日一致性，"
                  "能过滤掉孤立涨停和尾盘偷袭，但它不预测次日涨跌，也不含估值与基本面判断。"
                  "涨停原因来自板块级标注，同板块个股会共用一条逻辑；价格仅取自主力资金榜，未入榜的留空。"))
    h.append("</div>")
    return "".join(h)


_ADVICE = {
    "hot": "赚钱效应最强，也是退潮前夜。只做低位补涨，不接高位连板；已有盈利分批兑现。",
    "warm": "主线清晰，可正常参与。优先主线首板与二板，单票不追高，赚情绪的钱。",
    "mid": "结构性行情。只做有板块效应、板块内多股涨停的首板；孤立涨停不参与。",
    "cold": "晋级率低、接力容易亏。只做低吸不追涨，宁可错过不做错。",
    "ice": "空仓或极轻仓观察。这个阶段打板期望收益为负，等情绪修复再说。",
}


# ---------------------------------------------------------------- 驱动词（d 站缺的模块）
def render_drivers(snap) -> str:
    sm = driver_summary(snap)
    if not sm:
        return ('<div class="card"><h2>涨停驱动词<span>个股级口径</span></h2>%s</div>'
                % empty("本日未采集驱动词（需联网抓同花顺逐股异动，或用 --no-reasons 跳过）"))
    c = sm["coverage"]
    rows = []
    for d in (sm["all"] or [])[:20]:
        mark = ""
        if d["generic"]:
            mark = '<span class="dv-line">泛</span>'
        elif not d["in_sector_view"] and d["count"] >= 2:
            mark = '<span class="dv-line x">暗线</span>'
        stocks = "、".join(s["name"] for s in (d.get("stocks") or [])[:6])
        rows.append("<tr>%s%s%s%s<td class=\"l dv-detail\">%s</td></tr>" % (
            td(esc(d["keyword"]), left=True),
            td(d["count"]),
            td(d["max_board"]),
            td(mark or "—"),
            esc(stocks)))
    body = ('<div class="dv-cov">按个股驱动词聚类（同花顺异动解读），命中 '
            "<b>%d/%d</b> 只涨停（%.0f%%）；过期跳过 %d 只。</div>"
            % (c["hit_same_day"], c["pool"], c["rate"], c.get("stale_skipped", 0)))
    body += table(["驱动词", "只数", "最高板", "性质", "成分股"], "".join(rows),
                  aligns="l r r r l", empty="本日没有可聚类的驱动词")
    body += warn("「暗线」= 55188 板块榜里根本没有这个词，只能从个股驱动词看得见。"
                 "接口每只票只保留最近一次异动，错过当日无法回补，命中率会如实显示。")
    return card("涨停驱动词", body, "同花顺异动 · 个股级")


# ---------------------------------------------------------------- 整页
def render(snap, hist, dv, pk, offline_banner: str = "", sc=None,
           tab: str = "", base: str = "/") -> str:
    snap = fill_defaults(snap)
    b, s = snap["breadth"], snap["sentiment"]
    tc = temp_color(dv["temp"]["score"])

    bars = "".join(
        '<div class="bar"><div>%s</div><div class="track">'
        '<div class="fill" style="width:%s%%;background:%s"></div></div>'
        '<div class="bval">%s%s</div></div>'
        % (esc(it["name"]),
           rnd(clamp(it["score"], 0, 100), 1),
           "#d9363e" if it["score"] >= 60 else ("#e0a33c" if it["score"] >= 40 else "#3f9d76"),
           trim(it["value"], 1), esc(it["unit"]))
        for it in dv["temp"]["items"])

    def _ladder_row(l):
        names = [x["name"] for x in (l.get("stocks") or []) if x.get("name")]
        shown = "、".join(names[:12])
        if len(names) > 12:
            shown += "　等 %d 只" % len(names)
        b = l["board"]
        cls = "r" if b >= 4 else ("o" if b == 3 else ("y" if b == 2 else "g"))
        return "<tr>%s%s%s</tr>" % (
            td('<span class="bs %s">%d 板</span>' % (cls, b), left=True),
            td("%s 只" % l["count"]),
            td('<span style="white-space:normal;color:var(--t2)">%s</span>' % esc(shown),
               left=True))

    ladder_rows = "".join(_ladder_row(l) for l in snap["ladder"])

    def _sec_row(i, x):
        cls = "r" if i == 1 else ("o" if i == 2 else ("y" if i == 3 else "g"))
        return ("<tr>%s%s%s</tr>" % (
            td('<span class="bs %s">%d</span> %s' % (cls, i, esc(x["name"])), left=True),
            td('<b class="red">%d</b>' % x["limit_up_count"]),
            td(x.get("max_board") or "—")))

    sector_rows = "".join(_sec_row(i, x) for i, x in enumerate(snap["hot_sectors"], 1))

    block_rows = "".join(
        "<tr>%s%s%s%s</tr>" % (
            td(esc(x["name"]), left=True),
            td("%s%%" % signed(x["inc"]), "red" if num(x["inc"]) >= 0 else "green"),
            td(yi(x["main_net"])),
            td(rnd(x["strength"], 0)))
        for x in snap["blocks"])

    theme_items = (snap.get("themes") or {}).get("items") or []
    theme_html = ""
    for i, t in enumerate(theme_items[:6], 1):
        tags = ""
        if t.get("is_new"):
            tags += '<span class="tag n">新增</span>'
        if t.get("is_hot"):
            tags += '<span class="tag">热门</span>'
        stks = "".join(
            '<span class="stk">%s <b class="%s">%s%%</b></span>'
            % (esc(x["name"]), "red" if num(x.get("pct")) >= 0 else "green",
               signed(x.get("pct"), 1))
            for x in (t.get("stocks") or []))
        theme_html += ('<div class="theme"><div class="t1">%d. %s %s</div>'
                       '<div class="t2">%s</div>'
                       '<div class="t3">涨停 %s 只 · 当日 %s%%　%s</div></div>'
                       % (i, esc(t["name"]), tags,
                          esc(t.get("title") or t.get("summary") or ""),
                          t.get("limit_up_count"), signed(t.get("change_pct"), 2), stks))

    lhb = snap["lhb"]
    lhb_rows = "".join(
        "<tr>%s%s%s%s%s</tr>" % (
            td(esc(x["name"]), left=True),
            td("%s%%" % signed(x["pct"]), "red" if num(x["pct"]) >= 0 else "green"),
            td(yi(x["net"])),
            td(esc(x.get("org") or "—")),
            td('<span style="white-space:normal;color:var(--muted);font-size:12px">%s</span>'
               % esc("·".join(x.get("topics") or [])), left=True))
        for x in (lhb.get("stocks") or [])[:10])

    hist_chart = hist if hist and len(hist) > 1 else None
    if hist_chart:
        chart_html = (
            '<div style="font-size:12px;color:var(--muted);margin:0 0 4px">情绪温度</div>'
            + line_chart(hist_chart, "temp", "#2563eb")
            + '<div style="font-size:12px;color:var(--muted);margin:14px 0 4px">封板率 %</div>'
            + line_chart(hist_chart, "seal_rate", "#d9363e", "%")
            + '<div style="font-size:12px;color:var(--muted);margin:14px 0 4px">涨停家数</div>'
            + line_chart(hist_chart, "limit_up", "#e8804a", " 只"))
    else:
        chart_html = empty("从今天开始积累，攒够 2 个交易日就能看到轨迹。"
                           "满 20 个交易日后，情绪温度自动从经验阈值切换为历史分位。")

    amt_pct = b["amount_change"] / b["prev_amount"] * 100 if b["prev_amount"] else 0

    if dv["temp"]["mode"] == "rank":
        mode_note = "当前按历史分位计算（样本 %d 个交易日）。" % dv["sample_days"]
    else:
        mode_note = ("当前样本仅 %d 个交易日，未达分位计算门槛，暂用经验阈值，"
                     "满 20 个交易日后自动切换为历史分位。" % dv["sample_days"])

    # ---- 四栏（2026-11-02 用户令：一页太长，改成分栏点开看）
    # 分栏只做「收纳」，不删模块也不改口径：11 个模块全在，只是按"看什么"归堆。
    # 情绪总览 = 一眼判断今天冷不冷；观察池 = 明天做不做、做谁；
    # 涨停结构 = 涨停都堆在哪；题材资金 = 明天可能烧到哪、钱从哪来。
    mood = "".join([
        render_narrative(snap, dv),
        card("情绪分项", '<div class="bars">%s</div>' % bars),
        card("市场广度",
             grid4([("上涨", '<span class="red">%d</span>' % b["up"],
                     "占比 %s%%" % trim(dv["up_ratio"], 1)),
                    ("下跌", '<span class="green">%d</span>' % b["down"],
                     "平盘 %d" % b["flat"]),
                    ("涨停 / 跌停",
                     '<span class="red">%d</span> / <span class="green">%d</span>'
                     % (b["limit_up"], b["limit_down"]),
                     "炸板 %d 只" % b["broken"]),
                    ("两市成交", yi(b["amount"]), "较昨日 %s%%" % signed(amt_pct, 1))])
             + warn("口径提示：本页涨停/跌停取全 A 行情统计（含北交所、ST），"
                    "封板率与炸板数取同花顺口径，两者可能存在数只差异，属正常现象。")),
        card("历史轨迹", chart_html, "累计 %d 个交易日" % (len(hist) if hist else 1)),
    ])

    pool = render_picks(pk) or empty("今日观察池未生成：缺共振分或四维分模块。")

    struct = "".join([
        card("涨停梯队",
             table(["高度", "数量", "个股"], ladder_rows, aligns="l r l", empty="暂无梯队数据"),
             "最高 %s 板 · %s" % (s["max_board"], esc(s.get("top_board_stock") or ""))),
        card("热门板块",
             table(["板块", "涨停", "最高板"], sector_rows, aligns="l r r", empty="暂无板块数据"),
             "按涨停数为序"),
        card("精选板块",
             table(["板块", "涨幅", "主力净额", "强度"], block_rows, aligns="l r r r",
                   empty="暂无板块数据"),
             "主力净额 / 强度分"),
        render_drivers(snap),
    ])

    flow = "".join([
        card("下一交易日题材前瞻", theme_html or empty("暂无题材前瞻数据"),
             esc((snap.get("themes") or {}).get("date") or "")),
        # 行业维度与题材是两套口径：题材=故事，行业=这一片是不是整体在动。
        # 双轮（两者同时热）的票在 /industry 页有完整名单，这里只给 TOP8 一眼货。
        card("行业热度<span>申万行业指数</span>",
             _sector_mini(sc) or empty("暂无行业数据"),
             ("双轮驱动 %d 只 · 完整行业榜见「行业」页"
              % (((sc or {}).get("meta") or {}).get("n_double") or 0))
             if sc else "行业页见顶部导航"),
        card("龙虎榜",
             grid4([("机构席位", lhb.get("org_count", 0), "家"),
                    ("营业部席位", lhb.get("seat_count", 0), "个"),
                    ("上榜涨 / 跌",
                     '<span class="red">%s</span> / <span class="green">%s</span>'
                     % (lhb.get("up", 0), lhb.get("down", 0)), "家"),
                    ("净买入合计", yi(lhb.get("net_total")), "榜单口径")])
             + table(["名称", "涨幅", "净买", "机构", "题材"], lhb_rows,
                     aligns="l r r r l", empty="暂无龙虎榜数据"),
             "%s · %s 只上榜 · 净买 %s"
             % (esc(lhb.get("date") or ""), lhb.get("count", 0), yi(lhb.get("net_total")))),
    ])

    tabs_html = tabset("home", [
        ("mood", "情绪总览", "%s · %s" % (rnd(dv["temp"]["score"], 0), dv["temp"]["level"]), mood),
        ("pool", "观察池",
         ("A%d · B%d · C%d" % (len(pk["a"]), len(pk["b"]), len(pk["c"]))) if pk else "",
         pool),
        ("struct", "涨停结构", "涨停 %d · 炸板 %d" % (b["limit_up"], b["broken"]), struct),
        ("flow", "题材资金", "题材 %d · 龙虎 %d"
         % (len(theme_items[:6]), lhb.get("count", 0)), flow),
    ], tab, base)

    parts = [
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        # 复盘页是自拼外壳（不走 shell.page），主题 boot 必须在这里单独引入，
        # 否则这一页的 ◐ 按钮就是死按钮——Firefox 里"不能切换风格"就是这么来的。
        THEME_BOOT,
        "<title>每日复盘 · %s</title>" % esc(snap.get("trade_date") or ""),
        "<style>%s</style></head><body>" % _css(),
        nav("/"),
        offline_banner,
        ('<div class="wrap"><div class="warn" style="margin-bottom:14px">'
         "<b>部分数据源异常</b>：%s。相关模块显示为「暂无」，不是页面坏了。</div></div>"
         % esc("；".join(snap.get("degraded") or []))) if snap.get("degraded") else "",
        '<div class="wrap">',

        '<div class="hero"><div class="eyebrow">A 股每日复盘 · 自动采集</div>',
        "<h1>%s 市场情绪</h1>" % esc(snap.get("trade_date") or "—"),
        '<div class="meta">数据时点 %s　·　采集于 %s（北京）</div>'
        % (esc(snap.get("as_of") or "—"), esc(bj_time(snap.get("collected_at")))),
        '<div class="temp"><div><div class="tnum" style="color:%s">%s</div>'
        '<div class="tlevel" style="color:%s;background:%s18">%s</div></div>'
        '<div class="tnote">情绪温度由封板率、首板晋级率、涨停家数、连板高度、上涨占比五项加权得出。%s</div>'
        % (tc, rnd(dv["temp"]["score"], 0), tc, tc, esc(dv["temp"]["level"]), mode_note),
        "</div></div>",

        tabs_html,

        "<footer>数据来源：55188 sec.php 公开接口（overview / blocks / fry_themes / lhb_board / qxzb）"
        "＋ 同花顺逐股异动（驱动词）。指数与行情数据时点 %s，情绪指标时点 %s。"
        "<br>说明：本页为盘后快照，非实时行情；题材前瞻的日期为下一交易日，采集时间以页首北京时间为准。"
        % (esc((snap.get("sources") or {}).get("overview") or "—"),
           esc((snap.get("sources") or {}).get("qxzb") or "—")),
        ("<br><b>部分源异常：%s</b>" % esc("；".join(snap["degraded"])))
        if snap.get("degraded") else "",
        "</footer></div>%s</body></html>" % THEME_TOGGLE_JS,
    ]
    return "".join(parts)


def _css() -> str:
    from .theme import CSS
    return CSS


# ---------------------------------------------------------------- 公众号版
def render_mp(snap, dv, pk) -> str:
    """纯数据无个股，全内联样式（微信编辑器会剥 <style>）。"""
    b, s = snap["breadth"], snap["sentiment"]
    tc = temp_color(dv["temp"]["score"])

    def row(k, v):
        return ('<tr><td style="padding:7px 8px;border-bottom:1px solid #eee;color:#666;'
                'font-size:13px">%s</td><td style="padding:7px 8px;border-bottom:1px solid #eee;'
                'text-align:right;font-size:13px;font-weight:600">%s</td></tr>' % (esc(k), v))

    rows = [
        row("情绪温度", '<span style="color:%s">%s（%s）</span>'
            % (tc, rnd(dv["temp"]["score"], 0), esc(dv["temp"]["level"]))),
        row("建议仓位", esc(pk["regime"]["pos"]) if pk else "—"),
        row("涨停 / 跌停", '%d / %d' % (b["limit_up"], b["limit_down"])),
        row("上涨 / 下跌", '%d / %d' % (b["up"], b["down"])),
        row("两市成交", yi(b["amount"])),
    ]
    for it in dv["temp"]["items"]:
        rows.append(row(it["name"], "%s%s" % (rnd(it["value"], 1), it["unit"])))

    sec_rows = "".join(
        row("%d. %s" % (i, x["name"]), "%d 只涨停" % x["limit_up_count"])
        for i, x in enumerate(snap["hot_sectors"][:8], 1))

    return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>%s 情绪速览</title></head>"
            '<body style="margin:0;padding:16px;background:#fff;font:15px/1.7 -apple-system,'
            '\'PingFang SC\',\'Microsoft YaHei\',sans-serif;color:#171a1f">'
            '<div style="font-size:12px;color:#999;letter-spacing:1px">A 股每日复盘</div>'
            '<div style="font-size:20px;font-weight:700;margin:4px 0 14px">%s 情绪速览</div>'
            '<table style="width:100%%;border-collapse:collapse">%s</table>'
            '<div style="font-size:14px;font-weight:700;margin:18px 0 6px">热门板块</div>'
            '<table style="width:100%%;border-collapse:collapse">%s</table>'
            '<div style="font-size:11px;color:#999;margin-top:16px;line-height:1.7">'
            "数据来自 55188 公开接口，盘后快照，非实时行情，不构成投资建议。</div>"
            "</body></html>") % (
        esc(snap.get("trade_date") or ""), esc(snap.get("trade_date") or ""),
        "".join(rows), sec_rows)
