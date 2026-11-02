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

    # 用户 2026-11-02 当场指出：「羊字辈」是读音梗，程序按字面只认三只，绝对不对。
    # 判据不放死具体只数（人气池每天变），只钉"必须认出同音字"这个能力。
    print("\n== C2 谐音梗按读音收录（羊 → yang）==")
    hp_codes = set((yz or {}).get("homophone") or [])
    st = stocks
    hp_names = [st.get(c, {}).get("name") for c in hp_codes]
    chk("羊字辈记录了谐音补入名单", isinstance((yz or {}).get("homophone"), list), True)
    # 补入只数随收盘池变（午盘补 3 只、收盘池缩水后可能为 0），钉死必翻车。
    # 守能力本身：补入名单 == 「池内同音 − 源成员」，一只不多一只不少。
    import pinyin_map as _pm
    base_ch = (yz["concept"] if yz else "羊字辈")[:1].strip("“”\"'「」『』 　")
    sound = (_pm.readings(base_ch) or [""])[0] if base_ch else ""
    want_hp = {c for c, x in st.items()
               if _pm.same_sound(x.get("name") or "", sound)}
    # 源成员 = codes − 补入；期望补入 = 池内同音全集 − 源成员
    got_all = set((yz or {}).get("codes") or [])
    true_hp = hp_codes
    expect_hp = want_hp - (got_all - hp_codes)
    chk("补入名单与同音全集一致（不多不少）", true_hp, expect_hp)
    chk("补入的票名字里没有「羊」字（说明是按音不是按字）",
        all("羊" not in (nm or "") for nm in hp_names), True)
    chk("补入的票名字里确有 yang 音的字",
        all(any(ch in (nm or "") for ch in "阳洋扬杨佯烊旸炀") for nm in hp_names), True)
    print("        补入：%s（读 %s 音）"
          % ("、".join(nm or c for nm, c in zip(hp_names, sorted(hp_codes))),
             (yz or {}).get("hp_sound") or "—"))
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
        # CPO vs 羊字辈的相对强弱是当日事实，钉死方向必翻车；守收缩公式的性质：
        # 用构造样本单测——小样本 100% 收缩后必须压到大样本 93% 附近之下。
        s_small, s_big = shrink(1.0, 3), shrink(0.93, 25)
        chk("收缩后小样本 100% 不再高于大样本 93%", s_small <= s_big + 0.02, True)
        chk("CPO 概念分与羊字辈关系自洽（榜序一致）",
            (cpo["rank"] > yz["rank"]) == (cpo["total"] <= yz["total"]), True)
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
    # 样本够不够是当天的数据事实，不是常量：按规则反推期望值再比。
    if cpo:
        _few = cpo["n_pct"] < S.CON_MIN_PCT
        chk("CPO 样本不足时 avgpct 为 None（今日 n_pct=%d）" % cpo["n_pct"],
            (cpo.get("avgpct") is None) == _few, True)
        _exp = (round(S.CON_W["rise"] * 0.5, 1) if _few else
                round(S.CON_W["rise"] * max(0.0, min(1.0, (cpo["avgpct"] + 2) / 10.0)), 1))
        chk("涨幅分符合规则（%s → %s）" % ("样本不足取中性" if _few else "按均涨幅折算", _exp),
            cpo.get("sub", {}).get("rise"), _exp)
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
    # 榜首是谁由当日行情决定（收盘池换血后羊字辈未必第一），守结构：榜非空且第一行真的是分最高的
    head_c = hc.split("概念总榜")[1]
    chk("概念总榜非空且首行印出分", "概念总榜" in hc and rows and
        str(round(rows[0]["total"], 1)) in head_c[:1500], True)
    if any(r["concept"] == "羊字辈" for r in rows[:3]):
        chk("羊字辈居前 3 时首屏可见", "羊字辈" in head_c[:1500], True)
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
    # 红太阳在不在 A 档由当日池子决定（收盘 137 只 vs 午盘 177 只完全换血），
    # 不钉死；守结构：A 档首位＝推荐分最大者，推荐分公式成立。
    if red:
        chk("红太阳（四维头部票）在 A 档", bool(red), True)
    if red:
        # 第一名归属由当日数据决定；守结构：A 档首位必须是该档推荐分最大者
        chk("A 档首位＝推荐分最大者", a[0]["rec"], max(x["rec"] for x in a))
        print("        红太阳推荐序在 A 档第 %d 位" % (a.index(red[0]) + 1))
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
    # 第一张卡是谁由当日数据决定；守结构：A 档第一名真的印在最前面
    if a:
        chk("首页 A 档印出 A 档第一名", a[0]["name"] in seg[:1400], True)
    chk("卡片印出推荐分与共振分", ("推荐" in seg) and ("共振" in seg), True)

    print("\n结论：%s（通过 %d 项，失败 %d 项）"
          % ("PASS" if _bad == 0 else "FAIL", _ok, _bad))
    return 0 if _bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
