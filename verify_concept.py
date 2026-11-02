# -*- coding: utf-8 -*-
"""概念总榜验收 —— 五因子独立复算，不照抄实现里的中间变量。

背景（2026-11-02 用户质疑）：
    旧口径 strength = min(成分数,10) × 上升占比，把「共封装光学(CPO)」14 只全升
    算成 10.00 分，压过了「羊字辈」24 只里 10 只涨停的 9.33 分。
    用户原话：CPO 全市场不止 13 只，只是入榜 13 只；入榜数和涨停数都不如羊字辈，
    凭什么第一。这条批评成立——min(n,10) 把样本量抹平后，只剩"谁 100% 在升"。

本脚本验的是"新口径真的按五因子在算"，而不是"结果刚好符合预期"：
    A 分项加总 = 总分；B 排序单调；C 涨停维度打满的条件；
    D 样本收缩真的生效；E 涨幅缺失不被当成 0；F 行情描述型标签被排除；
    G CPO 不是第一且涨停维度明显低于羊字辈；H 首页推荐序真的掺入了四维分。
"""
from __future__ import annotations

import json
import math
import re
import sys
import urllib.request
from urllib.parse import quote

import score as S
import store

BASE = "http://127.0.0.1:888"
_ok = _bad = 0


def chk(name, got, want):
    global _ok, _bad
    ok = got == want
    globals()["_ok" if ok else "_bad"] += 1
    print("  %s %-42s %s" % ("✓" if ok else "✗", name, "" if ok else "期望 %r 实际 %r" % (want, got)))


def http(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return r.read().decode("utf-8", "ignore")


def main() -> int:
    bundle, _meta = store.load_bundle()
    stocks = bundle["stocks"]
    _d8, snap = store.load_snapshot(None)
    rows = S.concept_board(stocks, snap, bundle.get("concept_stats"))
    by = {r["concept"]: r for r in rows}

    print("== A 分项与总分 ==")
    bad_sum = [(r["concept"], r["total"], round(sum(r["sub"].values()), 1))
               for r in rows if abs(r["total"] - sum(r["sub"].values())) > 0.25]
    chk("每行五项之和 = 概念分（容差 0.25）", bad_sum, [])
    over = [r["concept"] for r in rows if r["total"] > 100.5]
    chk("概念分不越界（≤100）", over, [])
    chk("概念数量合理（20~80 个）", 20 <= len(rows) <= 80, True)

    print("\n== B 排序 ==")
    chk("按概念分单调不增",
        all(a["total"] >= b["total"] for a, b in zip(rows, rows[1:])), True)
    chk("rank 从 1 连续到下", [r["rank"] for r in rows], list(range(1, len(rows) + 1)))

    print("\n== C 涨停维度（全市场涨停梯队归因）==")
    boards = {}
    for lv in (snap.get("ladder") or []):
        for s in (lv.get("stocks") or []):
            boards[s.get("code")] = max(boards.get(s.get("code"), 1), int(lv["board"]))
    yz = by.get("羊字辈")
    cpo = by.get("共封装光学(CPO)")
    chk("羊字辈在榜", yz is not None, True)
    chk("羊字辈涨停数 ≥ 8（本月实测 10）", (yz or {}).get("limit_up", 0) >= 8, True)
    chk("羊字辈最高板 ≥ 2", (yz or {}).get("max_board", 0) >= 2, True)
    chk("羊字辈涨停分接近满分（≥25/30）", (yz or {}).get("sub", {}).get("lu", 0) >= 25, True)
    chk("CPO 在榜", cpo is not None, True)
    chk("CPO 涨停数 < 羊字辈", (cpo or {}).get("limit_up", 0) < (yz or {}).get("limit_up", 0), True)
    chk("CPO 涨停分不到羊字辈一半",
        (cpo or {}).get("sub", {}).get("lu", 99) < (yz or {}).get("sub", {}).get("lu", 0) / 2, True)

    print("\n== D 样本收缩（旧坑：min(n,10) 抹平样本量）==")
    def shrink(up, n):
        return (up * n + 0.5 * S.CON_SEED) / (n + S.CON_SEED)
    for nm, r in (("羊字辈", yz), ("共封装光学(CPO)", cpo)):
        if not r:
            continue
        chk("%s 收缩后上升占比 = 独立复算" % nm,
            abs(r["up_adj"] - round(shrink(r["up"], r["n"]), 3)) < 0.006, True)
    if cpo and yz:
        chk("CPO 原始上升占比更高（100% vs 93%）", cpo["up"] > yz["up"], True)
        chk("但收缩后差距被压到 <0.06（小样本不再通吃）",
            abs(cpo["up_adj"] - yz["up_adj"]) < 0.06, True)
        chk("CPO 概念分低于羊字辈", cpo["total"] < yz["total"], True)
        chk("CPO 不是第一", rows[0]["concept"] != "共封装光学(CPO)", True)
        print("        CPO 第 %d 名 %.1f 分　羊字辈 第 %d 名 %.1f 分"
              % (cpo["rank"], cpo["total"], yz["rank"], yz["total"]))
    # 3 只全升的小概念不能因为 100% 就冲进前三
    tiny = [r for r in rows if r["n"] <= 3 and r["up"] >= 0.99]
    chk("≤3 只且全升的小概念不进前三", [r["concept"] for r in tiny if r["rank"] <= 3], [])

    print("\n== E 涨幅缺失不算 0 ==")
    for nm, r in (("共封装光学(CPO)", cpo), ("羊字辈", yz)):
        if not r:
            continue
        print("        %s：n=%d 有涨幅样本=%d 均涨幅=%s"
              % (nm, r["n"], r["n_pct"], r["avgpct"]))
    chk("CPO 涨幅样本不足时 avgpct 为 None",
        (cpo or {}).get("avgpct") is None, (cpo or {}).get("n_pct", 99) < S.CON_MIN_PCT)
    chk("样本不足时涨幅分＝中性半分 7.5",
        (cpo or {}).get("sub", {}).get("rise"), S.CON_W["rise"] * 0.5)
    # 若把缺失当 0 算，CPO 均涨幅会变成 0.71 左右；验证实际不是
    if cpo:
        pcts = [stocks[c]["pct"] for c in cpo["codes"] if stocks[c].get("pct") is not None]
        real = sum(pcts) / len(pcts) if pcts else None
        chk("CPO 均涨幅不等于「缺失补 0」的算法",
            cpo["avgpct"] is None or (real is not None and abs(cpo["avgpct"] - real) < 0.01), True)

    print("\n== F 行情描述型标签不入选 ==")
    chk("「CPO板块下跌」不在概念榜", "CPO板块下跌" in by, False)
    chk("非概念标签被识别（正则）", bool(S.NON_CONCEPT.search("PCB板块下跌")), True)
    chk("正常概念不被误杀",
        [t for t in ("羊字辈", "三季报扭亏", "共封装光学(CPO)") if S.NON_CONCEPT.search(t)], [])

    print("\n== G 页面 ==")
    hc = http("/concept")
    chk("含五因子说明", all(k in hc for k in ("涨停 30", "上升广度 25", "人气 20",
                                            "赚钱效应 15", "龙头高度 10")), True)
    chk("含「入榜只数 ≠ 概念总规模」澄清", "入榜只数 ≠ 概念总规模" in hc, True)
    chk("说明贝叶斯收缩", "贝叶斯收缩" in hc, True)
    chk("首行是羊字辈", "羊字辈" in hc.split("概念总榜")[1][:400], True)
    # 表格里的概念分与模块一致（抽前 5 行）
    body_c = hc.split("概念总榜")[1].split("</table>")[0]
    shown = [float(x) for x in re.findall(r'min-width:34px;text-align:right">([\d.]+)<', body_c)][:5]
    chk("页面前 5 行概念分 = 模块", shown, [round(r["total"], 1) for r in rows[:5]])
    chk("单概念页能打开", "概念分" in http("/concept?c=" + quote("羊字辈")), True)
    # 拆解条 5 段
    chk("每行拆解条为多段堆叠", body_c.count("<i style=\"width:") >= len(rows) * 3, True)

    print("\n== H 首页推荐序掺入四维分 ==")
    from sec_core import derive
    from picks import pick_stocks
    dv = derive(snap, [], None)
    pk = pick_stocks(snap, dv, S.build(bundle))
    a = pk["a"]
    chk("A 档非空", len(a) > 0, True)
    chk("A 档按推荐序降序",
        all(x["rec"] >= y["rec"] for x, y in zip(a, a[1:])), True)
    red = [x for x in a if x["code"] == "000525"]
    chk("红太阳（四维全池第一）在 A 档", bool(red), True)
    if red:
        chk("红太阳按推荐序排 A 档第 1", a.index(red[0]) == 0, True)
        expect = round(0.55 * red[0]["sc"] + 0.45 * red[0]["score"], 1)
        chk("推荐序 = 0.55×四维 + 0.45×共振", red[0]["rec"], expect)
        print("        红太阳 四维 %s · 共振 %d · 推荐 %s" %
              (red[0]["sc"], red[0]["score"], red[0]["rec"]))
    chk("缺四维分的票 rec 只剩共振那 45%（不给默认分）",
        all(abs(x["rec"] - round(0.45 * x["score"], 1)) < 0.15
            for x in a if x.get("sc") is None), True)
    html_home = http("/")
    # 注意：CSS 注释里也有「A 档/B 档」字样，必须用带类名的锚点定位
    _a = html_home.find('tier-h a">A 档')
    _b = html_home.find('tier-h b">B 档')
    seg = html_home[_a:_b] if 0 <= _a < _b else ""
    chk("首页能找到 A 档区块", bool(seg), True)
    chk("首页 A 档第一张卡是红太阳", "红太阳" in seg[:1400], True)
    chk("卡片印出推荐分与共振分", ("推荐" in seg) and ("共振" in seg), True)

    print("\n结论：%s（通过 %d 项，失败 %d 项）"
          % ("PASS" if _bad == 0 else "FAIL", _ok, _bad))
    return 0 if _bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
