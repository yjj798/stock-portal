# -*- coding: utf-8 -*-
"""主线（消息面）验收：归并正确性、去重计分、页面四处落地。

背景：2026-11-02 用户令——"AI 短剧、AI 漫剧、AI 视频、出版传媒其实是同一条消息，
你分成十几个细支，概念就分散了；机床也不是通用设备，真正的行业是机器人。
归因能归到一条消息，才能判断这波还有多高。"

这里守三件事：
  A 归并层：同一条消息的细支必须落到同一条主线，成员是并集而不是各算各的
  B 去重层：一只票同一主线只计一次概念分（原来挂 5 个细支会累加 5 遍）
  C 落地层：/theme 主线页 + 首页 + 行业页 + 概念页 + 个股页四处都能看到这一层
"""
from __future__ import annotations

import store
import score as scoring
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
f10 = data.get("f10") or {}
cblocks = (data.get("concept_sector") or {}).get("blocks") or {}
sc = scoring.build(data)
rows = (sc.get("theme") or {}).get("rows") or []
by_id = {r["id"]: r for r in rows}

print("== A 归并层 ==")
chk("主线数量 = 定义条数（或更少）", len(rows) <= len(theme.THEMES), True)
chk("主线覆盖 ≥ 80% 的池内票",
    sum(1 for v in sc["by_code"].values() if (v.get("theme") or {}).get("ids"))
    / max(len(stocks), 1) >= 0.8, True)

# AI 视频：必须把短剧/漫剧/影视/出版类细支并进来，且成员 > 任一细支
av = by_id.get("ai_video")
chk("存在「AI 视频」主线", bool(av), True)
if av:
    tags = [t["tag"] for t in av["tags"]]
    chk("AI 视频并入了短剧类细支", any("短剧" in t for t in tags), True)
    chk("AI 视频并入了漫剧类细支", any("漫剧" in t for t in tags), True)
    chk("AI 视频并入了视频/影视类细支",
        any(("视频" in t or "影视" in t or "传媒" in t or "出版" in t) for t in tags), True)
    chk("AI 视频细支 ≥ 8 个（并集前是散的）", len(tags) >= 8, True)
    chk("AI 视频成员多于最大细支",
        av["n"] > max(t["n"] for t in av["tags"]), True)
    chk("AI 视频有成员", av["n"] >= 10, True)

# 机器人：机床类必须能进来（用户点名的沈阳机床）
rb = by_id.get("robot")
chk("存在「机器人」主线", bool(rb), True)
if rb:
    inds = [i["name"] for i in rb.get("industries") or []]
    machine = [c for c in rb["codes"]
               if ((sc["by_code"].get(c) or {}).get("theme") or {}).get("finest") == "机床工具"]
    chk("机器人主线含机床工具行业的票", len(machine) >= 1, True)
    chk("机器人主线的产业链归属票 ≥ 1", len(rb.get("chain_codes") or []) >= 1, True)
    finest = [((sc["by_code"].get(c) or {}).get("theme") or {}).get("finest")
              for c in rb["codes"]]
    chk("机器人主线成员的行业链最细级里有「机床工具」", "机床工具" in finest, True)

# 生肖谐音是"叠加属性"，不抢主归属，成员应等于概念层羊字辈的全部（21 只前后）
z = by_id.get("zodiac")
if z:
    chk("生肖谐音成员 = 计分成员（可叠加）", z["n_scored"], z["n"])
    chk("生肖谐音成员 ≥10 只（含同音补入）", z["n"] >= 10, True)

print("== B 去重层 ==")
dup, mismatch = [], []
for c, r in sc["by_code"].items():
    ts = r.get("theme_tags") or []
    if len(set(ts)) != len(ts):
        dup.append(c)
    ids = set((r.get("theme") or {}).get("ids") or [])
    names = {theme.BY_ID[i]["name"] for i in ids if i in theme.BY_ID}
    if sum(1 for t in ts if t in names) != len(names):
        mismatch.append(c)
chk("归并后标签无重复", dup[:5], [])
chk("每条命中主线在标签里恰好一个合成标签", mismatch[:5], [])
chk("theme_tags 非空且不少于命中主线数",
    all(len(v.get("theme_tags") or []) >= len((v.get("theme") or {}).get("ids") or [])
        for v in sc["by_code"].values()), True)
chk("主线 id 全部来自定义表",
    all(r["id"] in theme.BY_ID for r in rows), True)
chk("每票 main 属于它的 ids",
    all((not (v.get("theme") or {}).get("main"))
        or (v["theme"]["main"] in (v["theme"].get("ids") or []))
        for v in sc["by_code"].values()), True)
chk("主线分在 0~100 之间", all(0 <= r["total"] <= 100 for r in rows), True)
chk("主线按分降序",
    all(rows[i]["total"] >= rows[i + 1]["total"] for i in range(len(rows) - 1)), True)
chk("核心成员是成员子集",
    all(set(r["core_codes"]) <= set(r["codes"]) for r in rows), True)
chk("「人工智能」这类底色词不计概念分", "人工智能" in scoring.WIDE, True)

print("== C 落地层 ==")
from render import page_concept, page_home, page_industry, page_stock, page_theme  # noqa: E402

html_t = page_theme.render(data, meta, sc)
for kw in ("今天在炒哪条消息", "主线热度榜", "消息面", "证据链", "核心",
           "并成一条主线", "产业链归属"):
    chk("主线页含「%s」" % kw, kw in html_t, True)
chk("主线页列出全部主线", all(r["name"] in html_t for r in rows), True)

chk("首页有主线小表（_theme_mini 出表）",
    "主线（消息面）" in page_home._theme_mini(sc), True)

html_i = page_industry.render(data, meta, sc=sc)
chk("行业页有「归因主线」列", "归因主线" in html_i, True)

html_c = page_concept.render(data, meta)
chk("概念页有「归入主线」列", "归入主线" in html_c, True)

any_code = next((c for c in stocks if ((sc["by_code"].get(c) or {}).get("theme") or {}).get("main")), None)
if any_code:
    html_s = page_stock.render(any_code, stocks[any_code], data, meta)
    chk("个股页有「归因主线」卡", "归因主线" in html_s, True)

from render.nav import TABS  # noqa: E402
paths = [t[0] for t in TABS]
chk("导航有 /theme", "/theme" in paths, True)
chk("主线排在行业与概念之前",
    paths.index("/theme") < paths.index("/industry")
    and paths.index("/theme") < paths.index("/concept"), True)

print("\n主线 %d 条 · 强 %d 条" % (len(rows), sum(1 for r in rows if r.get("hot"))))
for r in rows:
    print("  %-8s %5.1f %s 计分%2d/关联%2d 涨停%2d %d板 龙%s"
          % (r["name"], r["total"], r.get("tier"), r["n_scored"], r["n"],
             r["lu"], r["max_board"], r["best_name"]))
print("\nPASS %d · FAIL %d" % (PASS, FAIL))
raise SystemExit(0 if not FAIL else 1)
