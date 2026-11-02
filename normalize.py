# -*- coding: utf-8 -*-
"""三源归一：把人气榜 / tdx / 同花顺热榜按 6 位代码合并成一份个股索引。

合并原则
--------
1. **代码是唯一主键**。各源的代码格式不同（`002172.SZ` / `002172` / `2172`），
   统一先过 `base.code6()`，否则同一只票会出现三条记录。
2. **字段冲突时人气榜优先**。它是自算综合分的主源，price/score/concept_all 都是
   它的口径；tdx 与热榜只补它没有的（涨停原因、排名历史、实时热度标签）。
3. **不做"猜"**。某源缺字段就留 None，页面显示"—"。宁可少一行，也不拿别处
   的近似值冒充——那会让"这个数字哪来的"变得无法回溯。
"""
from __future__ import annotations

from fetchers import base, hotlist_ths, renqi, tdx_rank


def split_concepts(concept_all: str) -> list:
    """'脑机接口+医疗服务+国资控股+“羊”字辈' → ['脑机接口','医疗服务','国资控股','羊字辈']

    去引号是为了和 `concept_stats` 里的键对齐（那边叫"羊字辈"，不带全角引号），
    否则题材页会出现两个只差引号的同名概念。
    """
    out = []
    for part in str(concept_all or "").split("+"):
        s = part.strip().strip("“”\"'· ").strip()
        if s and s not in out:
            out.append(s)
    return out


def build(renqi_d=None, tdx_p=None, hot_d=None) -> dict:
    idx = {}

    def slot(c):
        return idx.setdefault(c, {"code": c, "sources": []})

    # ---- 1. 人气榜铺底（字段最全）
    if renqi_d:
        for c, s in renqi.stock_map(renqi_d).items():
            e = slot(c)
            e.update(s)
            e["name"] = s.get("name") or e.get("name") or ""
            e["pct"] = s.get("chg") if s.get("chg") is not None else e.get("pct")
            e["score"] = s.get("score_final")
            e["concepts"] = split_concepts(s.get("concept_all"))
            e["sources"].append("renqi")

    # ---- 2. tdx 补涨停原因与排名历史
    if tdx_p:
        for c, t in tdx_rank.stock_map(tdx_p).items():
            e = slot(c)
            e["tdx"] = t
            e["sources"].append("tdx")
            if not e.get("name"):
                e["name"] = t.get("name") or ""
            if e.get("price") is None:
                e["price"] = t.get("price")
            if e.get("pct") is None:
                e["pct"] = t.get("change_pct")
            # 涨停原因：人气榜的 reason 字段实测为 None，tdx 的 limit_up_reason 才是真货
            if t.get("limit_up_reason") and not e.get("limit_up_reason"):
                e["limit_up_reason"] = t["limit_up_reason"]

    # ---- 3. 同花顺热榜补实时名次/人气标签
    if hot_d:
        for c, h in hotlist_ths.stock_map(hot_d).items():
            e = slot(c)
            e["hot"] = h
            e["sources"].append("hot")
            if not e.get("name"):
                e["name"] = h.get("name") or ""

    return idx


def name_index(idx: dict) -> dict:
    """中文名 → 代码。题材页的 members 只给名字不给代码，靠这个反查。"""
    out = {}
    for c, e in idx.items():
        n = (e.get("name") or "").strip()
        if n and n not in out:
            out[n] = c
    return out


def search(idx: dict, q: str, limit: int = 20) -> list:
    """双向搜：代码（前缀/包含）与中文名（包含）都能命中。

    排序：代码完全相等 > 名字完全相等 > 代码前缀 > 名字前缀 > 其余。
    """
    q = (q or "").strip()
    if not q:
        return []
    ql = q.lower()
    hits = []
    for c, e in idx.items():
        n = (e.get("name") or "").lower()
        if ql == c or ql == n:
            rank = 0
        elif c.startswith(ql):
            rank = 2
        elif n.startswith(ql):
            rank = 3
        elif ql in c or ql in n:
            rank = 4
        else:
            continue
        hits.append((rank, c, e))
    hits.sort(key=lambda x: (x[0], -(e_score(x[2])), x[1]))
    return [h[2] for h in hits[:limit]]


def e_score(e):
    try:
        return float(e.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def line(e: dict) -> str:
    """拼出"一行看全"的摘要——就是最初需求里那条
    「澳洋健康 ¥5.91 95.2 216.4万·日 第7名 +110.1% 脑机接口+医疗服务+国资控股+"羊"字辈 龙头 利多强」。
    只做纯文本，具体着色由页面各自决定。
    """
    bits = []
    if e.get("price") is not None:
        bits.append("¥%.2f" % float(e["price"]))
    if e.get("score") is not None:
        bits.append(_t(e["score"]))
    if e.get("ths_heat"):
        bits.append("%.1f万·%s" % (float(e["ths_heat"]) / 1e4,
                                  "日" if (e.get("ths_heat_src") or "day") == "day" else "时"))
    if e.get("heat_rank"):
        bits.append("第%d名" % e["heat_rank"])
    if e.get("heat_growth") is not None:
        bits.append("%+.1f%%" % float(e["heat_growth"]))
    if e.get("concept_all"):
        bits.append(e["concept_all"])
    if e.get("is_leader"):
        bits.append("龙头")
    if e.get("benefit_lv"):
        bits.append("利多" + str(e["benefit_lv"]))
    return "　".join(bits)


def _t(v):
    s = ("%.1f" % float(v))
    return s[:-2] if s.endswith(".0") else s
