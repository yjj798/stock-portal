# -*- coding: utf-8 -*-
"""龙虎榜（个股上榜）抓取 —— 两个源各取所长，字段不混用。

为什么是两个源
--------------
用户指定要 `data.10jqka.com.cn/market/ggph/` 的「近30天上榜次数 + 机构席位」。
那个页面确实是最权威的上榜统计（含**参与机构位数**与**机构专用买入/卖出**，
这两列只有同花顺给），但它有两个硬限制：

1. **只有第 1 页能抓**。翻页走 `.../ajax/1/` 分支，服务端要求 chameleon 反爬
   算出的 `hexin-v` cookie，缺了直接 401（实测）。
2. 第 1 页只有 50 行，按上榜次数降序——池里 167 只票只覆盖得到最活跃的那几只。

所以：
    同花顺 ggph（第 1 页 50 行）  → 机构席位、机构专用买卖、总买卖额
    东方财富 龙虎榜明细（近 30 天全量）→ 上榜次数、净买额、最近上榜日/原因、上榜后 1/5 日表现

**同一条指标只允许一个源**，不拿东财的次数去补同花顺的次数。两边口径其实一致
（都是"上榜记录条数"，一天两个上榜原因算两次），可对拍：实测 50 只里 46 只完全相等，
差的是 4 只 —— 差异来自"近 30 天"窗口的日期边界（同花顺按自然日滑动，东财按我给的
起始日截断），不是口径不同。这条结论写在 verify_lhb.py 里，每次刷新都会重算。

用法：
    python -m fetchers.lhb            # 单独跑，看抓到了什么
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import urllib.parse

from . import base

THS_URL = "https://data.10jqka.com.cn/market/ggph/"
EM_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_REPORT = "RPT_DAILYBILLBOARD_DETAILSNEW"
WINDOW_DAYS = 30


# ---------------------------------------------------------------- 同花顺
def _cells(row: str):
    """把一行 <tr> 拆成去标签的单元格文本。"""
    tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
    return [re.sub(r"<[^>]+>", "", t).replace("&nbsp;", " ").strip() for t in tds]


def _f(s, d=0.0):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return d


def parse_ths(raw: bytes) -> dict:
    """解析 ggph 首页表格 → {code: {...}}。

    表头：序号 | 代码 | 简称 | 近30天上榜次数 | 买入(万) | 卖出(万)
           | 参与机构位数 | 机构专用买入(万) | 机构专用卖出(万) | 明细
    页面是 GBK，行内还夹着大量导航 <tr>，靠 `lhbcjmx/code/` 链接筛出数据行。
    """
    text = raw.decode("gbk", "ignore")
    out = {}
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S):
        if "lhbcjmx/code/" not in r:
            continue
        c = _cells(r)
        if len(c) < 9 or not re.fullmatch(r"\d{6}", c[1]):
            continue
        code = c[1]
        out[code] = {
            "code": code, "name": c[2],
            "sb": int(_f(c[3])),                        # 近 30 天上榜次数
            "buy_amt": _f(c[4]) * 1e4,                  # 万元 → 元
            "sell_amt": _f(c[5]) * 1e4,
            "jg_seats": int(_f(c[6])),                  # 参与机构位数
            "jg_buy": _f(c[7]) * 1e4,                   # 机构专用买入
            "jg_sell": _f(c[8]) * 1e4,
        }
    return out


def fetch_ths() -> dict:
    raw, note = base.get(THS_URL, timeout=20)
    rows = parse_ths(raw)
    if not rows:
        raise base.FetchError("ggph 页面解析出 0 行，页面结构可能变了")
    return {"rows": rows, "note": note}


# ---------------------------------------------------------------- 东方财富
def fetch_em(since: dt.date, max_pages: int = 6) -> list:
    """近 30 天全部上榜记录（全市场）。东财这个报表一行 = 一个「上榜原因」。"""
    out = []
    for page in range(1, max_pages + 1):
        q = {
            "reportName": EM_REPORT, "columns": "ALL",
            "filter": "(TRADE_DATE>='%s')" % since.isoformat(),
            "pageNumber": page, "pageSize": 500,
            "sortColumns": "TRADE_DATE", "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        }
        url = EM_URL + "?" + urllib.parse.urlencode(q)
        obj, _note = base.get_json(url, timeout=20)
        res = obj.get("result") or {}
        data = res.get("data") or []
        out += data
        if len(data) < 500:
            break
    if not out:
        raise base.FetchError("东财龙虎榜返回 0 行")
    return out


def agg_em(rows: list, since: dt.date) -> dict:
    """按代码聚合：上榜次数、上榜天数、净买、最近一次上榜、上榜后表现。"""
    a = collections.defaultdict(lambda: {
        "n30": 0, "dates": [], "net": 0.0, "buy": 0.0, "sell": 0.0,
        "d1": [], "d5": [], "last": None, "reasons": collections.Counter(),
    })
    for x in rows:
        code = x.get("SECURITY_CODE") or ""
        if not code:
            continue
        d = str(x.get("TRADE_DATE") or "")[:10]
        g = a[code]
        g["n30"] += 1
        if d not in g["dates"]:
            g["dates"].append(d)
        net = x.get("BILLBOARD_NET_AMT") or 0
        g["net"] += net
        g["buy"] += x.get("BILLBOARD_BUY_AMT") or 0
        g["sell"] += x.get("BILLBOARD_SELL_AMT") or 0
        if x.get("D1_CLOSE_ADJCHRATE") is not None:
            g["d1"].append(x["D1_CLOSE_ADJCHRATE"])
        if x.get("D5_CLOSE_ADJCHRATE") is not None:
            g["d5"].append(x["D5_CLOSE_ADJCHRATE"])
        ex = x.get("EXPLANATION") or ""
        if ex:
            g["reasons"][ex] += 1
        if g["last"] is None or d > g["last"]["date"]:
            g["last"] = {"date": d, "reason": ex, "net": net,
                         "pct": x.get("CHANGE_RATE"),
                         "explain": x.get("EXPLAIN") or ""}

    out = {}
    for code, g in a.items():
        out[code] = {
            "n30": g["n30"],
            "days": len(g["dates"]),
            "dates": sorted(g["dates"], reverse=True)[:8],
            "net": round(g["net"], 2),
            "buy": round(g["buy"], 2),
            "sell": round(g["sell"], 2),
            "d1": round(sum(g["d1"]) / len(g["d1"]), 2) if g["d1"] else None,
            "d5": round(sum(g["d5"]) / len(g["d5"]), 2) if g["d5"] else None,
            "last": g["last"],
            "reason_top": (g["reasons"].most_common(1)[0][0] if g["reasons"] else ""),
        }
    return out


# ---------------------------------------------------------------- 合并
def fetch(window_days: int = WINDOW_DAYS) -> dict:
    """返回 {'by_code': {...}, 'since': ..., 'n_ths': .., 'n_em': .., 'recon': {...}}。"""
    since = dt.date.today() - dt.timedelta(days=window_days)
    out = {"since": since.isoformat(), "by_code": {}}

    ths = {}
    try:
        r = fetch_ths()
        ths = r["rows"]
        out["n_ths"] = len(ths)
        out["ths_note"] = r["note"]
    except Exception as e:  # noqa: BLE001
        out["ths_error"] = "%s: %s" % (type(e).__name__, e)

    em = {}
    try:
        rows = fetch_em(since)
        em = agg_em(rows, since)
        out["n_em"] = len(em)
        out["n_em_rows"] = len(rows)
    except Exception as e:  # noqa: BLE001
        out["em_error"] = "%s: %s" % (type(e).__name__, e)

    codes = set(ths) | set(em)
    for c in codes:
        t, e = ths.get(c) or {}, em.get(c) or {}
        rec = {
            "code": c,
            "name": t.get("name") or "",
            # 次数：同花顺优先（用户指定源），没有才用东财
            "n30": t["sb"] if t else e.get("n30", 0),
            "n30_src": "ths" if t else ("em" if e else ""),
            "days": e.get("days"),
            "dates": e.get("dates") or [],
            "net": e.get("net"),
            "buy": e.get("buy"),
            "sell": e.get("sell"),
            "d1": e.get("d1"),
            "d5": e.get("d5"),
            "last": e.get("last"),
            "reason_top": e.get("reason_top") or "",
            # 机构（只有同花顺前 50 有）
            "jg_seats": t.get("jg_seats"),
            "jg_buy": t.get("jg_buy"),
            "jg_sell": t.get("jg_sell"),
            "jg_net": (round(t["jg_buy"] - t["jg_sell"], 2) if t else None),
        }
        out["by_code"][c] = rec

    # 对拍：同花顺次数 vs 东财次数，供验收与页面口径说明用
    both = [c for c in ths if c in em]
    same = [c for c in both if ths[c]["sb"] == em[c]["n30"]]
    out["recon"] = {"n_both": len(both), "n_same": len(same)}
    return out


def main():
    r = fetch()
    print("窗口起点 %s" % r["since"])
    print("同花顺 %s 只（%s）" % (r.get("n_ths"), r.get("ths_error") or r.get("ths_note")))
    print("东财   %s 只 / %s 行（%s）" % (r.get("n_em"), r.get("n_em_rows"),
                                     r.get("em_error") or "ok"))
    print("对拍   %s" % r["recon"])
    top = sorted(r["by_code"].values(), key=lambda x: -x["n30"])[:8]
    for x in top:
        print("  %s %s 上榜%d次 净买%s 机构%s位"
              % (x["code"], x["name"], x["n30"],
                 "—" if x["net"] is None else "%.2f亿" % (x["net"] / 1e8),
                 x["jg_seats"]))


if __name__ == "__main__":
    main()
