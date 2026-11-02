# -*- coding: utf-8 -*-
"""本轮新增验收：龙虎榜列 + 10 日排名 + 概念口径 + A 档榜单通道。

跑法：python verify_lhb.py        （需要 data/live/bundle.json 与 :888 服务在跑）
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

import store
import score as scoring
from picks import pick_stocks
from sec_core import derive
from render import page_rank, page_stock, page_home

HERE = os.path.dirname(os.path.abspath(__file__))
OK = FAIL = 0


def chk(name, got, want=True):
    global OK, FAIL
    good = got == want
    OK, FAIL = OK + good, FAIL + (not good)
    print("  %s %s%s" % ("✓" if good else "✗", name,
                         "" if good else "%s期望 %r 实际 %r " % (" " * max(1, 30 - len(name)), want, got)))


def fetch(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.read().decode("utf-8", "ignore")


def main():
    data, meta = store.load_bundle()
    chk("bundle 含龙虎榜", bool(data.get("lhb")))
    lhb = data["lhb"]
    chk("龙虎榜覆盖 ≥ 400 只", len(lhb) >= 400, True)
    chk("冰山冷热 30 日上榜 23 次", (lhb.get("000530") or {}).get("n30"), 23)
    chk("红太阳近 30 天未上榜", (lhb.get("000525") or {}).get("n30") or 0, 0)
    m = data.get("lhb_meta") or {}
    rec = m.get("recon") or {}
    chk("同花顺/东财次数对拍 ≥ 90%",
        rec.get("n_both") and rec["n_same"] / rec["n_both"] >= 0.9, True)
    chk("机构席位来自同花顺（冰山冷热 93 席）",
        (lhb.get("000530") or {}).get("jg_seats"), 93)

    sc = scoring.build(data)
    r1 = sc["ranked"][0]
    # v3 加了行业维＋双轮共振（用户令：行业和概念同时热要加分）。收盘池每天换血，
    # 谁第一、base100 谁最高都是当日事实，钉死必翻车。守结构：
    #   ① base100 与 total 各自严格降序（两套口径都成立）；
    #   ② 第 1 名有硬逻辑支撑（drive ∈ 双轮/概念/行业）且严格领先；
    #   ③ base100 第 1 的分数 ≥ 65（四维口径没有通胀）。
    b1 = max(sc["ranked"], key=lambda r: r["base100"])
    chk("base100 全部在 0~100（四维口径未越界）",
        all(0 <= r["base100"] <= 100.01 for r in sc["ranked"]), True)
    chk("total ≥ base100（行业分与共振非负）",
        all(r["total"] >= r["base100"] - 0.001 for r in sc["ranked"]), True)
    chk("综合分第 1 名有硬逻辑支撑", r1["drive"] in ("双轮", "概念", "行业"), True)
    # 分数随当日行情变化（午盘/收盘不同），别把某一天的 87.4 钉死；
    # 真正要守的是"它凭什么第一"——分数要拉开差距，不是刚好压线。
    chk("总分 ≥ 70 且严格第一（领先第 2 名 > 0）",
        r1["total"] >= 70 and r1["total"] > sc["ranked"][1]["total"], True)
    chk("base100 第 1 分数 ≥ 65（四维口径未通胀）", b1["base100"] >= 65, True)
    all_tags = [d["tag"] for r in sc["by_code"].values() for d in r["concept_detail"]]
    # 扭亏标签是否参与打分是**口径事实**，不随当日池子变；守口径层而不是守当日样本。
    chk("三季报扭亏不在泛标签（应计入趋势）", "三季报扭亏" not in scoring.WIDE, True)
    chk("三季报扭亏不被当情绪词", "扭亏" not in scoring.SOFT.pattern, True)
    chk("三季报增长仍是泛标签", "三季报增长" in scoring.WIDE, True)
    chk("羊字辈标签未被移出标签池", "羊字辈" not in scoring.WIDE, True)

    html_rank = page_rank.render(data, meta)
    chk("综合分表列头为 10 日排名", "10 日排名" in html_rank, True)
    chk("旧列头近 5 步名次已移除", "近 5 步名次" not in html_rank, True)
    chk("人气榜标题不带说明尾巴",
        "人气榜 · 一张表" not in html_rank and "<h2>人气榜<" in html_rank, True)
    chk("人气榜表不再显示涨停原因列", "<th>涨停原因</th>" not in html_rank, True)
    chk("人气榜含 30 日上榜列", "30日上榜" in html_rank, True)
    chk("人气榜含机构席位徽章", "机构" in html_rank and "席" in html_rank, True)
    chk("人气榜含龙虎榜净买列", "龙虎榜净买" in html_rank, True)
    chk("5日趋势已改 10 日", "10日趋势" in html_rank and "<th>5日趋势</th>" not in html_rank, True)

    html_525 = page_stock.render("000525", data["stocks"]["000525"], data, meta)
    chk("红太阳详情页有龙虎榜卡", "龙虎榜" in html_525, True)
    chk("未上榜有解释文案", "近 30 天没上过龙虎榜" in html_525, True)
    chk("概念 chip 带成分数", "本池成分数" in html_525, True)
    chk("百草枯标注不足 3 只", "不足 3 只" in html_525, True)
    html_530 = page_stock.render("000530", data["stocks"].get("000530") or {"code": "000525"}, data, meta) \
        if data["stocks"].get("000530") else ""
    if html_530:
        chk("冰山冷热详情页印出上榜 23 次", "23 次" in html_530, True)
        chk("冰山冷热详情页印出机构 93 席", "93 席" in html_530, True)

    # A 档榜单通道：哪只票进 A 档是当日事实（收盘池 137 只 vs 午盘 177 只完全不同），
    # 钉死红太阳必翻车。守结构：A 档非空、榜单通道门槛生效、页面真的印出来了。
    d8, snap = store.load_snapshot(None)
    dv = derive(snap, [], None)
    pk = pick_stocks(snap, dv, sc)
    a_names = [x["name"] for x in pk["a"]]
    chk("首页 A 档非空", len(a_names) > 0, True)
    chk("榜单通道门槛 75/30 生效（B 档无人混入）",
        all(x.get("via") == "resonance" or (x.get("sc") or 0) >= 75 for x in pk["a"]), True)
    chk("A 档每只都在综合分模型里",
        all(x["code"] in sc["by_code"] for x in pk["a"] if x.get("via") == "score"), True)
    html_home = page_home.render(snap, [], dv, pk, sc=sc)
    _a = html_home.find("tier-h a")          # CSS 注释里也有"A 档"字样，用类名定位
    _b = html_home.find("tier-h b")
    chk("首页 A 档印出至少一只票", 0 <= _a < _b and _b - _a > 200, True)
    if a_names:
        chk("首页 A 档印出 A 档第一名", a_names[0] in html_home[_a:_b], True)
    chk("首页有榜单通道徽章", "榜单通道" in html_home, True)
    chk("首页含配色新类", "tier-h a" in html_home and 'class="pk a"' in html_home, True)

    print("\n结论：%s（通过 %d 项，失败 %d 项）"
          % ("PASS" if not FAIL else "FAIL", OK, FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
