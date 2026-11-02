# -*- coding: utf-8 -*-
"""采集每日快照 → data/snapshots/<YYYY-MM-DD>.json（首页情绪/梯队/板块层）。

数据源 55188 sec.php（免登录）：
    overview   → breadth / sentiment(封板率·最高板) / ladder(涨停时间线+plates)
                 / hot_sectors / main_force / sector_flow(themes)
    qxzb       → 情绪校验值（qx 封板率、冲刺率、晋级数、最高连板股）
    fry_themes → themes（下一交易日题材前瞻）
    lhb_board  → lhb（龙虎榜汇总 + 前 15）
    blocks     → blocks（申万板块涨幅/主力/强度）

任一端点失败：该块空缺 + degraded 留痕，页面显示「暂无」，不让整快照失败。
overview 是核心（breadth/ladder 全在里面），它失败时仍用 qxzb 兜底出最小快照。

用法：python snapshot_job.py [YYYY-MM-DD]   （无参=最新交易日）
"""
from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.request
from datetime import datetime, timezone, timedelta

import store

_BASE = "https://www.55188.com/sec.php"
_HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
         "Referer": "https://www.55188.com/sec.php",
         "Accept": "application/json, text/plain, */*"}
_TIMEOUT = 20
_BJ = timezone(timedelta(hours=8))


def _is_archived(day: str) -> bool:
    """源口径是"已归档的历史交易日"吗——是则本次不写盘，避免把旧日覆盖成空。

    为什么需要：09:00 早间档开盘前抓，源的 trade_date 还是上一交易日；若照写，
    上一交易日的快照会被"非盘中"版本覆盖（涨停池、梯队常为空），越跑越差。
    """
    if not day:
        return False
    if day == datetime.now(_BJ).strftime("%Y-%m-%d"):
        return False
    return day in store.snapshot_dates()


def _get(action: str) -> dict | None:
    for i in range(3):
        try:
            req = urllib.request.Request("%s?action=%s" % (_BASE, action), headers=_HDRS)
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8", "ignore"))
        except Exception as e:  # noqa: BLE001
            print("[snapshot] %s 第%d次失败：%s %s" % (action, i + 1, type(e).__name__, e))
            import time
            time.sleep(2 * (i + 1))
    return None


def run(target: str | None = None) -> dict | None:
    degraded: list[str] = []
    src: dict = {}
    ov = _get("overview")
    if ov and ov.get("status") not in ("ok", None):
        degraded.append("overview:%s" % ov.get("status"))
        ov = None
    if ov is None:
        degraded.append("overview 拉取失败")
    qx = _get("qxzb")
    if qx is None or qx.get("status") != "ok":
        degraded.append("qxzb 拉取失败")
        qx = None
    if ov is None and qx is None:
        print("[snapshot] 核心源全挂，不出快照")
        return None

    ovd = (ov or {}).get("overview") or {}
    mtc = (ov or {}).get("metrics") or {}
    lim = ((qx or {}).get("payload") or {}).get("limit") or {}
    brd = ((qx or {}).get("payload") or {}).get("breadth") or {}
    qdate = (ov or {}).get("trade_date") or ((qx or {}).get("payload") or {}).get("trade_date") \
        or (target or "")
    if target and qdate and qdate[:10] != target[:10]:
        print("[snapshot] 源返回 %s 与请求 %s 不符，以源为准" % (qdate, target))

    # ---- breadth（overview 为主，qxzb 补位）
    def g(d, k, default=None):
        v = d.get(k)
        if isinstance(v, dict) and "value" in v:      # 源有时包一层 {value,status,reason}
            v = v.get("value")
        return v if v is not None else default

    breadth = {
        "up": g(ovd, "up_count", g(brd, "up")),
        "down": g(ovd, "down_count", g(brd, "down")),
        "flat": g(ovd, "flat_count", g(brd, "flat")),
        "limit_up": g(ovd, "limit_up_count", g(brd, "limit_up")),
        "limit_down": g(ovd, "limit_down_count", g(brd, "limit_down")),
        "broken": g(ovd, "broken_count"),
        "limit_down_open": g(mtc, "limit_down_open_count"),
        "suspended": g(ovd, "suspended_count"),
        "amount": g(ovd, "amount", g(brd, "amount")),
        "prev_amount": g(ovd, "previous_amount"),
        "amount_change": g(ovd, "amount_change"),
        "coverage": g(ovd, "coverage_rate", 1.0),
    }
    breadth = {k: v for k, v in breadth.items() if v is not None}

    # ---- sentiment
    sentiment = {
        "seal_rate": g(mtc, "seal_rate"),
        "prev_seal_rate": g(mtc, "previous_seal_rate"),
        "max_board": g(ovd, "max_board", g(mtc, "max_board")),
        "sprint_rate": g(lim, "sprint_rate"),
        "continue_count": g(lim, "continue_count"),
        "prev_limit_up": g(lim, "prev_limit_up"),
        "once_limit_up": g(lim, "once_limit_up"),
        "broken_count": g(lim, "broken_count", g(ovd, "broken_count")),
        "top_board_stock": g(lim, "top_board_stock"),
        "top_board_count": g(lim, "top_board_count"),
        "main_net": g(brd, "main_net"),
        "qx_seal_rate": g(lim, "seal_rate"),
    }
    sentiment = {k: v for k, v in sentiment.items() if v is not None}

    # ---- ladder（overview 明细带涨停时间与 plates）
    ladder = []
    for it in (ov or {}).get("limit_ladder") or []:
        stocks = []
        for s in it.get("stocks") or []:
            stocks.append({"code": s.get("code") or (s.get("symbol") or "")[-6:],
                           "name": s.get("name") or "",
                           "first": s.get("first_limit_up"),
                           "last": s.get("last_limit_up"),
                           "plates": [{"name": p.get("name"), "reason": p.get("reason")}
                                      for p in s.get("plates") or [] if p.get("name")]})
        ladder.append({"board": int(it.get("board") or 0),
                       "count": int(it.get("count") or len(stocks)),
                       "stocks": stocks})

    hot_sectors = [{"name": h.get("name"), "limit_up_count": h.get("limit_up_count"),
                    "max_board": h.get("max_board"),
                    "stock_count": len(h.get("stocks") or [])}
                   for h in (ov or {}).get("hot_sectors") or []]

    mf_rows = ((ov or {}).get("main_force") or {}).get("all") or []
    main_force = [{"code": r.get("code"), "name": r.get("name"), "rank": r.get("rank"),
                   "price": r.get("price"), "pct": r.get("change_pct"),
                   "mf_pct": r.get("main_force_pct"), "sector": r.get("sector")}
                  for r in mf_rows[:60]]

    sector_flow = [{"name": t.get("name"), "pct": t.get("change_pct"),
                    "net": t.get("main_force_net_inflow"), "up": t.get("up_count"),
                    "down": t.get("down_count"), "leader": t.get("leader_name"),
                    "leader_pct": t.get("leader_change_pct")}
                   for t in (ov or {}).get("themes") or []]

    # ---- fry_themes（题材前瞻）
    themes: dict = {}
    fr = _get("fry_themes")
    if fr and fr.get("status") == "ok":
        p = fr.get("payload") or {}
        days = p.get("days") or []
        if days:
            themes = {"date": days[0].get("date"), "items": days[0].get("items") or []}
        src["fry"] = fr.get("checked_at")
    else:
        degraded.append("fry_themes 拉取失败")

    # ---- lhb
    lhb: dict = {}
    lb = _get("lhb_board")
    if lb and lb.get("status") == "ok":
        p = lb.get("payload") or {}
        st = p.get("stats") or {}
        lhb = {"date": p.get("date"), "count": st.get("count"),
               "org_count": st.get("org_count"), "seat_count": st.get("seat_count"),
               "up": st.get("up"), "down": st.get("down"),
               "net_total": st.get("net_total"),
               "stocks": (p.get("stocks") or [])[:15]}
        src["lhb"] = lb.get("checked_at")
    else:
        degraded.append("lhb_board 拉取失败")

    # ---- blocks
    blocks: list = []
    bl = _get("blocks")
    if bl and bl.get("status") == "ok":
        blocks = (bl.get("rows") or [])[:15]
        src["blocks"] = bl.get("at")
    else:
        degraded.append("blocks 拉取失败")

    if ov is not None:
        src["overview"] = (ov or {}).get("as_of")
        src["snapshot_id"] = (ov or {}).get("snapshot_id")
    if qx is not None:
        src["qxzb"] = qx.get("checked_at")

    # 开盘前（09:00 档）与休市时段重抓，源的 trade_date 还是上一个交易日：此时写盘
    # 会把**已归档的历史日**用"非盘中快照"覆盖（涨停池/梯队可能为空），越跑越差。
    # 判据：源口径 != 今天，且该日已有快照 ⇒ 只读不写。
    _day = (qdate or "")[:10]
    if _is_archived(_day):
        print("[snapshot] 源口径 %s 为历史交易日且已有快照，跳过写入（保住已归档数据）"
              % _day)
        return store.load_snapshot(_day)[1]

    snap = {"trade_date": qdate,
            "as_of": src.get("overview") or src.get("qxzb") or "",
            "collected_at": datetime.now(_BJ).isoformat(),
            "breadth": breadth, "sentiment": sentiment, "ladder": ladder,
            "hot_sectors": hot_sectors, "main_force": main_force,
            "sector_flow": sector_flow, "themes": themes, "lhb": lhb,
            "blocks": blocks, "sources": src, "degraded": degraded}
    # 与旧快照同构的最小兜底：overview 挂时 breadth/sentiment 用 qxzb 补出的值也在上面
    path = store.save_snapshot(snap)
    print("[snapshot] %s 已写 %s（degraded=%d）"
          % (snap["trade_date"], path, len(degraded)))
    for d in degraded:
        print("[snapshot]   -", d)
    return snap


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        snap = run(target)
        sys.exit(0 if snap else 1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
