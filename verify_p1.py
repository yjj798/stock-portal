# -*- coding: utf-8 -*-
"""P1 验收：本地 :888 复盘页 vs 线上 d.legaga.top 逐模块对拍。

用法：
    python verify_p1.py                     # 抓线上再比（需代理 7890）
    python verify_p1.py --live _cmp/live.html   # 用已存好的线上页比
    python verify_p1.py --local-only        # 只看本地有没有模块缺失

判读原则：只比"能对着人眼核对的量"（温度、广度、梯队、榜单行数、名单与分数），
不比整页字符串——本地多了「驱动词」模块和本地专属导航，字节数天然不同。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

import urllib.request

LIVE = "https://d.legaga.top/"
LOCAL = "http://127.0.0.1:888/"
PROXY = "http://127.0.0.1:7890"
HERE = os.path.dirname(os.path.abspath(__file__))


def fetch(url, proxy=None):
    if proxy:
        out = subprocess.run(
            ["curl", "-s", "--max-time", "30", "-x", proxy, "-H", "User-Agent: Mozilla/5.0", url],
            capture_output=True)
        return out.stdout.decode("utf-8", "ignore")
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read().decode("utf-8", "ignore")


def grab(s):
    d = {}
    m = re.search(r'class="tnum"[^>]*>([^<]+)<', s)
    d["温度"] = m.group(1).strip() if m else "?"
    m = re.search(r'class="tlevel"[^>]*>([^<]+)<', s)
    d["档位"] = m.group(1).strip() if m else "?"
    d["分项"] = [x.strip() for x in re.findall(r'class="bval">([^<]+)<', s)]
    d["广度"] = re.findall(
        r'<div class="cell"><div class="k">([^<]+)</div><div class="v[^"]*">(.*?)</div>'
        r'<div class="n">([^<]+)</div>', s)[:4]
    d["梯队"] = re.findall(r'(?:<b>(\d+) 板</b>|<span class="bs \w+">(\d+) 板</span>)</td><td>(\d+) 只', s)
    d["梯队"] = [tuple(x for x in t if x) for t in d["梯队"]]
    d["板块行"] = len(re.findall(
        r'<tr><td class="l">(?:\d+\. |<span class="bs \w+">\d+</span> )', s))
    d["精选行"] = len(re.findall(r"<td class=\"\w+\">([+-]?\d+\.?\d*)%</td><td>", s))
    d["观察池"] = re.findall(r'class="pk-n">([^<]+)<', s)
    d["分数"] = re.findall(r'class="pk-s"[^>]*>(\d+)<', s)
    # 卡片块级解析：A/B/C 卡都带 tier 左边框类（pk a/b/c）。
    # 「榜单通道」卡是本地有意加的（picks.CH_SCORE），对拍时要从名单里剔掉。
    d["cards"] = []
    for blk in re.split(r'<div class="pk [abc]">', s)[1:]:
        m = re.search(r'class="pk-n">([^<]+)<', blk)
        n = re.search(r'class="pk-s"[^>]*>(\d+)<', blk)
        if m:
            d["cards"].append((m.group(1), n.group(1) if n else "",
                               "榜单通道" in blk))
    d["叙事"] = re.findall(r'class="nar-t">([^<]+)<', s)
    d["龙虎行"] = len(re.findall(r'<tr><td class="l">[^<]+</td><td class="(?:red|green)">'
                                r'[+-][\d.]+%</td><td>', s))
    d["题材"] = len(re.findall(r'<div class="theme"><div class="t1">\d+\. ', s))
    m = re.search(r"<title>([^<]+)</title>", s)
    d["标题"] = m.group(1) if m else "?"
    return d


def numonly(v):
    """从 <span class="red">893</span> / 893 / +1.44% 里取数，便于跨版本比较。"""
    m = re.search(r"-?[\d.]+", re.sub(r"<[^>]+>", "", str(v)))
    return m.group(0) if m else str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live")
    ap.add_argument("--local-only", action="store_true")
    a = ap.parse_args()

    loc = grab(fetch(LOCAL))
    print("== 本地模块自检 ==")
    need = ["当日结论", "情绪分项", "市场广度", "今日观察池", "涨停梯队",
            "热门板块", "精选板块", "题材前瞻", "龙虎榜", "涨停驱动词", "历史轨迹"]
    html = fetch(LOCAL)
    miss = [k for k in need if k not in html]
    print("  模块 %d/%d 在位%s" % (len(need) - len(miss), len(need),
                                  "" if not miss else "，缺：" + "、".join(miss)))
    print("  温度 %s（%s）  叙事 %d 条：%s" % (loc["温度"], loc["档位"],
                                              len(loc["叙事"]), "、".join(loc["叙事"])))
    print("  梯队 %s" % (loc["梯队"],))
    print("  观察池 %d 只，分数 %s" % (len(loc["观察池"]), loc["分数"]))
    if a.local_only:
        return 0 if not miss else 1

    live_html = open(a.live, encoding="utf-8", errors="ignore").read() if a.live \
        else fetch(LIVE, PROXY)
    liv = grab(live_html)

    print("\n== 与线上对拍 ==")
    bad = 0

    def cmp(key, lv, ov, note=""):
        nonlocal bad
        ok = lv == ov
        if not ok:
            bad += 1
        print("  %-6s %s  线上=%s  本地=%s %s"
              % (key, "OK  " if ok else "DIFF", lv, ov, note))

    cmp("标题", liv["标题"], loc["标题"])
    cmp("温度", liv["温度"], loc["温度"])
    cmp("档位", liv["档位"], loc["档位"])
    cmp("分项", [numonly(x) for x in liv["分项"]], [numonly(x) for x in loc["分项"]])
    cmp("梯队", liv["梯队"], loc["梯队"])
    cmp("板块行", liv["板块行"], loc["板块行"])
    cmp("题材", liv["题材"], loc["题材"])
    # 「榜单通道」卡（四维分 ≥75 且趋势 ≥30）是本地有意加的，对拍前剔除；
    # 剔除后名单与分数应与线上完全一致——这样改 A 档规则时线上仍能当基准。
    chan = [c[0] for c in loc["cards"] if c[2]]
    loc_cards = [c for c in loc["cards"] if not c[2]]
    print("  %-6s      本地榜单通道：%s（对拍时剔除）"
          % ("通道", "、".join(chan) or "无"))
    # 榜单通道的票本来在线上 B 档里，剔除后两边名单才可比。
    # 2026-11-02 起本地排序改用「推荐序」（综合分 55% + 共振分 45%），
    # 与线上按共振分排的顺序必然不同 —— 所以名单比**集合**，序号差异只做提示，
    # 仍按名字逐只比共振分（±1），那才是真正需要锁死的口径。
    ln = [n for n in liv["观察池"] if n not in chan]
    on = [c[0] for c in loc_cards]
    same_set = sorted(ln) == sorted(on)
    print("  %-6s %s  线上 %d 只 / 本地 %d 只%s"
          % ("名单", "OK  " if same_set else "DIFF", len(ln), len(on),
             "" if same_set else "　仅线上：%s　仅本地：%s"
             % ([n for n in ln if n not in on], [n for n in on if n not in ln])))
    if not same_set:
        bad += 1
    if ln != on:
        print("  %-6s     顺序不同属预期：本地按推荐序（综合 55%% + 共振 45%%）排" % "顺序")
    # 分数按名字对齐比（榜单通道卡剔除后，B/C 段会整体前移一位，按下标比会假报）。
    # 只对两边都有的名字比分值（±1）；顺序由上面的「观察池」项覆盖。
    lv = {n: int(s) for n, s in zip(liv["观察池"], liv["分数"]) if n not in chan}
    ov = {c[0]: int(c[1]) for c in loc_cards if c[1]}
    common = [n for n in lv if n in ov]
    diff = [(n, lv[n], ov[n]) for n in common if abs(lv[n] - ov[n]) > 1]
    print("  %-6s %s  共同比对 %d 名，差>1：%s"
          % ("分数", "OK  " if not diff else "DIFF", len(common), diff or "无"))
    if diff:
        bad += 1
    only_l = [n for n in lv if n not in ov]
    only_o = [n for n in ov if n not in lv]
    if only_l or only_o:
        print("  %-6s DIFF 仅线上：%s　仅本地：%s" % ("名单", only_l, only_o))
        bad += 1
    # 叙事：本地多一条「驱动词口径」属预期
    extra = [x for x in loc["叙事"] if x not in liv["叙事"]]
    missing = [x for x in liv["叙事"] if x not in loc["叙事"]]
    print("  %-6s %s  本地新增：%s  本地缺：%s"
          % ("叙事", "OK  " if not missing else "DIFF", extra or "无", missing or "无"))
    if missing:
        bad += 1

    print("\n结论：%s" % ("PASS 与线上一致（本地多出驱动词模块）" if not bad
                        else "FAIL %d 项不一致" % bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
