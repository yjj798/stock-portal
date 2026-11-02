# -*- coding: utf-8 -*-
"""同花顺热榜抓取（dq.10jqka.com.cn/fuyao/hot_list_data）。

这是三张榜里唯一"真·实时"的一张：盘中也跳，跟人气榜（自算综合分）和 tdx
（排名历史）互为印证。

已失效字段备忘（别再往回找）
--------------------------
`analyse_title`（异动原因一句话）在 2026-11 的实测里 **0/100 全部为空**，
旧卡与 tdx 里那套口径已作废。现在能拿到的只有：
    tag.concept_tag     概念标签数组
    tag.popularity_tag  人气标签（"2天2板"/"首板涨停"）
真正的"异动原因"走逐股接口（见 reasons_core），那边覆盖率 96%，别在这里绕。
"""
from __future__ import annotations

from . import base

NAME = "ths_hot"

BASE = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"

# hour=盘中小时榜（默认看这个，跳动最敏感）；day=日榜（收盘后更稳）
KINDS = ("hour", "day")


def _url(kind: str) -> str:
    return "%s?stock_type=a&type=%s&list_type=normal" % (BASE, kind)


def fetch(save: bool = True) -> dict:
    """两张表都抓，任一张失败不牵连另一张（返回里带 errors）。"""
    out, notes, errors = {}, {}, {}
    for kind in KINDS:
        try:
            obj, note = base.get_json(_url(kind), timeout=12, tries_proxy=(False, True))
            lst = ((obj or {}).get("data") or {}).get("stock_list") or []
            out[kind] = [_slim(x) for x in lst]
            notes[kind] = "%s %d 只" % (note, len(lst))
        except Exception as e:  # noqa: BLE001
            out[kind] = []
            errors[kind] = "%s: %s" % (type(e).__name__, e)
    payload = {"lists": out, "errors": errors}
    if save and (out.get("hour") or out.get("day")):
        base.save(NAME, payload, {"notes": notes, "errors": errors})
    if not any(out.values()):
        raise base.FetchError("同花顺热榜两张表都空：" + str(errors))
    return payload


def _slim(x: dict) -> dict:
    tag = x.get("tag") or {}
    return {
        "code": base.code6(x.get("code")),
        "name": x.get("name") or "",
        "order": x.get("order"),
        "rate": _f(x.get("rate")),
        "pct": _f(x.get("rise_and_fall")),
        "rank_chg": x.get("hot_rank_chg"),
        "popularity_tag": tag.get("popularity_tag") or "",
        "concept_tag": tag.get("concept_tag") or [],
        "market": x.get("market"),
    }


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load():
    return base.load(NAME)


def stock_map(payload: dict) -> dict:
    """按代码索引，`hot_hour`/`hot_day` 分别记名次，供个股页同时看两个口径。"""
    out = {}
    lists = (payload or {}).get("lists") or {}
    for kind in KINDS:
        for x in lists.get(kind) or []:
            c = x.get("code")
            if not c:
                continue
            d = out.setdefault(c, {"code": c, "name": x.get("name") or ""})
            d["hot_" + kind] = x.get("order")
            d["hot_%s_rate" % kind] = x.get("rate")
            d["hot_%s_pct" % kind] = x.get("pct")
            if x.get("concept_tag"):
                d["concept_tag"] = x["concept_tag"]
            if x.get("popularity_tag"):
                d["popularity_tag"] = x["popularity_tag"]
    return out
