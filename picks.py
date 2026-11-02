# -*- coding: utf-8 -*-
"""观察池（A/B/C 档 + 共振分）—— 从 d 站 worker.mjs 的 pickStocks() 逐条移植。

为什么要移植而不是"重新设计打分"：线上 d 站已有这个模块且用户在用，
分数口径一变，两边就不可比。移植后可用「同一天同一快照」对拍：
Python 与 JS 算出的 A/B/C 名单与分数必须完全一致。

共振分构成（合计上限 100）：
    板块热度 26 + 同板块涨停密度 15 + 板块主力资金 ±13 + 封板时间 17
    + 连板高度 12 + 主力资金榜 12 + 题材叠加 5
只挂泛标签的标的整体 ×0.7 降权。
"""
from __future__ import annotations

import re

from sec_core import regime_of
from render.components import num, rnd, trim, clamp, yi

# 泛标签：不指向具体产业逻辑，不能作为入选理由
WIDE = {
    "业绩增长", "大消费", "其他", "ST股", "次新股", "预盈预增", "超跌反弹", "低价股", "破净股",
    "高送转", "参股金融", "融资融券", "机构重仓", "基金重仓", "QFII重仓", "社保重仓",
    "深股通", "沪股通", "MSCI中国", "标准普尔", "富时罗素", "股权转让", "举牌", "壳资源",
}

RISK_WORDS = re.compile("减持|问询|风险提示|澄清")

# 榜单通道门槛：四维综合分 ≥ 75 且 排名趋势 ≥ 30（趋势满分 35）。
# 为什么 A 档要开这条通道：A 档原规则要求「连板 ≥ 2」，而 002088 鲁阳节能、
# 000525 红太阳 这类票的名次正在从千名外往上冲、概念也在同步走强，
# 四维分排全池第一，却因为"只是首板"被挡在 A 档外——那是规则的漏洞，不是标的的问题。
# 门槛卡在 75/30 而不是 60/20，是为了让这条通道只放"趋势已经成立"的票：
# 30 分意味着速度分与稳定分合计拿满 25 以上，只有真在连续上升才够。
CH_SCORE = 75.0
CH_TREND = 30.0


def hhmm(ts) -> str:
    """首封时间戳 → HH:MM（北京时间）。兼容秒/毫秒/已是字符串。"""
    t = num(ts)
    if not t:
        return ""
    if t > 1e11:
        t = t / 1000
    from datetime import datetime, timedelta, timezone
    try:
        return datetime.fromtimestamp(t, timezone(timedelta(hours=8))).strftime("%H:%M")
    except Exception:
        return ""


def mins_of(t: str) -> int:
    if not t or len(t) < 5:
        return 0
    try:
        return int(t[:2]) * 60 + int(t[3:5])
    except ValueError:
        return 0


def is_st(name) -> bool:
    return bool(re.search("ST|退", str(name or "")))


def is_20cm(code) -> bool:
    return bool(re.match(r"^(30|68)", str(code or "")))


def pick_sector(plates):
    """一只票常挂多个板块，取最具体那个，避免落进泛标签。"""
    for p in plates:
        if p.get("name") and p["name"] not in WIDE:
            return {"name": p["name"], "reason": p.get("reason") or "", "wide": False}
    f = plates[0] if plates else {}
    return {"name": f.get("name") or "", "reason": f.get("reason") or "",
            "wide": bool(f.get("name"))}


def pick_stocks(snap, dv, sc=None) -> dict:
    hot = snap.get("hot_sectors") or []
    hot_rank = {x["name"]: i + 1 for i, x in enumerate(hot)}
    flow = {x["name"]: x.get("net") for x in (snap.get("sector_flow") or [])}
    mfl = snap.get("main_force") or []
    mf_map = {x["code"]: x for x in mfl}

    allrows = []
    for lv in (snap.get("ladder") or []):
        board = int(lv.get("board") or 1)
        for st in (lv.get("stocks") or []):
            if not st.get("name") or is_st(st["name"]):
                continue
            pl = st.get("plates") or []
            sec = pick_sector(pl)
            sec_name = sec["name"]
            rank = hot_rank.get(sec_name, 0)
            h = hot[rank - 1] if rank else None
            hc = int(h.get("limit_up_count") or 0) if h else 0
            mf = mf_map.get(st.get("code"))
            t = hhmm(st.get("first"))
            mins = mins_of(t)

            score = 0
            why, risks = [], []

            # ① 板块热度
            if 1 <= rank <= 3:
                score += 26
            elif 4 <= rank <= 6:
                score += 18
            elif 7 <= rank <= 10:
                score += 10
            elif hc >= 3:
                score += 6
            if rank:
                why.append("板块「%s」热度第 %d 位" % (sec_name, rank))
            elif hc >= 3:
                why.append("板块「%s」内 %d 只涨停" % (sec_name, hc))

            # ② 同板块涨停密度
            if hc >= 10:
                score += 15
            elif hc >= 6:
                score += 12
            elif hc >= 4:
                score += 9
            elif hc >= 2:
                score += 5
            if hc >= 4:
                why.append("同板块 %d 只涨停" % hc)

            # ③ 板块资金
            net = flow.get(sec_name)
            if net is not None and num(net, None) is not None:
                if net > 0:
                    score += 13
                    why.append("板块主力净流入 %s" % yi(net))
                else:
                    score -= 6
                    why.append("板块主力净流出 %s" % yi(net))

            # ④ 封板时间
            if mins and mins <= 9 * 60 + 45:
                score += 17
                why.append("%s 早盘封板" % t)
            elif mins and mins <= 10 * 60 + 30:
                score += 12
                why.append("%s 上午封板" % t)
            elif mins and mins <= 11 * 60 + 30:
                score += 7
            elif mins and mins <= 14 * 60:
                score += 3
            elif mins:
                why.append("%s 尾盘封板" % t)

            # ⑤ 连板高度（首板/二板最优）
            if board == 1:
                score += 10
            elif board == 2:
                score += 12
            elif board == 3:
                score += 7
            elif board >= 4:
                score += 2

            # ⑥ 主力资金榜
            if mf:
                score += 12
                why.append("主力资金占比 %s%%（榜内第 %s）"
                           % (trim(mf.get("mf_pct"), 1), mf.get("rank")))

            # ⑦ 多题材叠加
            if len(pl) >= 2:
                score += 5
                why.append("%d 条题材叠加" % len(pl))

            if sec["wide"] and score > 0:
                score *= 0.7
                why.append("仅「%s」泛标签，已降权" % sec_name)

            if board >= 4:
                risks.append("%d 板高位" % board)
            if mins and mins > 14 * 60:
                risks.append("尾盘封板，承接弱")
            if not mf:
                risks.append("未入主力资金榜")
            if not rank and hc < 3:
                risks.append("板块无热度")
            if is_20cm(st.get("code")):
                risks.append("20cm 波动大")
            if pl and RISK_WORDS.search(sec["reason"] or ""):
                risks.append("公告含风险提示")

            allrows.append({
                "code": st["code"], "name": st["name"], "board": board, "first": t,
                "price": mf.get("price") if mf else None,
                "pct": mf.get("pct") if mf else None,
                "sector": sec_name, "sector_rank": rank, "wide": sec["wide"],
                "reason": sec["reason"], "plates": [p.get("name") for p in pl],
                "score": int(rnd(clamp(score, 0, 100), 0)), "why": why, "risks": risks,
            })

    allrows.sort(key=lambda x: -x["score"])

    # 四维分挂到每一行：A 档的「榜单通道」与卡片上的分数徽章都用它。
    # 注意两套分不同源——共振分看"今天这一板的质量"，四维分看"这波人气是否在上升"，
    # 一个抓截面，一个抓时间，所以并列展示而不是互相替换。
    sc_by = (sc or {}).get("by_code") or {}
    for x in allrows:
        s = sc_by.get(x["code"])
        if not s:
            continue
        x["sc"] = s["total"]
        x["sc_rank"] = s.get("rank")
        x["sc_n"] = (sc.get("meta") or {}).get("n") or 0
        x["sc_trend"] = (s.get("trend") or {}).get("pts")
        x["sc_concepts"] = [d["tag"] for d in (s.get("concept_detail") or [])[:3]]
        x["sc_money"] = (s.get("money_detail") or {})

    # 推荐序 = 四维综合分 55% + 共振分 45%。
    # 为什么四维分权重反过来压过共振分：共振分只看「今天这一板的质量」（封板时间、
    # 板块热度、主力占比），它是**截面**；四维分看「这波人气是否正在上升」，是**时间序列**。
    # 只按共振分排，红太阳（首板、共振 59、四维 87.4 全池第一）会排在一堆二板后面，
    # 等于把最重要的因子扔了。缺四维分的票（不在人气池）按 0 计并标「未入榜」——
    # 没有证据就是没有证据，不能给默认分。
    for x in allrows:
        x["rec"] = round(0.55 * (x.get("sc") or 0) + 0.45 * x["score"], 1)
        x["rec_has_sc"] = x.get("sc") is not None

    A = [x for x in allrows
         if x["board"] >= 2 and not x["wide"] and 0 < x["sector_rank"] <= 6
         and x["score"] >= 55][:6]
    used0 = {x["code"] for x in A}

    # 榜单通道：首板也能进 A，条件是四维分 ≥75 且趋势 ≥30。
    ch = [x for x in allrows
          if x["code"] not in used0 and not x["wide"]
          and (x.get("sc") or 0) >= CH_SCORE and (x.get("sc_trend") or 0) >= CH_TREND]
    ch.sort(key=lambda x: -(x.get("sc") or 0))
    for x in ch:
        x["via"] = "score"
    A = A + ch[:4]
    for x in A:
        x.setdefault("via", "resonance")
    # A 档内部排序改用推荐序——否则"榜单通道"进来的票永远垫底，
    # 等于给了门票不给座位（红太阳四维分第 1，却排在第 4 张卡）。
    A.sort(key=lambda x: -x.get("rec", 0))

    B = [x for x in allrows if x["board"] == 1 and x["score"] >= 55][:8]
    B = [x for x in B if x["code"] not in {y["code"] for y in A}]
    B.sort(key=lambda x: -x.get("rec", 0))
    used = {x["code"] for x in A + B}

    # C 档：资金先于价格 —— 主力榜前列但还没涨停
    C = []
    for m in mfl:
        if len(C) >= 6:
            break
        if not m.get("name") or is_st(m["name"]) or m["code"] in used:
            continue
        pct = num(m.get("pct"))
        if pct <= 0 or pct >= 9.5:
            continue
        if num(m.get("mf_pct")) < 15:
            continue
        sec = m.get("sector") or ""
        hit = hot_rank.get(sec, 0) > 0
        if not hit:
            for hn in hot_rank:
                if hn and (hn in sec or sec in hn):
                    hit = True
                    break
        C.append({
            "code": m["code"], "name": m["name"], "price": m.get("price"), "pct": pct,
            "mf_pct": num(m.get("mf_pct")), "rank": m.get("rank"),
            "sector": sec, "sector_hot": hit,
            "score": int(rnd(clamp(num(m.get("mf_pct")), 0, 60) + (30 if hit else 0), 0)),
        })

    # 被泛标签拖下去的高位股，单独提示，避免"龙头不见了"
    dropped = sorted([x for x in allrows if x["wide"] and x["board"] >= 3],
                     key=lambda x: -x["board"])[:2]

    dist = {}
    for x in A + B:
        if x["sector"]:
            dist[x["sector"]] = dist.get(x["sector"], 0) + 1
    sector_dist = sorted(({"name": k, "n": v} for k, v in dist.items()),
                         key=lambda x: -x["n"])

    return {
        "regime": regime_of(dv["temp"]["score"]),
        "a": A, "b": B, "c": C, "dropped": dropped,
        "sector_dist": sector_dist, "scanned": len(allrows),
        "note": ("推荐序 = 四维综合分 55% + 共振分 45%；共振分 = 板块热度 26 + 同板块涨停数 15 "
                 "+ 板块主力资金 ±13 + 封板时间 17 + 连板高度 12 + 主力资金榜 12 + 题材叠加 5，上限 100；"
                 "只挂泛标签（业绩增长 / 大消费 / 其他 / ST股等）的标的整体 ×0.7 降权；"
                 "不在人气池的标的四维分按 0 计（无证据不给默认分）。"
                 "分数只用于同一交易日内的排序筛选，不是收益预测。"),
    }
