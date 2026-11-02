# -*- coding: utf-8 -*-
"""P3 三页（/drivers /attr /brief）验收：数据层独立复算 + 页面断言。

独立复算的意思：炸板率、事件过滤、概念 TOP10 剔泛词这些逻辑，
这里用自己的公式重算一遍再和页面/数据对，实现抄实现是验不出错的。
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import date

sys.path.insert(0, ".")

import store  # noqa: E402
import reasons_core  # noqa: E402

BASE = "http://127.0.0.1:888"
PASS = FAIL = 0


def chk(name, got, want):
    global PASS, FAIL
    ok = got == want
    if isinstance(want, bool) or isinstance(got, bool):
        ok = bool(got) == bool(want)
    if ok:
        PASS += 1
        print("  ✓ %s" % name)
    else:
        FAIL += 1
        print("  ✗ %s\n        got %r\n        want %r" % (name, got, want))


def http(path):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    r = op.open(BASE + path, timeout=30)
    return r.read().decode("utf-8", "replace")


def main():
    at, am = store.load_attr()
    br, bm = store.load_brief()
    rd, rm = store.load_reasons()
    today = date.today().isoformat()

    print("== 数据层：归因池")
    chk("attr.json 存在且带 qdate", bool(at and re.fullmatch(r"\d{8}", at.get("qdate") or "")), True)
    q = at["qdate"]
    zt, zb = at["today"]["zt"], at["today"]["zb"]
    zt_y, zb_y = at["prev"]["zt"], at["prev"]["zb"]
    chk("今日涨停非空", len(zt) > 0, True)
    chk("昨日涨停非空（交易日回溯成功）", len(zt_y) > 0, True)
    chk("昨日日期 < 数据日", at["prev_date"] < q, True)
    gap = (date(int(q[:4]), int(q[4:6]), int(q[6:]))
           - date(int(at["prev_date"][:4]), int(at["prev_date"][4:6]), int(at["prev_date"][6:]))).days
    chk("昨日与今日差 ≤ 4 天（跳过周末）", 1 <= gap <= 4, True)
    rate = len(zb) / (len(zt) + len(zb)) * 100 if (zt or zb) else 0.0
    chk("区间涨幅键都在涨停池内",
        set(at["gains"]) <= {x["code"] for x in zt + zt_y}, True)
    chk("涨停池行的板数 ≥ 1", all(int(x["board"]) >= 1 for x in zt), True)
    chk("涨停池行的涨幅都在涨停附近（>9%）", all(float(x["pct"] or 0) > 9 for x in zt), True)

    print("== 数据层：简报")
    chk("brief.json 有最新篇", bool(br.get("latest")), True)
    # 篇目类型会变：行情稿一般 5-6 个指数，周末/展望稿只点到海外 3-4 个。
    chk("指数 ≥ 3 个", len(br.get("indices") or []) >= 3, True)
    evs = br.get("events") or []
    chk("事件日历无过期事件", all(e["date"] >= today for e in evs), True)
    chk("事件日历非空（该源的核心价值）", len(evs) > 0, True)
    chk("事件带出处（可回溯到篇目）", all(e.get("from") for e in evs), True)

    print("== 数据层：驱动词")
    ds = rd.get("drivers") or []
    chk("驱动词聚类非空", len(ds) > 0, True)
    chk("records 非空", len(rd.get("records") or []) > 0, True)
    chk("泛词被标记", any(d.get("generic") for d in ds), True)
    chk("聚类 score = 只数×权重 + 最高板×0.5",
        all(abs(d["score"] - (d["count"] * (0.35 if d["generic"] else 1.0)
                              + d["max_board"] * 0.5)) < 0.01 for d in ds), True)
    cov = rd.get("coverage") or {}
    chk("覆盖率 = 命中/池子",
        cov.get("rate") == round(cov.get("hit_same_day", 0) / max(cov.get("pool", 1), 1) * 100, 1),
        True)

    print("== 页面：/drivers")
    hd = http("/drivers")
    chk("三句话结论卡在页", "三句话结论" in hd, True)
    chk("广度/高度/暗线三行都在",
        all(k in hd for k in ("广度线", "高度线", "暗线")), True)
    chk("泛词标了降权", "泛词·降权" in hd, True)
    n_dark = sum(1 for d in ds if not d.get("generic")
                 and not d.get("in_sector_view") and d["count"] >= 2)
    chk("头部暗线计数与数据一致", ("暗线 %d 个" % n_dark) in hd, True)
    chk("逐股原因表非空", "逐股异动原因" in hd and "首句" in hd, True)
    chk("口径声明了不做热度环比", "不做热度环比" in hd, True)

    print("== 页面：/attr")
    ha = http("/attr")
    chk("KPI 今日涨停数与数据一致", (">%d<" % len(zt)) in ha, True)
    chk("KPI 今日炸板数与数据一致", (">%d<" % len(zb)) in ha, True)
    chk("炸板率与独立复算一致", ("%.1f" % rate) in ha, True)
    for t in ("今日涨停", "昨日涨停", "今日炸板", "盯盘打板"):
        chk("Tab 按钮含 %s" % t, t in ha, True)
    # 概念 TOP10 剔泛词：用同一份 drivers 的 generic 集合独立重算
    generic = {d["keyword"] for d in ds if d.get("generic")}
    kw_map = {r["code"]: [k for k in (r.get("keywords") or []) if k]
              for r in (rd.get("records") or [])}
    cnt = Counter()
    for it in zt:
        for w in set(kw_map.get(it["code"]) or []) - generic:
            cnt[w] += 1
    top1 = cnt.most_common(1)[0] if cnt else ("", 0)
    seg = ha.split("概念热度 TOP10")[1][:600]
    chk("概念 TOP10 第一名与复算一致（%s %d）" % top1,
        top1[0] in seg and ("<b>%d</b>" % top1[1]) in seg, True)
    chk("概念 TOP10 无泛词", not any(g in seg for g in
                                   ("三季报增长", "国企改革", "超跌反弹")), True)
    top_rng = sorted(at["gains"].items(), key=lambda t: -t[1])[:5]
    # 注意 all([]) 恒真：gains 为空时这里必须显式判 5 条，否则区间涨幅挂了也算过
    chk("区间最强 TOP5 恰好 5 条", len(top_rng), 5)
    chk("区间最强 TOP5 数值与数据一致",
        all(("+%.1f%%" % g) in ha for _, g in top_rng), True)
    chk("说明声明了题材分发已弃用", "4427" in ha, True)

    print("== 页面：/brief")
    hb = http("/brief")
    chk("指数卡数量与数据一致", hb.count('class="ix"') == len(br.get("indices") or {}), True)
    chk("事件行数与数据一致",
        hb.count('<span class="ev-day">') == len(evs), True)
    chk("事件无过期日期渲染",
        not re.search(r"ev-day\">(\d{4}-\d{2}-\d{2})", hb)
        or all(m >= today for m in re.findall(r"ev-day\">(\d{4}-\d{2}-\d{2})", hb)), True)
    chk("多空基调卡在页", "多空基调" in hb, True)
    chk("声明了 AI 生成属性", "AI 生成" in hb, True)

    print("== 导航")
    chk("六栏导航无建设中标记", hd.count("opacity:.55") == 0, True)

    print("\n%d 项通过，%d 项失败" % (PASS, FAIL))
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
