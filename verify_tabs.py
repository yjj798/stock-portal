# -*- coding: utf-8 -*-
"""分栏（tab）验收：首页 4 栏、榜单 2 栏，切栏不丢模块、不重复渲染、后退能回上栏。

为什么单独一个脚本：分栏是「纯版式」改动，数字全对也可能把某一栏放错地方、
或者同一个模块被复制进两栏（页面看不出，但字数会翻倍、口径会漂）。
所以这里不比对线上数值，只锁四件版式契约：

  1. 栏目集合与默认栏 —— 首页 mood/pool/struct/flow，榜单 score/hot，默认第一栏；
     非法 ?t= 必须回退第一栏而不是白屏（收藏夹里可能留着旧值）。
  2. 模块归属 —— 11 个复盘模块必须**各出现一次**，且主题不同栏不重复。
  3. 无 JS 也能用 —— 每个 tab 是真实 href（?t=key），历史快照页的 href 要带 /snapshot/<日期>，
     否则点一下就被送回最新一天。
  4. 分栏底座在位 —— CSS 的 .tp/.tp.on 规则、脚本的 pushState/popstate。

跑法：python verify_tabs.py    （需要 :888 在跑；不需要联网）
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 888
OK = FAIL = 0

HOME_KEYS = ["mood", "pool", "struct", "flow"]
RANK_KEYS = ["score", "hot"]
# 复盘页现有模块（与 verify_p1 的 need 列表一致），漏一个就是"拆栏时丢了内容"
HOME_MODULES = ["当日结论", "情绪分项", "市场广度", "今日观察池", "涨停梯队",
                "热门板块", "精选板块", "下一交易日题材前瞻", "龙虎榜",
                "涨停驱动词", "历史轨迹"]


def chk(name, got, want=True):
    global OK, FAIL
    good = got == want
    OK, FAIL = OK + good, FAIL + (not good)
    print("  %s %s%s" % ("✓" if good else "✗", name,
                         "" if good else "%s期望 %r 实际 %r "
                         % (" " * max(1, 30 - len(name)), want, got)))


def http(path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=20) as r:
        return r.read().decode("utf-8", "ignore")


def panes(html):
    """→ [(key, 是否显示, 面板 html)]。面板由 <section class="tp[ on]" data-k=...> 包裹。"""
    out = []
    for m in re.finditer(r'<section class="(tp[^"]*)" data-k="(\w+)">(.*?)</section>',
                         html, re.S):
        out.append((m.group(2), "on" in m.group(1).split(), m.group(3)))
    return out


def bar_links(html):
    """→ [(key, href, 是否高亮)]，只取分栏标题栏里的链接。"""
    m = re.search(r'<div class="tabs2">(.*?)</div>', html, re.S)
    if not m:
        return []
    return [(a.group(1), a.group(2), 'class="on"' in a.group(0))
            for a in re.finditer(r'<a([^>]*)href="([^"]*)"[^>]*>', m.group(1))]


def main():
    print("== A 首页四栏 ==")
    h = http("/board")   # 总览已从 / 迁到 /board
    ps = panes(h)
    chk("栏目数 = 4", len(ps), 4)
    chk("栏目顺序", [k for k, _, _ in ps], HOME_KEYS)
    chk("默认显示且只显示 mood", [k for k, on, _ in ps if on], ["mood"])
    chk("每栏都有内容（≥1 张卡）", all(x[2].count('<div class="card"') >= 1 for x in ps), True)

    print("\n== B 首页 11 个模块各出现一次 ==")
    for name in HOME_MODULES:
        n = h.count("<h2>%s" % name)
        chk("%-12s 出现 1 次" % name, n, 1)
    # 归属：拆栏不能把同一张卡塞进两栏（那样 count 会变 2，上面已拦），
    # 但还要防"A 栏的卡跑到 B 栏"——这里按语义点几个关键归属。
    by = {k: v for k, _, v in ps}
    chk("当日结论在情绪总览", "当日结论" in by.get("mood", ""), True)
    chk("观察池独占一栏", "今日观察池" in by.get("pool", "")
        and "今日观察池" not in by.get("mood", ""), True)
    chk("涨停梯队/驱动词在涨停结构", "涨停梯队" in by.get("struct", "")
        and "涨停驱动词" in by.get("struct", ""), True)
    chk("题材前瞻/龙虎榜在题材资金", "下一交易日题材前瞻" in by.get("flow", "")
        and "龙虎榜" in by.get("flow", ""), True)

    print("\n== C 切换与兜底 ==")
    for key in ("pool", "struct", "flow"):
        p = panes(http("/board?t=" + key))
        chk("?t=%s 只亮该栏" % key, [k for k, on, _ in p if on], [key])
    chk("非法 ?t= 回退第一栏",
        [k for k, on, _ in panes(http("/board?t=zzz")) if on], ["mood"])
    chk("无参默认第一栏", [k for k, on, _ in panes(http("/board")) if on], ["mood"])
    # 所有面板始终在 HTML 里：切栏是显隐，不是按需渲染（否则搜索/爬虫/打印会缺内容）
    chk("切栏不改变 HTML 体积", len(http("/board?t=flow")), len(h))

    print("\n== D 真实 href（无 JS 可用）==")
    links = bar_links(h)
    chk("首页 4 个 tab 都有 href", [x[1] for x in links],
        ["/board?t=%s" % k for k in HOME_KEYS])
    chk("默认高亮第一个", [x[2] for x in links], [True, False, False, False])
    snap = [x for x in os.listdir(os.path.join(HERE, "data", "snapshots"))
            if x.endswith(".json")]
    if snap:
        d = snap[-1].replace(".json", "")
        hs = http("/snapshot/%s?t=struct" % d)
        chk("快照页 href 带 /snapshot/%s" % d,
            [x[1] for x in bar_links(hs)], ["/snapshot/%s?t=%s" % (d, k) for k in HOME_KEYS])
        chk("快照页也能切栏", [k for k, on, _ in panes(hs) if on], ["struct"])

    print("\n== E 榜单页两栏 ==")
    r = http("/rank")
    rp = panes(r)
    chk("栏目数 = 2", len(rp), 2)
    chk("栏目顺序", [k for k, _, _ in rp], RANK_KEYS)
    chk("默认四维综合榜", [k for k, on, _ in rp if on], ["score"])
    rb = {k: v for k, _, v in rp}
    chk("综合分表在第一栏", "综合分 TOP12" in rb.get("score", ""), True)
    chk("人气榜在第二栏", "<h2>人气榜<" in rb.get("hot", ""), True)
    chk("两栏不串（综合榜栏无人气榜卡、人气榜栏无综合分表）",
        ("<h2>人气榜<" in rb.get("score", ""),
         "综合分 TOP12" in rb.get("hot", "")), (False, False))
    chk("?t=hot 只亮人气榜",
        [k for k, on, _ in panes(http("/rank?t=hot")) if on], ["hot"])
    chk("小时/日切换保留 tab",
        'href="/rank?t=hot&amp;hot=day"' in r, True)
    chk("搜索表单保留 tab", '<input type="hidden" name="t" value=' in r, True)

    print("\n== F 分栏底座 ==")
    chk("CSS 隐藏非活动栏", ".tp{display:none}" in r, True)
    chk("CSS 显示活动栏", ".tp.on{display:block}" in r, True)
    chk("脚本含 pushState", "history.pushState" in r, True)
    chk("脚本含 popstate", 'addEventListener(\'popstate\'' in r, True)
    chk("脚本在页尾（DOM 已就绪）", r.rstrip().endswith("</script></body></html>"), True)

    print("\n结论：%s（通过 %d 项，失败 %d 项）"
          % ("PASS" if FAIL == 0 else "FAIL", OK, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
