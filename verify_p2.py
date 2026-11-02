# -*- coding: utf-8 -*-
"""P2 验收：三张榜 + 个股页 + 搜索，逐项与"源"对拍。

对拍思路
--------
不拿"我自己刚写的 bundle"跟"我刚抓的源"比——那样只要解析错一次就两边一起错。
这里做两件事：
  1. **bundle vs 源重抓**：确认归一化没丢字段、没改数值。
  2. **页面 HTML vs bundle**：确认渲染层真的把数字印出来了（而不是空表格）。

判据（项目书第八节）：
  A 综合分 TOP10 的 code 序列与线上一致
  B tdx 榜的 rank / price / turnover / limit_up_reason 与线上一致
  C 任选 3 只票的 price / pct / board / score_final / heat 与各源一致
  D 中文名与代码双向搜得到

用法：python verify_p2.py
"""
from __future__ import annotations

import re
import sys
import urllib.parse
import urllib.request

import store
from fetchers import base, renqi, spot, tdx_rank

PORT = 888
OK, BAD = 0, 0


def chk(label, got, want, note=""):
    global OK, BAD
    if got == want:
        OK += 1
        print("  ✓ %-46s %s" % (label, _s(got)))
    else:
        BAD += 1
        print("  ✗ %-46s 期望 %s 实际 %s %s" % (label, _s(want), _s(got), note))


def _s(v):
    s = str(v)
    return s if len(s) <= 40 else s[:37] + "..."


def http(path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=10) as r:
        return r.read().decode("utf-8", "replace")


def main():
    data, meta = store.load_bundle()
    if not data:
        print("没有 bundle，先跑 python refresh.py")
        return 1
    print("bundle：行情日 %s　个股 %d　概念 %d　tdx %d　热榜 %d　刷新于 %s"
          % (data.get("quote_date"), len(data.get("stocks") or {}),
             len(data.get("concept_stats") or []), len(data.get("tdx_top") or []),
             len(data.get("hot_hour") or []), meta.get("fetched_at")))

    # ---------------------------------------------------------- A 综合分 TOP10
    print("\n== A 综合分 TOP10 序列 ==")
    fresh_rq = renqi.fetch(save=False)
    # 综合分 TOP10 = leaderboard（10 条，score_final 严格递减）。
    # lists.composite 只有 5 条，是"涨停且高分"的子集，不是这张榜——别搞混。
    want = [base.code6(x.get("code")) for x in fresh_rq.get("leaderboard") or []]
    got = [base.code6(x.get("code")) for x in data.get("leaderboard") or []]
    chk("leaderboard code 序列", got, want)
    chk("张数", len(got), 10)
    scores = [float(x.get("score_final") or 0) for x in (data.get("leaderboard") or [])]
    chk("按 score_final 降序", scores == sorted(scores, reverse=True), True)
    # 页面真的印出来了吗：第一张表的链接顺序应与 leaderboard 完全一致
    html_rank = http("/rank")
    # 2026-11-02：综合分榜已改成本机四维模型（score.py），不再按 leaderboard 排序，
    # 所以这里只校验"人气榜那张表"的 tdx 顺序，TOP 表的断言挪到 verify_score.py。
    chk("榜单页含综合分 TOP12", "综合分 TOP12" in html_rank, True)
    # 2026-11-02 起标题就是「人气榜」三个字（用户令：去掉后面的计数说明），
    # 计数挪进了标题右侧的 <span>。
    chk("榜单页含人气榜一张表", "人气榜" in html_rank and "一张表" not in html_rank.split("人气榜", 1)[1][:200], True)

    # ---------------------------------------------------------- B tdx 榜
    print("\n== B tdx 榜字段 ==")
    fresh_tdx, _note = tdx_rank.fetch_top()
    got_tdx = data.get("tdx_top") or []
    chk("条目数", len(got_tdx), len(fresh_tdx))
    byc = {base.code6(x.get("code")): x for x in got_tdx}
    bad = 0
    checked = 0
    for x in fresh_tdx:
        c = base.code6(x.get("code"))
        g = byc.get(c)
        if not g:
            bad += 1
            continue
        checked += 1
        for k in ("rank", "current_rank", "price", "turnover", "limit_up_reason", "consecutive_boards"):
            if g.get(k) != x.get(k):
                bad += 1
                print("     字段不符 %s.%s: bundle=%r 源=%r" % (c, k, g.get(k), x.get(k)))
    chk("逐条字段一致（%d 条 × 6 字段）" % checked, bad, 0)

    # ---------------------------------------------------------- C 三只个股
    print("\n== C 个股字段（bundle vs 源） ==")
    rq_map = renqi.stock_map(fresh_rq)
    tdx_map = tdx_rank.stock_map({"top": fresh_tdx, "history": {}})
    # 价格/涨幅的真值＝实时行情（data/live/spot.json）；人气榜是收盘后源，
    # 盘中的 price/pct 还停在上一个交易日，拿它当基准等于用旧数据验收新页面。
    try:
        sp_map = spot.load()[0] or {}      # base.load 返回 (data, meta)
    except Exception:  # noqa: BLE001
        sp_map = {}
    for c in ("002172", "002086", "600721"):
        e = (data.get("stocks") or {}).get(c) or {}
        s = rq_map.get(c) or {}
        t = tdx_map.get(c) or {}
        sp = sp_map.get(c) or {}
        chk("%s 名称" % c, e.get("name"), s.get("name") or t.get("name"))
        chk("%s 价格" % c, e.get("price"),
            sp.get("price") if sp.get("price") is not None
            else (s.get("price") if s.get("price") is not None else t.get("price")))
        chk("%s 涨幅" % c, e.get("pct"),
            sp.get("pct") if sp.get("pct") is not None
            else (s.get("chg") if s.get("chg") is not None else t.get("change_pct")))
        chk("%s 连板标签" % c, e.get("board_tag"), s.get("board_tag"))
        chk("%s score_final" % c, e.get("score"), s.get("score_final"))
        chk("%s ths_heat" % c, e.get("ths_heat"), s.get("ths_heat"))
        chk("%s 涨停原因(取自tdx)" % c, e.get("limit_up_reason"), t.get("limit_up_reason"))

    # ---------------------------------------------------------- D 搜索 + 页面
    print("\n== D 搜索与页面 ==")
    for q, want_code in (("002172", "002172"), ("澳洋健康", "002172"), ("澳洋", "002172")):
        h = http("/rank?q=" + urllib.parse.quote(q))
        hit = ('href="/s/%s"' % want_code) in h
        chk("搜「%s」命中 /s/%s" % (q, want_code), hit, True)

    print("\n== 页面可访问性 ==")
    for p in ("/rank", "/rank?hot=day", "/concept", "/concept?c=" + urllib.parse.quote("机器人概念"),
              "/s/002172", "/s/999999"):
        h = http(p)
        chk("%-28s 200 且非空" % p, len(h) > 2000, True)

    print("\n== 个股页数字落地 ==")
    h = http("/s/002172")
    e = (data.get("stocks") or {})["002172"]
    for label, needle in (("价格 ¥%.2f" % float(e["price"]), "¥%.2f" % float(e["price"])),
                          ("综合分 %s" % _s(e["score"]), _t(e["score"])),
                          ("概念串 脑机接口", "脑机接口"),
                          ("涨停原因", "国资控股")):
        chk(label, needle in h, True)
    chk("含排名轨迹图", "<svg" in h, True)
    chk("含评分拆解", "评分拆解" in h, True)

    # ---------------------------------------------------------- E 上榜原因
    print("\n== E 上榜原因（逐股异动 reason） ==")
    ab = (data.get("abnormal") or {})
    chk("bundle 里上榜原因条数>0", len(ab) > 0, True)
    n_today = sum(1 for v in ab.values() if v.get("date") == data.get("quote_date"))
    print("  当日 %d / 总 %d（其余为历史异动，页面按新旧分档）" % (n_today, len(ab)))
    chk("002172 含上榜原因卡片", "上榜原因" in h, True)
    chk("002172 含行业原因", "行业原因" in h, True)
    chk("002172 含公司原因", "公司原因" in h, True)
    # 原文每天在变，不能把某一天的人名钉死在断言里；从当日原文取一段核对是否真渲染出来
    _frag = next((seg.strip()[:12] for seg in
                  ((ab.get("002172") or {}).get("reason") or "").split("\n")
                  if len(seg.strip()) > 12), "")
    chk("002172 原文片段落地（%s）" % (_frag or "空原文"), bool(_frag) and _frag in h, True)
    chk("旧文案（概念龙头提示句）已移除",
        "概念榜里它的人气名次最靠前" not in h, True)
    # 非当日：有旧记录的票要明确标注，不能冒充当日原因
    old = [c for c, v in ab.items()
           if v.get("date") and v["date"] < str(data.get("quote_date") or "" )
           and _gap_days(v["date"], data.get("quote_date")) is not None
           and _gap_days(v["date"], data.get("quote_date")) > 7]
    if old:
        ho = http("/s/" + old[0])
        chk("%s（%s）标注非当日" % (old[0], ab[old[0]]["date"]),
            "不作为当日上榜原因" in ho, True)
    # 近 7 天非当日：展示正文但带"最近一次异动"提示
    near = [c for c, v in ab.items()
            if v.get("date") and v["date"] < str(data.get("quote_date") or "")
            and (_gap_days(v["date"], data.get("quote_date")) or 0) in range(1, 8)]
    if near:
        hn = http("/s/" + near[0])
        chk("%s（%s）带最近一次异动提示" % (near[0], ab[near[0]]["date"]),
            "最近一次异动" in hn, True)

    print("\n结论：%s（通过 %d 项，失败 %d 项）"
          % ("PASS" if BAD == 0 else "FAIL", OK, BAD))
    return 0 if BAD == 0 else 1


def _t(v):
    s = "%.1f" % float(v)
    return s[:-2] if s.endswith(".0") else s


def _gap_days(a, b):
    from datetime import date
    try:
        y1, m1, d1 = [int(x) for x in str(a).split("-")[:3]]
        y2, m2, d2 = [int(x) for x in str(b).split("-")[:3]]
        return (date(y2, m2, d2) - date(y1, m1, d1)).days
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
