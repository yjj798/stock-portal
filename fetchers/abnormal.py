# -*- coding: utf-8 -*-
"""同花顺「上榜原因」抓取 —— 个股详情页那块 `atom-clamp` 文本的真身。

为什么不用抓网页
----------------
`https://ms.10jqka.com.cn/thsHotDetail/?name=..&code=..&marketCode=..` 是个 Vue SPA，
HTML 只有 4.8KB 壳子，正文全靠 JS 渲染。反查 `app.5d75221c.js` 拿到它真正调的接口：

    abnormalUrl = //dq.10jqka.com.cn/fuyao/transaction_history/service/v1/get
    拼接规则    = abnormalUrl + "/" + market + "_" + code + ".txt"

即 `.../get/33_002172.txt`。返回 `data.anomalyAnalysisList[0].reason` 就是页面上
那段「行业原因：… 公司原因：…」原文，逐字一致（含换行）。同一个响应还带
`keywordList`（就是 concept_all 的来源）与 `tagName`（涨停/首板等）。

市场码（实测，不是猜的）：
    6xxxxx → 17   沪市
    0/3xxxxx → 33 深市
    4/8/9xxxxx → 151 北交所
用错市场的表现是返回 76 字节的空对象，`anomalyAnalysisList` 为 []。

局限（必须知道）
----------------
这个接口只保留**最近一次**异动，没有历史列表，所以补不了往日的上榜原因。
当日没进异动的票返回空，属于正常——那就是"今天没有上榜原因"。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import base

NAME = "abnormal"
URL = "https://dq.10jqka.com.cn/fuyao/transaction_history/service/v1/get/%s_%s.txt"


def market_of(code6: str) -> str:
    c = (code6 or "").strip()
    if c.startswith("6"):
        return "17"
    if c[:1] in ("0", "3"):
        return "33"
    if c[:1] in ("4", "8", "9"):
        return "151"
    return "33"


def fetch_one(code6: str):
    """取单只票最近一次异动。没有就返回 None（不是错误）。"""
    url = URL % (market_of(code6), code6)
    try:
        obj, _ = base.get_json(url, timeout=10, tries_proxy=(False, True))
    except Exception:
        return None
    lst = ((obj or {}).get("data") or {}).get("anomalyAnalysisList") or []
    if not lst:
        return None
    # 接口目前只回一条；万一以后回多条，取日期最新的那条
    row = sorted(lst, key=lambda r: str(r.get("date") or ""))[-1]
    return {
        "date": row.get("date"),
        "reason": (row.get("reason") or "").strip(),
        "keywords": row.get("keywordList") or [],
        "tag_name": row.get("tagName") or "",
        "tag_code": row.get("tagCode") or "",
        "stock_name": row.get("stockName") or "",
    }


def fetch_all(codes, workers: int = 10) -> dict:
    """并发抓一批。返回 {code: item}；抓不到的不出现在结果里。"""
    codes = [c for c in dict.fromkeys(codes) if c]
    out = {}
    if not codes:
        return out
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for c, item in zip(codes, ex.map(fetch_one, codes)):
            if item and item.get("reason"):
                out[c] = item
    return out


def load():
    return base.load(NAME)


# ---------------------------------------------------------------- 文本处理
_DISC = "（免责声明"


def split_reason(text: str):
    """把整段拆成 (行业原因, 公司原因, 免责声明)。

    原文形如：
        行业原因：
        1、…
        公司原因：
        1、…
        （免责声明：本内容由AI技术搜集公开信息总结生成…）
    拆开是为了页面上能把"行业"和"公司"分两块显示——这两类原因的性质完全不同，
    混在一段里读起来很累。拆不出来就整段当正文，不丢字。
    """
    t = (text or "").strip()
    disc = ""
    i = t.find(_DISC)
    if i >= 0:
        disc = t[i:].strip()
        t = t[:i].strip()
    ind = comp = ""
    j = t.find("公司原因")
    if j >= 0:
        ind = t[:j].strip()
        comp = t[j:].strip()
    else:
        ind = t
    for pre in ("行业原因：", "行业原因:"):
        if ind.startswith(pre):
            ind = ind[len(pre):].strip()
    for pre in ("公司原因：", "公司原因:"):
        if comp.startswith(pre):
            comp = comp[len(pre):].strip()
    return ind, comp, disc
