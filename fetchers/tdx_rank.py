# -*- coding: utf-8 -*-
"""tdx 榜单抓取（yjj79819/tdx）：top50 + 每股 32 天排名序列。

为什么排名历史要单独抓
----------------------
榜单页的"趋势箭头"不是算当日涨幅，而是"排名比 5 天前上升/下降几位"。这个信息
只存在于 docs/data/history/<code>.json 里，每只票一个文件。43 只票 = 43 个请求，
所以刷新时并发拉、只拉当天榜单里的票，不做全市场预热。

数据质量提醒：top50.json 里 `turnover_rate` 常年是 0（上游字段没填），
所以页面不能拿它当"换手率"显示，得用 renqi 的 turnover，或干脆不显示。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import base

NAME = "tdx"
RAW = "https://raw.githubusercontent.com/yjj79819/tdx/main/docs/data"
CDN = "https://cdn.jsdelivr.net/gh/yjj79819/tdx@main/docs/data"
PROXY = "https://gh-proxy.com/https://raw.githubusercontent.com/yjj79819/tdx/main/docs/data"

# 这个坑必须写在代码里：jsDelivr 对 @main 分支最长缓存 12 小时，实测它给的是
# **35 条**的旧版本，而仓库真实文件是 **43 条**。榜单少 8 只票肉眼很难发现，
# 所以新鲜度必须优先于速度——gh-proxy 0.5s 拿到的是最新提交。
CHANNELS = [
    ("gh-proxy", PROXY + "/top50.json", (False, True)),
    ("jsdelivr", CDN + "/top50.json", (False, True)),
    ("gh-raw", RAW + "/top50.json", (True, False)),
]

HIST_CHANNELS = [
    (PROXY + "/history/%s.json", (False, True)),
    (CDN + "/history/%s.json", (False, True)),
    (RAW + "/history/%s.json", (True, False)),
]


def fetch_top(save: bool = False):
    obj, note = base.pick_json(CHANNELS, timeout=15)
    if not isinstance(obj, list):
        raise base.FetchError("tdx top50 结构异常：期望 list，拿到 %s" % type(obj).__name__)
    return obj, note


def fetch_hist(code6: str):
    """单股排名历史。拿不到就返回空列表——趋势箭头显示"—"，不影响主表。"""
    for tpl, tp in HIST_CHANNELS:
        try:
            obj, _ = base.get_json(tpl % code6, timeout=8, tries_proxy=tp)
        except Exception:
            continue
        rows = (obj or {}).get("history") or []
        # 只留 date/rank，去掉多余字段减小体积
        return [{"date": r.get("date"), "rank": r.get("rank")}
                for r in rows if r.get("date") and r.get("rank") is not None]
    return []


def fetch(save: bool = True, with_history: bool = True, workers: int = 8) -> dict:
    top, note = fetch_top()
    hist = {}
    if with_history:
        codes = [base.code6(x.get("code")) for x in top]
        codes = [c for c in codes if c]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for c, rows in zip(codes, ex.map(fetch_hist, codes)):
                if rows:
                    hist[c] = rows
    payload = {"top": top, "history": hist}
    if save:
        base.save(NAME, payload, {"channel": note, "n_top": len(top),
                                  "n_hist": len(hist)})
    return payload


def load():
    return base.load(NAME)


def stock_map(payload: dict) -> dict:
    """tdx 侧按代码建索引，附加 `_trend`（近 5 日排名变化，负数=名次前进）。"""
    out = {}
    hist = (payload or {}).get("history") or {}
    for x in (payload or {}).get("top") or []:
        c = base.code6(x.get("code"))
        if not c:
            continue
        d = dict(x)
        d["code"] = c
        rows = hist.get(c) or []
        d["hist"] = rows
        d["hist_days"] = len(rows)
        d["trend5"] = _trend(rows, 5)
        d["rank_prev"] = rows[-2]["rank"] if len(rows) > 1 else None
        out[c] = d
    return out


def _trend(rows, n):
    """排名变化：正数=名次后退（变差），负数=前进（变好）。与页面箭头方向一致。"""
    if len(rows) < 2:
        return None
    cur = rows[-1]["rank"]
    base_row = rows[max(0, len(rows) - 1 - n)]
    return cur - base_row["rank"]
