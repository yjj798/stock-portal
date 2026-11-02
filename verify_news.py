# -*- coding: utf-8 -*-
"""消息面（news）验收：异动解析覆盖、关键词计数、主线实况、四处落地。

背景：2026-11-02 用户令——「你应该从所有涨停股里去读它相关的这个异动解析，
每只涨停股、龙虎榜里出现的股票、同花顺排行 100 里出现的股票都去看一下它这种
链接里的消息」。

所以这一层必须守住四件事：
  A 覆盖：不能只读人气池（141 只），要读「池 ∪ 全市场涨停 ∪ 今日龙虎榜 ∪ 热榜 100」
  B 计数：关键词「挂几只 / 其中几只涨停」能逐个复算出来，没有拍脑袋的数
  C 归并：同一个消息的多个词（AI短剧 / AI漫剧 / 微短剧 / AI影视）要落到同一条主线，
          并且两处「核心 N 只」必须是同一个定义
  D 落地：/theme 有关键词榜与实况原文，个股页关键词带共享只数，池外涨停有轻量页
"""
from __future__ import annotations

import re

import news
import score as scoring
import store
import theme

PASS, FAIL = 0, 0


def chk(name, got, want):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print("  %s %s%s" % ("✓" if ok else "✗", name,
                         "" if ok else "　期望 %r 实际 %r" % (want, got)))


data, meta = store.load_bundle()
stocks = data.get("stocks") or {}
abn = data.get("abnormal") or {}
zt_pool = data.get("zt_pool") or []
sc = scoring.build(data)
main_of = (sc.get("theme") or {}).get("main_of") or {}
nw = news.build(data, main_of=main_of)
kws = nw.get("keywords") or []
nm = nw.get("meta") or {}

print("== A 覆盖：不是只读人气池 ==")
chk("异动解析条数 > 人气池只数", len(abn) > len(stocks), True)
chk("异动解析至少覆盖 1.5 倍人气池", len(abn) >= int(len(stocks) * 1.5), True)
zt_codes = {str(x.get("code")) for x in zt_pool}
hit = sum(1 for c in zt_codes if c in abn)
chk("涨停池里 ≥90%% 有异动解析（%d/%d）" % (hit, len(zt_codes)),
    hit >= int(len(zt_codes) * 0.9), True)
chk("有涨停池字段（zt_pool）", len(zt_pool) > 0, True)
chk("每条异动解析都有 date 与 keywords",
    all(v.get("date") and isinstance(v.get("keywords"), list) for v in abn.values()), True)

print("\n== B 关键词计数可复算 ==")
chk("关键词榜非空", len(kws) > 20, True)
chk("关键词榜按「涨停数 → 只数」降序",
    all((a["n_zt"], a["n"]) >= (b["n_zt"], b["n"]) for a, b in zip(kws, kws[1:])), True)
bad = []
for r in kws[:30]:
    cs = {c for c, v in abn.items()
          if r["kw"] in [news.norm_kw(k) for k in (v.get("keywords") or [])]}
    if cs != set(r["codes"]):
        bad.append((r["kw"], len(cs), len(r["codes"])))
chk("前 30 个词逐个复算成员一致", bad, [])
chk("涨停数 ≤ 总只数",
    all(r["n_zt"] <= r["n"] for r in kws), True)
chk("噪声词不进榜（此前涨幅较大/超跌反弹/板块下跌）",
    [r["kw"] for r in kws if news.is_noise(r["kw"])], [])
chk("带引号的「“羊”字辈」被归一成「羊字辈」",
    any(r["kw"] == "羊字辈" for r in kws), True)

print("\n== C 归并：一条消息一个核心 ==")
tid = "ai_video"
rows = (sc.get("theme") or {}).get("rows") or []
row = next((r for r in rows if r["id"] == tid), None)
chk("AI 视频主线存在", row is not None, True)
if row:
    # 同一消息的细支词必须都落在这一条线上
    same = [r["kw"] for r in kws if r.get("theme") == tid]
    for w in ("AI短剧", "AI漫剧", "微短剧", "AI影视"):
        chk("「%s」归到 AI 视频" % w, w in same or w not in [x["kw"] for x in kws], True)
    v = (nw.get("themes") or {}).get(tid) or {}
    chk("实况核心数与主线核心数一致（%d vs %d）" % (v.get("n_core"), row.get("n_core")),
        v.get("n_core"), row.get("n_core"))
    chk("实况有行业原因原文", len(v.get("quote") or "") >= 8, True)
    # 原文必须真的来自某只成员的异动解析，不能是编的
    texts = set()
    for c in v.get("core") or []:
        one = news.split_reason((abn.get(c) or {}).get("reason"))[0]
        if one:
            texts.add(one)
    chk("行业原因原文可在成员解析里找到", v.get("quote") in texts, True)
    chk("主线成员数 ≥ 核心数", (row.get("n") or 0) >= (row.get("n_core") or 0), True)

print("\n== D 页面落地 ==")
from render import page_stock, page_theme  # noqa: E402

h = page_theme.render(data, meta, sc)
chk("主线页有关键词榜", "今日关键词" in h, True)
chk("关键词榜印出「挂几只 / 涨停」", "挂 · 涨停" in h, True)
chk("主线卡有实况关键词", h.count("实况关键词") >= 1, True)
chk("主线卡有行业原因原文", "行业原因原文" in h, True)
chk("主线卡有最典型个股的公司原因", "公司原因" in h, True)
chk("口径说明写明并集范围",
    ("人气池 ∪ 全市场涨停" in h) or ("人气池 ∪ 全市场涨停 ∪ 今日龙虎榜" in h), True)
n_link = len(set(re.findall(r'href="/s/(\d{6})"', h)))
chk("主线页链到 ≥ 20 只个股", n_link >= 20, True)

# 个股页：关键词带共享只数
pool_code = sorted(stocks)[0]
hs = page_stock.render(pool_code, stocks[pool_code], data, meta)
chk("个股页关键词带「N 只 · 涨停 M」", "只 · 涨停" in hs, True)
chk("个股页链到关键词榜", "看今日关键词榜" in hs, True)

# 池外涨停：轻量页必须有内容，不能是「没这只票的数据」
outside = [c for c in zt_codes if c not in stocks]
if outside:
    c0 = sorted(outside)[0]
    e0 = page_stock.entry_of(c0, data)
    chk("池外涨停能取到轻量记录", bool(e0 and e0.get("_partial")), True)
    ho = page_stock.render(c0, e0, data, meta)
    chk("池外涨停页有异动解析正文", "行业原因" in ho or "公司原因" in ho, True)
    chk("池外涨停页写清「为什么没有评分」", "为什么这页没有评分" in ho, True)
    chk("池外涨停页不出现「没这只票的数据」", "没这只票的数据" in ho, False)
else:
    chk("今日存在池外涨停（数据异常）", False, True)

print("\n== E 降级不崩 ==")
empty = news.build({})
chk("空数据不抛异常且返回空表", (empty.get("keywords"), empty.get("meta", {}).get("n_kw")), ([], 0))
noab = news.build(data, abn={})
chk("无异动解析时关键词榜为空", noab.get("keywords"), [])

print("\nPASS %d · FAIL %d" % (PASS, FAIL))
