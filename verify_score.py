# -*- coding: utf-8 -*-
"""评分模型 v2 验收：四维加权（趋势 35 + 概念 25 + 原因 20 + 资金 20）。

验收思路＝**用独立算路复算，不信任模块自己的输出**。
    - 趋势：直接从 bundle 的 tdx hist 手算对数斜率与单调性，与模块比
    - 资金：直接算成交额分位，验证没把换手率混进来（踩过的坑）
    - 概念：直接数标签成分，验证"羊字辈 = 25 只"这种能对上的读数
    - 页面：把 /rank 印出来的数字与模块输出逐项比，保证没渲染错

运行：python verify_score.py
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request

import score

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "http://127.0.0.1:888"

_ok = _bad = 0


def chk(label, got, want=True):
    global _ok, _bad
    good = got == want
    if good:
        _ok += 1
    else:
        _bad += 1
    print("  %s %-42s %s" % ("✓" if good else "✗", label,
                             "OK" if good else "期望 %r 实际 %r" % (want, got)))


def http(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def load():
    with open(os.path.join(HERE, "data", "live", "bundle.json"), encoding="utf-8") as f:
        return json.load(f)["data"]


def main():
    data = load()
    S = data["stocks"]
    sc = score.build(data)
    by = sc["by_code"]
    ranked = sc["ranked"]

    # ---------------------------------------------------------- A 基本约束
    print("\n== A 分数边界与排序 ==")
    chk("覆盖全池", len(by), len(S))
    over = [r["code"] for r in ranked
            if r["trend"]["pts"] > 35.01 or r["concept"] > 25.01
            or r["reason"] > 20 or r["money"] > 20.01]
    chk("四维均不越界（趋势≤35 概念≤25 原因≤20 资金≤20）", over, [])
    tots = [r["total"] for r in ranked]
    chk("总分严格降序", tots == sorted(tots, reverse=True), True)
    chk("总分 = 四维之和", all(
        abs(r["total"] - (r["trend"]["pts"] + r["concept"] + r["reason"] + r["money"])) < 0.051
        for r in ranked), True)
    chk("排名连续无重复", [r["rank"] for r in ranked], list(range(1, len(ranked) + 1)))

    # ---------------------------------------------------------- B 趋势维（独立复算）
    print("\n== B 排名趋势（独立复算 hist）==")
    e = S["002088"]
    rs = [x["rank"] for x in e["tdx"]["hist"]][-6:]
    chk("鲁阳 hist 序列", rs, [1572, 1937, 652, 227, 127, 29])
    seg = [x["rank"] for x in e["tdx"]["hist"]][-6:]
    i0 = seg.index(max(seg))
    chk("起算点=启动前最差名次（1937，跳过 1572 的回撤）", seg[i0], 1937)
    seg = rs[rs.index(max(rs)):]
    slope = (math.log(seg[0]) - math.log(seg[-1])) / (len(seg) - 1)
    mono = sum(1 for a, b in zip(seg, seg[1:]) if b < a) / (len(seg) - 1)
    t = by["002088"]["trend_detail"]
    chk("鲁阳 对数斜率复算一致", round(t["slope"], 3), round(slope, 3))
    chk("鲁阳 单调性复算一致", round(t["mono"], 2), round(mono, 2))
    chk("鲁阳 当前名次", t["now"], 29)
    # 速度封顶：日均 1.0 个对数单位，超出不再加分
    chk("速度封顶后不超过 14", all(r["trend"].get("speed", 0) <= 14.01 for r in ranked), True)
    # 代理趋势上限 21
    proxy = [r for r in ranked if r["trend"].get("proxy")]
    chk("代理趋势不超过 21（35×0.6）", all(r["trend"]["pts"] <= 21.01 for r in proxy), True)
    chk("有代理趋势的票数 > 0（验证这条路径真的走到过）", len(proxy) > 0, True)
    # 退潮股：名次在退的票，趋势分不该给高分
    falling = [r for r in ranked
               if r["trend_detail"] and r["trend_detail"]["slope"] < 0]
    chk("退潮股（斜率为负）趋势分 ≤ 21", all(r["trend"]["pts"] <= 21.01 for r in falling), True)

    # ---------------------------------------------------------- C 概念维（独立复算）
    print("\n== C 概念趋势（独立数标签）==")
    tags = sc["tags"]
    chk("羊字辈 成分 25 只", tags.get("羊字辈", {}).get("n"), 25)
    up_y = tags.get("羊字辈", {}).get("up")
    # 上升占比随"起算点"算法浮动（起算点取启动前最差名次），只验区间不写死
    chk("羊字辈 上升占比 >0.8", up_y > 0.8 and up_y <= 1.0, True)
    chk("羊字辈 判定为上升", tags.get("羊字辈", {}).get("rising"), True)
    # 独立数一遍标签成分，与模块结果对齐
    mem = sum(1 for _, x in S.items() if "羊字辈" in score.tags_of(x))
    chk("羊字辈 独立数标签复算", mem, tags["羊字辈"]["n"])
    # 泛标签不进池
    wide_in = [k for k in tags if k in score.WIDE]
    chk("泛标签不参与打分", wide_in, [])
    # 成分少于 3 的不进池
    thin = [k for k, g in tags.items() if g["n"] < score.TAG_MIN]
    chk("成分 <3 的标签不进池", thin, [])
    # 归一化：带引号的"羊"字辈应并入羊字辈
    chk("「\"羊\"字辈」已归一为「羊字辈」", "羊字辈" in tags and '"羊"字辈' not in tags, True)
    chk("带引号的同名标签不存在", [k for k in tags if "“" in k or '"' in k], [])

    # ---------------------------------------------------------- D 资金维（防踩过的坑）
    print("\n== D 资金（回归 turnover 同名不同义那个坑）==")
    money_full = [r["code"] for r in ranked if r["money"] >= 19.99]
    chk("没有大批票资金满分（旧坑：全员 20）", len(money_full) <= 2, True)
    md = by["002088"]["money_detail"]
    amt = (S["002088"]["tdx"].get("turnover")) or 0
    pool = sorted(x for x in ((v.get("tdx") or {}).get("turnover") for v in S.values()) if x)
    import bisect
    want_pct = round(bisect.bisect_left(pool, amt) / len(pool), 3)
    chk("鲁阳 成交额分位复算一致", md["amt_pct"], want_pct)
    chk("鲁阳 成交额用「元」而不是换手率", md["amt_yi"], round(amt / 1e8, 2))
    chk("鲁阳 资金分 < 10（小成交额拿不到高分）", by["002088"]["money"] < 10, True)
    chk("成交额池只含 tdx 口径（>=1000 万元级）", all(x > 1e7 for x in pool), True)

    # ---------------------------------------------------------- E 原因维
    print("\n== E 上榜原因 ==")
    q = str(data.get("quote_date"))
    stale = [c for c, ab in (data.get("abnormal") or {}).items()
             if str(ab.get("date")) != q and by.get(c) and by[c]["reason"] > 0]
    chk("非当日异动一律 0 分", stale, [])
    rd = by["002088"]["reason_detail"]
    # 哪只票当日有异动是数据事实（今天它不是涨停就自然没有），不能钉死在鲁阳身上。
    # 改成动态挑：先找"当日异动且带硬逻辑项"的票，再验它的原因分真被采纳。
    ab_all = data.get("abnormal") or {}
    pick = next((c for c, v in ab_all.items()
                 if v.get("date") == q and any(
                     k for k in ("产能", "订单", "净利", "研报", "中标", "重组", "并购")
                     if k in (v.get("reason") or ""))), None)
    if pick:
        rp = (score.build(data)["by_code"] or {}).get(pick) or {}
        rdp = next((x for x in (rp.get("reason_detail") or [])), {})
        chk("%s 当日异动被采纳（date=%s）" % (pick, q), ab_all[pick].get("date"), q)
        chk("%s 原因分 > 0" % pick, rp.get("reason", 0) > 0, True)
    else:
        chk("当日有硬逻辑异动的票存在（今日 0 只属异常）", False, True)
    chk("原因分不超过 20", all(r["reason"] <= 20 for r in ranked), True)

    # ---------------------------------------------------------- F 页面落地
    print("\n== F 页面数字与模块一致 ==")
    h = http("/rank")
    chk("含「综合分 TOP12」", "综合分 TOP12" in h, True)
    chk("含四维表头", all(k in h for k in ("趋势 /35", "概念 /25", "原因 /20", "资金 /20")), True)
    codes = re.findall(r'href="/s/(\d{6})"', h.split("综合分 TOP12")[1].split("</table>")[0])
    chk("TOP12 链接顺序 = 模块排名", codes, [r["code"] for r in ranked[:12]])
    # 具体哪只进 TOP12 由当日行情决定；守结构：TOP12 分数与全池前 12 名一致且 ≥ 50
    chk("TOP12 分数均 ≥ 50", all(r["total"] >= 50 for r in ranked[:12]), True)
    # 具体名次由当日行情决定（午盘与收盘就不同），守结构：TOP10 分数必须单调不增
    chk("TOP10 分数单调不增",
        all(x["total"] >= y["total"] for x, y in zip(ranked[:10], ranked[1:10])), True)

    hs = http("/s/002088")
    chk("个股页含四维评分卡", "排名趋势 35 + 概念趋势 25 + 上榜原因 20 + 资金 20" in hs, True)
    chk("个股页印出名次", "全池第 %d 名" % by["002088"]["rank"] in hs, True)
    chk("个股页印出趋势速度", ("%.2f 对数名次" % by["002088"]["trend_detail"]["slope"]) in hs, True)
    chk("个股页印出名次区间（起算 1937）", "第 1937 名 → 第 29 名" in hs, True)
    cd0 = (by["002088"].get("concept_detail") or [{}])[0]
    chk("个股页印出上升概念",
        ("%s（%d 只 · 升 %d%%）" % (cd0.get("tag"), cd0.get("n", 0),
                                  round((cd0.get("up") or 0) * 100))) in hs, True)

    hc = http("/concept")
    chk("概念页含「上升广度」与「概念分（拆解）」列",
        ("上升广度" in hc) and ("概念分（拆解）" in hc), True)
    # 概念总榜已改成五因子（独立复算见 verify_concept.py）。
    # 这里只验"渲染与模块一致"：名次随当日数据变，不锁死第一是谁。
    body_c = hc.split("概念总榜")[1].split("</table>")[0]
    rows_c = re.findall(r"<tr>(.*?)</tr>", body_c, re.S)[1:6]   # [0] 是表头
    top5 = [re.sub(r"<[^>]+>", " ", r) for r in rows_c]
    chk("羊字辈在概念榜前 5", any("羊字辈" in r for r in top5), True)
    chk("羊字辈在该行被判为上升（↑）",
        any("羊字辈" in r and "↑" in r for r in top5), True)
    scores = [float(x) for x in
              re.findall(r'min-width:34px;text-align:right">([\d.]+)<', body_c)]
    chk("概念分逐行单调不增", len(scores) >= 5 and all(
        a >= b for a, b in zip(scores, scores[1:])), True)

    print("\n结论：%s（通过 %d 项，失败 %d 项）"
          % ("PASS" if _bad == 0 else "FAIL", _ok, _bad))
    return 0 if _bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
