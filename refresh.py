# -*- coding: utf-8 -*-
"""刷新实时层：抓三源 → 归一 → 写 data/live/bundle.json。

用法：
    python refresh.py            # 抓三个源，全部成功才算成功
    python refresh.py --allow-partial   # 哪个源挂了就跳过它，仍然出 bundle

为什么要"全成功才算成功"：三张榜互相印证才有意义。如果默默用昨天的 tdx 补上，
页面上看不出少了一块，但结论会错——宁可让刷新报错，让人知道今天缺一张榜。
--allow-partial 是给计划任务凌晨自动跑用的：那时源站偶尔维护，缺一张也别把
整站刷新卡死（页面顶部会显示"部分数据源异常"）。
"""
from __future__ import annotations

import os
import sys
import time
import traceback

import normalize
import reasons_core
import sector
import store
from fetchers import (abnormal, attr as attr_f, brieffeed, f10 as f10_f,
                      hotlist_ths, industry as industry_f,
                      lhb, renqi, spot as spot_f, tdx_rank)


def _snap_for_reasons(qdate8: str, bundle_stocks: dict):
    """给驱动词聚类准备「当日涨停池」的两种来源。

    首选当天快照的 ladder（带 55188 板块 plates，能把「暗线」判准）；
    快照缺这一天时退化成 attr 的东财涨停池，板块名从 bundle 的概念成分反查——
    口径差一点，但总比整页空着强，返回的 sec_plates 会因此偏少（暗线计数偏高）。
    """
    d8 = "%s-%s-%s" % (qdate8[:4], qdate8[4:6], qdate8[6:]) if len(qdate8) == 8 else qdate8
    try:
        got_day, snap = store.load_snapshot(d8)
        if snap and snap.get("ladder"):
            return snap
    except Exception:  # noqa: BLE001
        pass
    return None


def _fake_snap(at: dict, concept_stats: list) -> dict:
    """用东财涨停池造一个最小可用的 snap（attach 只需要 trade_date + ladder）。"""
    q = at.get("qdate") or ""
    d8 = "%s-%s-%s" % (q[:4], q[4:6], q[6:]) if len(q) == 8 else q
    by_board = {}
    for it in (at.get("today") or {}).get("zt") or []:
        by_board.setdefault(int(it.get("board") or 1), []).append(it)
    ladder = []
    for b, items in sorted(by_board.items(), reverse=True):
        ladder.append({"board": b, "count": len(items),
                       "stocks": [{"code": x["code"], "name": x.get("name") or "",
                                   "plates": []} for x in items]})
    return {"trade_date": d8, "ladder": ladder}


def run(allow_partial: bool = False) -> dict:
    errors = {}
    rq = tdx = hot = None

    try:
        rq = renqi.fetch()
    except Exception as e:  # noqa: BLE001
        errors["renqi"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    try:
        tdx = tdx_rank.fetch()
    except Exception as e:  # noqa: BLE001
        errors["tdx"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    try:
        hot = hotlist_ths.fetch()
    except Exception as e:  # noqa: BLE001
        errors["hot"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    if errors and not allow_partial:
        raise SystemExit("刷新失败，以下源没抓到：%s\n"
                         "确认要「缺一块也刷新」就加 --allow-partial。" % errors)

    idx = normalize.build(rq, tdx, hot)

    # ---- 实时行情覆盖：人气榜是收盘后源，盘中它的 price/pct 还停在上一个交易日。
    #      不覆盖的话，午盘打开榜单页看到的是"行情日 = 前天"，价格全是旧的。
    #      只动 price/pct/amount/turnover 四个行情字段，热度/评分/概念/排名不动。
    sp = {}
    try:
        sp = spot_f.fetch(codes=list(idx.keys()))
        n_cov = spot_f.overlay(idx, sp)
        spot_f.save(sp, {"src": "eastmoney", "n": len(sp),
                         "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        print("  行情覆盖 %d/%d 只（实时源）" % (n_cov, len(idx)))
    except Exception as e:  # noqa: BLE001
        errors["spot"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    # ---- 行业板块（申万行业指数）：概念讲的是"故事"，行业讲的是"这一片是不是
    #      整体在动"。两者都要，评分才能区分「单一题材硬炒」与「行业＋题材双轮」。
    #      行业归属（f100）已由上面的 spot 覆盖带进 idx；这里只补板块指数读数。
    ind_blocks, ind_meta = {}, {}
    try:
        ind_blocks = industry_f.fetch(save=True)
        by_code = {c: e["industry"] for c, e in idx.items() if e.get("industry")}
        n_match = sum(1 for v in by_code.values() if v in ind_blocks)
        ind_meta = {"n_blocks": len(ind_blocks), "n_code": len(by_code),
                    "n_matched": n_match,
                    "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        print("  行业板块 %d 个 · 池内 %d/%d 只能对上行业指数"
              % (len(ind_blocks), n_match, len(idx)))
        # 09:15 前拿到的是昨日收盘，写成今天会污染"较昨日"的历史序列
        if time.strftime("%H:%M") >= "09:15":
            sector.save_hist(time.strftime("%Y-%m-%d"), ind_blocks)
    except Exception as e:  # noqa: BLE001
        errors["industry"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    # ---- 概念板块（东财 m:90+t:3，531 个）：与行业板块同一套字段、同一套算法。
    #      行业页与概念页要"格式一样"，底层就得是两份同构的板块读数。
    con_blocks, con_meta = {}, {}
    try:
        con_blocks = industry_f.fetch(save=True, kind="concept")
        print("  概念板块 %d 个" % len(con_blocks))
    except Exception as e:  # noqa: BLE001
        errors["concept_sector"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    # ---- 个股所属板块（F10 ssbk）：一只票挂 3 个行业（一/二/三级）+ 若干概念板块。
    #      这是"行业标签不唯一"的数据源；缺了会退回 f100 单行业，页面照常出。
    f10 = {}
    try:
        f10 = f10_f.fetch(list(idx.keys()))
        print("  F10 所属板块 %d 只（有行业链 %d 只）"
              % (len(f10), sum(1 for v in f10.values() if v.get("industries"))))
    except Exception as e:  # noqa: BLE001
        errors["f10"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    # 异动解析在 attr / lhb 之后抓（见下），因为要按「人气池 ∪ 全市场涨停 ∪
    # 今日龙虎榜 ∪ 热榜 100」的并集去抓，而不是只抓人气池。

    # 龙虎榜（个股上榜）：同花顺 ggph 给机构席位，东财给 30 天全量次数与净买。
    # 这是"资金是不是真站在里面"的独立证据，缺了不影响主榜，只在页面上少两列。
    lh = {}
    try:
        lh = lhb.fetch()
    except Exception as e:  # noqa: BLE001
        errors["lhb"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    # 概念成分只有名字没有代码，这里补上代码，题材页才能点进个股
    n2c = normalize.name_index(idx)
    stats = []
    for c in ((rq or {}).get("concept_stats") or []):
        d = dict(c)
        d["members"] = [[r[0], r[1], n2c.get(r[1], "")] for r in (c.get("members") or [])]
        stats.append(d)

    # ---- 归因池（涨停/炸板）：P3 /attr 的唯一数据源，独立成文件不进 bundle，
    #      因为它是全市场口径，和人气池 167 只是两个集合，混一起会把口径搅乱。
    at = {}
    try:
        at = attr_f.fetch()
        attr_f.save(at)
    except Exception as e:  # noqa: BLE001
        errors["attr"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    # ---- 异动解析（同花顺逐股异动的 reason + keywordList）：抓**并集**，不是只抓人气池。
    #      用户 2026-11-02："从所有涨停股里去读异动解析，每只涨停股、龙虎榜里的票、
    #      同花顺排行 100 里的票都去看一下"。实测 125 只涨停里只有 43 只在人气池内，
    #      只抓池子等于漏掉 2/3 的涨停股，消息面就数不出来。
    reasons = {}
    try:
        _hot_codes = {x.get("code") for x in (((hot or {}).get("lists") or {}).get("hour") or [])}
        _hot_codes |= {x.get("code") for x in (((hot or {}).get("lists") or {}).get("day") or [])}
        _zt_codes = {x.get("code") for x in ((at.get("today") or {}).get("zt") or [])}
        _lhb_all = (lh or {}).get("by_code") or {}
        _lhb_days = [str((v.get("last") or {}).get("date") or "") for v in _lhb_all.values()]
        _lhb_day = max([d for d in _lhb_days if d] or [""])
        _lhb_codes = {c for c, v in _lhb_all.items()
                      if str((v.get("last") or {}).get("date") or "") == _lhb_day}
        _union = ({c for c in idx} | (_zt_codes - {None}) | (_lhb_codes - {None})
                  | (_hot_codes - {None}))
        print("  异动解析并集 %d 只（人气池 %d · 涨停 %d · 龙虎榜 %d · 热榜 %d）"
              % (len(_union), len(idx), len(_zt_codes), len(_lhb_codes), len(_hot_codes)))
        reasons = abnormal.fetch_all(sorted(_union), workers=12)
        print("  异动解析命中 %d 只" % len(reasons))
    except Exception as e:  # noqa: BLE001
        errors["abnormal"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    # ---- 驱动词（P3 /drivers）：优先用当日快照的板块口径，缺了就退化成东财涨停池
    rd = {}
    try:
        snap = _snap_for_reasons(at.get("qdate") or "", idx) if at else None
        if not (snap and snap.get("ladder")):
            snap = _fake_snap(at or {}, stats)
        if snap.get("trade_date"):
            rd = reasons_core.attach(snap, os.path.join(store.DATA, "reasons"),
                                     sleep=0.15, verbose=False) or {}
    except Exception as e:  # noqa: BLE001
        errors["drivers"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    # ---- 简报（P3 /brief）：只有「事件日历」是不可替代的，指数与基调当补充
    br = {}
    try:
        br = brieffeed.fetch(4)
        brieffeed.save(br)
    except Exception as e:  # noqa: BLE001
        errors["brief"] = "%s: %s" % (type(e).__name__, e)
        traceback.print_exc()

    # ---- 行情日口径：有两层时点，别混
    #      人气榜（热度/评分/概念/排名）是收盘后源，盘中它的 quote_date 还是上一个交易日；
    #      行情（价/涨幅/额/换手）已经用实时源覆盖。所以：
    #        quote_date/updated_at = 行情与页面的"当前口径"
    #        renqi_date/renqi_at    = 人气榜源自己的时点（页面上如实标注，不冒充今天）
    _now = time.localtime()
    _today = time.strftime("%Y-%m-%d", _now)
    _hm = time.strftime("%H:%M", _now)
    _intraday = (_now.tm_wday < 5 and "09:15" <= _hm <= "15:05")
    # 09:15 前跑的早间档（如 09:00）拿到的是**昨日收盘价**，绝不能标成今天口径，
    # 否则页面写"行情 2026-11-02"却全是昨天的数。此时退回人气榜源自己的日期。
    _quote_day = _today if (sp and _hm >= "09:15") else ""

    bundle = {
        "quote_date": _quote_day or (rq or {}).get("quote_date"),
        "updated_at": (time.strftime("%Y-%m-%d %H:%M:%S") if _quote_day
                       else (rq or {}).get("updated_at")),
        "intraday": bool(_intraday if sp else (rq or {}).get("intraday")),
        "renqi_date": (rq or {}).get("quote_date"),
        "renqi_at": (rq or {}).get("updated_at"),
        "spot_n": len(sp),
        "stocks": idx,
        "concept_stats": stats,
        "concept_stats_heat": (rq or {}).get("concept_stats_heat") or [],
        "concept_traj": (rq or {}).get("concept_traj") or {},
        "lists": (rq or {}).get("lists") or {},
        # 综合分 TOP10 就是 leaderboard（10 条、score_final 严格递减）。
        # 别拿 lists.composite——那只有 5 条，是"涨停且高分"的子集，不是 TOP10。
        "leaderboard": (rq or {}).get("leaderboard") or [],
        "tdx_top": (tdx or {}).get("top") or [],
        "hot_hour": ((hot or {}).get("lists") or {}).get("hour") or [],
        "hot_day": ((hot or {}).get("lists") or {}).get("day") or [],
        "abnormal": reasons,
        "lhb": (lh or {}).get("by_code") or {},
        "lhb_meta": {k: v for k, v in (lh or {}).items() if k != "by_code"},
        # 行业维度：blocks 是全市场行业指数读数（分位按全市场算，不按池内），
        # by_code 是池内个股的行业归属。两者分开放，页面与评分各取所需。
        "industry": {
            "blocks": ind_blocks,
            "by_code": {c: e["industry"] for c, e in idx.items() if e.get("industry")},
            "meta": ind_meta,
        },
        # 概念板块：与 industry 同构（同字段、同算法），供 /concept 的概念板块榜
        "concept_sector": {"blocks": con_blocks, "meta": con_meta},
        # 个股所属板块（F10）：行业链 1~3 个 + 概念板块若干，行业标签不再唯一
        "f10": f10,
        # 全市场涨停池（东财）：人气池只有 ~141 只，而全市场涨停 ~125 只，
        # 两者交集只有 43 只。主线要按**全市场涨停**算热度，否则漏掉 2/3 的涨停股。
        "zt_pool": [{"code": x.get("code"), "name": x.get("name"),
                     "price": x.get("price"), "amount": x.get("amount"),
                     "pct": x.get("pct"), "board": x.get("board") or 1,
                     "days": x.get("days"), "industry": x.get("industry"),
                     "fund": x.get("fund"), "turnover": x.get("turnover")}
                    for x in ((at.get("today") or {}).get("zt") or [])],
        "degraded": ["%s（%s）" % (k, v) for k, v in errors.items()],
    }
    meta = {"errors": errors, "n_stocks": len(idx),
            "n_concept": len(stats),
            "n_tdx": len(bundle["tdx_top"]),
            "n_hot_hour": len(bundle["hot_hour"]),
            "n_reason": len(reasons),
            "n_lhb": len(bundle["lhb"]),
            "n_attr": len((at.get("today") or {}).get("zt") or []),
            "n_zb": len((at.get("today") or {}).get("zb") or []),
            "n_driver": len(rd.get("drivers") or []),
            "n_industry": len(ind_blocks),
            "n_concept_block": len(con_blocks),
            "n_f10": len(f10),
            "n_brief": len(br.get("reports") or [])}
    store.save_bundle(bundle, meta)
    return {"meta": meta, "bundle": bundle}


def main():
    partial = "--allow-partial" in sys.argv
    r = run(allow_partial=partial)
    m = r["meta"]
    b = r["bundle"]
    print("bundle 已写入 %s" % store.BUNDLE)
    print("  行情日 %s　主体 %s　盘中 %s"
          % (b["quote_date"], b["updated_at"], "是" if b["intraday"] else "否"))
    print("  个股 %d 只　概念 %d 个　tdx %d 只　热榜 %d 只　上榜原因 %d 条　龙虎榜 %d 只"
          % (m["n_stocks"], m["n_concept"], m["n_tdx"], m["n_hot_hour"], m["n_reason"],
             m["n_lhb"]))
    print("  涨停 %d 只　炸板 %d 只　驱动词 %d 个　简报 %d 篇"
          % (m["n_attr"], m["n_zb"], m["n_driver"], m["n_brief"]))
    if m["errors"]:
        print("  降级：")
        for k, v in m["errors"].items():
            print("    - %s: %s" % (k, v))


if __name__ == "__main__":
    main()
