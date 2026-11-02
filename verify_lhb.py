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
    chk("红太阳综合分全池第 1", r1["code"], "000525")
    chk("红太阳 ≥ 85", r1["total"] >= 85, True)
    tags = [d["tag"] for d in r1["concept_detail"]]
    chk("三季报扭亏计入概念趋势", "三季报扭亏" in tags, True)
    chk("三季报增长仍是泛标签", "三季报增长" in scoring.WIDE, True)
    chk("羊字辈仍在概念明细", "羊字辈" in tags, True)

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

    # A 档榜单通道
    d8, snap = store.load_snapshot(None)
    dv = derive(snap, [], None)
    pk = pick_stocks(snap, dv, sc)
    a_names = [x["name"] for x in pk["a"]]
    chk("红太阳进首页 A 档", "红太阳" in a_names, True)
    a525 = [x for x in pk["a"] if x["code"] == "000525"]
    chk("红太阳走榜单通道", a525 and a525[0].get("via") == "score", True)
    chk("榜单通道门槛 75/30 生效（B 档无人混入）",
        all(x.get("via") == "resonance" or (x.get("sc") or 0) >= 75 for x in pk["a"]), True)
    html_home = page_home.render(snap, [], dv, pk, sc=sc)
    _a = html_home.find("tier-h a")          # CSS 注释里也有"A 档"字样，用类名定位
    _b = html_home.find("tier-h b")
    chk("首页 A 档印出红太阳", 0 <= _a < _b and "红太阳" in html_home[_a:_b], True)
    chk("首页有榜单通道徽章", "榜单通道" in html_home, True)
    chk("首页含配色新类", "tier-h a" in html_home and 'class="pk a"' in html_home, True)

    print("\n结论：%s（通过 %d 项，失败 %d 项）"
          % ("PASS" if not FAIL else "FAIL", OK, FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
