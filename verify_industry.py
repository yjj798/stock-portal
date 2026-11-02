# -*- coding: utf-8 -*-
"""行业维度验收：数据、评分、双轮判定、页面，四层都查。

背景：2026-11-02 用户令——原来只有概念（故事）一个维度，要求加上行业，
行业和概念同时热（双轮）要加分，并且页面上把两者区分开。
这里的断言守的就是这套口径不被改坏。
"""
from __future__ import annotations

import sector
import score as scoring
from fetchers import industry as ind_f
from render import page_industry, page_rank, page_stock, page_home
import store

PASS, FAIL = 0, 0


def chk(name, got, want):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print("  %s %s%s" % ("✓" if ok else "✗", name,
                         "" if ok else "　期望 %r 实际 %r" % (want, got)))


data, meta = store.load_bundle()
print("== A 数据层 ==")
chk("bundle 带 industry 段", bool(data.get("industry")), True)
blocks = sector.blocks_of(data)
chk("行业板块 ≥ 300 个", len(blocks) >= 300, True)
by_code = sector.by_code_of(data)
chk("池内行业归属覆盖 ≥ 90%", len(by_code) / max(len(data.get("stocks") or {1: 1}), 1) >= 0.9, True)
n_matched = sum(1 for v in by_code.values() if v in blocks)
chk("归属名能对上板块指数 ≥ 95%", n_matched / max(len(by_code), 1) >= 0.95, True)
chk("板块读数带涨幅/涨跌家数",
    all(v.get("pct") is not None and v.get("up") is not None
        for v in list(blocks.values())[:50]), True)

print("== B 评分层 ==")
sc = scoring.build(data)
m = sc["meta"]
chk("meta 带行业维满分 14", m.get("ind_full"), 14.0)
chk("meta 带共振满分 6", m.get("reso_full"), 6.0)
ranked = sc["ranked"]
chk("总分不越界（≤120）", all(r["total"] <= 120.01 for r in ranked), True)
chk("行业分不越界（0~14）", all(0 <= r["ind"] <= 14.01 for r in ranked), True)
chk("共振分只有 0 或 6", all(r["reso"] in (0.0, 6.0) for r in ranked), True)
# 双轮判定复核：drive=双轮 ⇔ 行业热 且 概念分过半
bad = [r["code"] for r in ranked
       if (r["drive"] == "双轮") != (bool((r["industry"] or {}).get("hot"))
                                    and r["concept"] >= sector.CON_HOT)]
chk("双轮判定与两个判据严格一致", bad, [])
# 单边不该有共振分
bad2 = [r["code"] for r in ranked
        if r["reso"] and r["drive"] != "双轮"]
chk("共振分只发给双轮", bad2, [])
# 缺行业归属的票：行业分 0 且如实标注，而不是冒充"行业弱"
missing = [r["code"] for r in ranked if not (r["industry"] or {}).get("name")]
chk("缺行业归属的票行业分恰为 0",
    all(sc["by_code"][c]["ind"] == 0.0 for c in missing), True)

print("== C 行业榜 ==")
rows = (sc.get("sector") or {}).get("rows") or []
chk("行业榜非空", len(rows) >= 10, True)
chk("行业榜按热度分降序",
    [r["total"] for r in rows] == sorted((r["total"] for r in rows), reverse=True), True)
chk("分位取值 0~1",
    all(0 <= r["pct_rank"] <= 1 for r in rows), True)
chk("热点行业带标记", sum(1 for r in rows if r["hot"]) >= 1, True)
# 历史文件存在则逐日有值；首次运行可以没有
h = sector.load_hist()
if h:
    chk("行业历史逐条为数值", all(isinstance(v, (int, float))
                                  for d in list(h.values())[:3] for v in d.values()), True)
else:
    chk("行业历史尚无（首日运行允许，页面显示 — 不报错）", True, True)

print("== D 页面层 ==")
html_i = page_industry.render(data, meta, sc=sc)
for kw in ("行业热度榜", "双轮驱动", "只有行业", "只有概念", "口径说明", "申万行业"):
    chk("行业页含「%s」" % kw, kw in html_i, True)
chk("行业页带行业分位条", "涨幅分位" in html_i, True)
html_r = page_rank.render(data, meta)
chk("榜单页带行业列", "行业 /14" in html_r, True)
chk("榜单页带驱动列", "驱动" in html_r, True)
chk("榜单页双轮标签", "双轮" in html_r, True)
r1 = ranked[0]
html_s = page_stock.render(r1["code"], data["stocks"].get(r1["code"]), data, meta)
chk("个股页评分卡带行业行", "行业热度" in html_s, True)
chk("个股页带双轮共振行", "双轮共振" in html_s, True)
chk("个股页头部 /120", "/120" in html_s, True)
chk("个股页印原四维基准", "原四维" in html_s, True)
# 首页行业卡：直接调内部小表（page_home.render 参数多，不再整页跑一遍）
mini = page_home._sector_mini(sc)
chk("首页行业小表带行业名", bool(mini) and ("行业" in mini), True)

print("\n结论：%s（通过 %d 项，失败 %d 项）"
      % ("PASS" if FAIL == 0 else "FAIL", PASS, FAIL))
raise SystemExit(0 if FAIL == 0 else 1)
