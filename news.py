# -*- coding: utf-8 -*-
"""消息面（news）—— 从「每只涨停股的异动解析」里把同一条消息数出来。

为什么要单独一层
----------------
用户 2026-11-02 原话：「你应该从所有涨停股里去读它相关的这个异动解析……
每只涨停股、龙虎榜里出现的股票、同花顺排行 100 里出现的股票都去看一下它这种链接里的消息。」

这件事的价值不在"多抓一份文本"，而在**同一句话被几只票共享**：
同花顺的异动解析给每只票 4 个 `keywordList` 和一段「行业原因」原文，
把 270 多只票的这两样东西摆在一起数，就能看出今天到底在炒哪一条消息，
而不是靠我手写一份关键词表去猜。

三层证据的关系
--------------
    异动解析原文（本模块）   ← 同花顺 AI 归纳的公开信息，有出处、可回溯
      ↓ keywordList 计数
    消息面关键词榜            ← "AI漫剧 9 只 / AI短剧 9 只 / 微短剧 5 只" 是同一个词根
      ↓ theme.classify
    消息面主线                ← 并成一条线，看它的涨停数与行业原因

与打分的关系（重要）
--------------------
本模块**不参与个股打分**。概念分仍只用标签（score.py 里的 ntags），
因为打分的口径一改，全站 120 分制的每一条阈值都要重标，收益不抵风险。
这一层只回答"为什么涨、这条消息有多大"，不回答"该给多少分"。
"""
from __future__ import annotations

import collections
import re

import theme as theme_mod

# 非题材词：这些是行情描述、交易属性或技术面，不是"消息"，不能进关键词榜。
# 三季报/业绩类不在这里——它们是真消息（财报披露期），单列为 report 主线。
NOISE = {
    "此前涨幅较大", "超跌反弹", "资金流出", "资金流入", "涨停", "跌停", "大幅波动",
    "换手率", "成交额", "融资融券", "深股通", "沪股通", "机构调研", "央企", "国企",
    "人工智能", "举牌", "增持", "回购", "减持", "解禁", "股权质押", "商誉",
}
_NOISE_RE = re.compile("板块(上涨|下跌|走弱|走强)|^(涨幅|跌幅)|板块异动")
_QUOTES = re.compile(r"[「」“”\"'‘’《》\s]+")


def norm_kw(kw: str) -> str:
    """关键词归一：去掉各种引号与空白。「"羊"字辈」→「羊字辈」，与 score.norm_tag 同口径。"""
    return _QUOTES.sub("", str(kw or "")).strip()


def is_noise(kw: str) -> bool:
    k = norm_kw(kw)
    return (not k) or k in NOISE or bool(_NOISE_RE.search(k))


def split_reason(text: str):
    """拆成 (行业原因, 公司原因)。原文由 fetchers.abnormal.split_reason 提供同款结构，
    这里只做去空白、去免责声明，方便按文本分组计数。"""
    t = str(text or "")
    i = t.find("（免责声明")
    if i < 0:
        i = t.find("(免责声明")
    if i >= 0:
        t = t[:i]
    ind = comp = ""
    j = t.find("公司原因")
    if j >= 0:
        ind, comp = t[:j], t[j:]
    else:
        ind = t
    for pre in ("行业原因：", "行业原因:"):
        if ind.startswith(pre):
            ind = ind[len(pre):]
    for pre in ("公司原因：", "公司原因:"):
        if comp.startswith(pre):
            comp = comp[len(pre):]
    return re.sub(r"\s+", " ", ind).strip(), re.sub(r"\s+", " ", comp).strip()


def _pct_of(code, stocks, zt):
    e = stocks.get(code) or {}
    if e.get("pct") is not None:
        return float(e["pct"])
    z = zt.get(code) or {}
    return float(z["pct"]) if z.get("pct") is not None else None


def _zt_of(code, stocks, zt):
    if code in zt:
        return True
    e = stocks.get(code) or {}
    return bool(e.get("limit_up") or e.get("board_tag"))


def build(data, abn=None, attr=None, f10=None, main_of=None) -> dict:
    """把异动解析聚成「关键词榜 + 主线实况 + 行业消息面」。

    入参全部可选，缺了就退化成空表——页面不许因此消失，只标"今天没抓到"。
    """
    data = data or {}
    stocks = data.get("stocks") or {}
    abn = abn if abn is not None else (data.get("abnormal") or {})
    f10 = f10 if f10 is not None else (data.get("f10") or {})
    attr = attr if attr is not None else {}
    zt = {}
    for x in ((attr.get("today") or {}).get("zt") or []):
        if x.get("code"):
            zt[str(x["code"])] = x
    # attr 缺席时用 bundle 自带的涨停标记兜底
    if not zt:
        for c, e in stocks.items():
            if e.get("limit_up") or e.get("board_tag"):
                zt[c] = {"code": c, "name": e.get("name"), "pct": e.get("pct")}

    # 每只票的行业链最细一级：优先 F10，其次行情接口的 f100
    def finest(code):
        ind = ((f10.get(code) or {}).get("industries") or [])
        return ind[-1]["name"] if ind else (stocks.get(code) or {}).get("industry")

    # 名字表：人气池 → 涨停池 → 异动解析自带的 stockName 三级兜底。
    # 少了这一层，非池内的票在关键词榜上会显示成 002555 这种纯代码。
    names = {c: (e.get("name") or "") for c, e in stocks.items()}
    for x in (data.get("zt_pool") or []):
        c = str(x.get("code") or "")
        names.setdefault(c, x.get("name") or "")
    for c, x in zt.items():
        names[c] = names.get(c) or (x.get("name") or "")
    for c, v in (abn or {}).items():
        names[c] = names.get(c) or (v.get("stock_name") or "")

    by_code, kw_codes = {}, collections.defaultdict(set)
    n_with = 0
    for c, v in (abn or {}).items():
        kws = [norm_kw(k) for k in (v.get("keywords") or [])]
        kws = [k for k in dict.fromkeys(kws) if k]
        if not v.get("reason"):
            continue
        n_with += 1
        ind_r, comp_r = split_reason(v.get("reason"))
        by_code[c] = {
            "date": v.get("date"), "tag": v.get("tag_name") or "",
            "keywords": kws,
            "theme_kw": [k for k in kws if not is_noise(k)],
            "ind_reason": ind_r, "comp_reason": comp_r,
            "industry": finest(c),
        }
        for k in kws:
            if not is_noise(k):
                kw_codes[k].add(c)

    # 每只票的**主归因**：它自己的关键词里落在哪条线上的最多。
    # 这一步是防"业绩"这类横切属性把票全吃掉——一只票可以同时挂「三季报增长」
    # 和「AI短剧」，但它的主归因只能是一个，否则每条线都把全市场算成自己人。
    main_of = main_of or {}
    for c, v in by_code.items():
        cnt = collections.Counter(t for t in (theme_mod.classify(k) for k in v["theme_kw"]) if t)
        if cnt:
            v["kw_hits"] = dict(cnt)
        # 主归因优先用主线层的结论（它还含产业链人工映射，优先级更高），
        # 没有才退回"关键词里最多的那条线"。两处定义必须一致，否则同一页出现
        # "核心 28 只"和"核心 38 只"两个数（2026-11-02 踩过）。
        v["main_kw"] = main_of.get(c) or (max(cnt, key=lambda t: (cnt[t], -theme_mod.BY_ID[t]["order"]))
                                          if cnt else None)

    # ---------------- 关键词榜：按「挂几只涨停股」排，票数相同再看总只数
    rows = []
    for k, codes in kw_codes.items():
        cs = sorted(codes)
        pcts = [p for p in (_pct_of(c, stocks, zt) for c in cs) if p is not None]
        tid = theme_mod.classify(k)
        rows.append({
            "kw": k, "n": len(cs), "n_zt": sum(1 for c in cs if _zt_of(c, stocks, zt)),
            "avg_pct": round(sum(pcts) / len(pcts), 2) if pcts else None,
            "theme": tid,
            "theme_name": (theme_mod.BY_ID[tid]["name"] if tid else None),
            "codes": cs,
            "names": [names.get(c) or c for c in cs],
        })
    rows.sort(key=lambda r: (-r["n_zt"], -r["n"], -(r["avg_pct"] or -99), r["kw"]))

    # ---------------- 主线实况：成员的关键词 + 行业原因原文
    per_theme = {}
    for tid in theme_mod.BY_ID:
        kw_rows = [r for r in rows if r["theme"] == tid]
        if not kw_rows:
            continue
        kw_codes_set = {c for r in kw_rows for c in r["codes"]}
        # 核心＝主归因就是本线的全部票（含"关键词没落在本线、但标签落在本线"的），
        # 成员＝核心 ∪ 关键词挂本线的票。只按关键词取会漏掉 8 只（实测算力 30 vs 38）。
        # 核心只取**主线口径内**的票（人气池 ∪ 今日涨停）：龙虎榜/热榜里那些
        # 既不在池、今天也没涨停的票会进来，但不该算进主线的核心，
        # 否则同一个"核心 38 只"在主线页与实况块会显示成两个数。
        core = sorted(c for c, v in by_code.items()
                      if v.get("main_kw") == tid and (not main_of or c in main_of))
        codes = sorted(set(core) | kw_codes_set)
        inds = collections.Counter(
            (by_code.get(c) or {}).get("industry") for c in codes
            if (by_code.get(c) or {}).get("industry"))
        # 行业原因常常一字不差（同一片票同一个消息），按原文分组数票。
        # 只用**核心成员**的原文：关联成员是被别的消息带进来的，它的行业原因是别人的消息。
        texts = collections.Counter()
        for c in (core or codes):
            t = (by_code.get(c) or {}).get("ind_reason") or ""
            if len(t) >= 8:
                texts[t] += 1
        reps = [{"text": t, "n": n} for t, n in texts.most_common(3)]
        # 公司原因不能取"最常见"——每家公司的原因都不一样，最常见的那条往往只有 1 只。
        # 取"与本线关键词重合最多"的那只票当代表，它的公司原因才像这条线。
        topkw = {x["kw"] for x in kw_rows[:5]}
        rep_c, best_ov = None, -1
        for c in (core or codes):
            ov = len(set((by_code.get(c) or {}).get("theme_kw") or []) & topkw)
            if ov > best_ov and len((by_code.get(c) or {}).get("comp_reason") or "") >= 8:
                rep_c, best_ov = c, ov
        comp_q = ((by_code.get(rep_c) or {}).get("comp_reason") or "") if rep_c else ""
        per_theme[tid] = {
            "id": tid, "name": theme_mod.BY_ID[tid]["name"],
            "n": len(codes), "n_zt": sum(1 for c in codes if _zt_of(c, stocks, zt)),
            "core": core,
            "n_core": len(core),
            "n_core_zt": sum(1 for c in core if _zt_of(c, stocks, zt)),
            "comp_quote": comp_q,
            "comp_name": (names.get(rep_c) or rep_c or "") if rep_c else "",
            "kw": [{"kw": r["kw"], "n": r["n"], "n_zt": r["n_zt"]} for r in kw_rows[:8]],
            "codes": codes,
            "industries": [{"name": k, "n": v} for k, v in inds.most_common(5)],
            "ind_reasons": reps,
            "quote": reps[0]["text"] if reps else "",
            "quote_n": reps[0]["n"] if reps else 0,
        }

    # ---------------- 行业消息面：按最细行业分，回答"这一片为什么一起涨"
    ind_map = collections.defaultdict(lambda: {"codes": [], "texts": collections.Counter()})
    for c, v in by_code.items():
        name = v.get("industry")
        if not name:
            continue
        ind_map[name]["codes"].append(c)
        if len(v.get("ind_reason") or "") >= 8:
            ind_map[name]["texts"][v["ind_reason"]] += 1
    industries = []
    for name, b in ind_map.items():
        texts = [{"text": t, "n": n} for t, n in b["texts"].most_common(2)]
        industries.append({
            "name": name, "n": len(b["codes"]),
            "n_zt": sum(1 for c in b["codes"] if _zt_of(c, stocks, zt)),
            "codes": sorted(b["codes"]),
            "quote": texts[0]["text"] if texts else "",
            "quote_n": texts[0]["n"] if texts else 0,
            "texts": texts,
        })
    industries.sort(key=lambda r: (-r["n_zt"], -r["n"], r["name"]))

    return {
        "by_code": by_code,
        "keywords": rows,
        "themes": per_theme,
        "industries": industries,
        "meta": {
            "n_codes": len(abn or {}), "n_with_reason": n_with,
            "n_kw": len(kw_codes), "n_kw_mapped": sum(1 for r in rows if r["theme"]),
            "n_zt": len(zt),
            "n_kw_noise": sum(len(v.get("keywords") or []) for v in (abn or {}).values())
                           - sum(len(v.get("theme_kw") or []) for v in by_code.values()),
        },
    }


def kw_of(news, code):
    """某只票的关键词（页面用）：原始词 + 每个词在全市场的共享只数。"""
    if not news:
        return []
    cnt = {r["kw"]: r["n"] for r in news.get("keywords") or []}
    v = (news.get("by_code") or {}).get(str(code).zfill(6)) or {}
    out = []
    for k in v.get("keywords") or []:
        out.append({"kw": k, "n": cnt.get(k, 1), "noise": is_noise(k)})
    return out
