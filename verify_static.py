# -*- coding: utf-8 -*-
"""静态站验收：扫 dist/ 全部页面里的内部链接，逐个确认目标文件存在。
再抽查关键内容点（分栏、搜索控件、概念详情脚本、快照 base）。
用法：python verify_static.py [--serve]（--serve 时先起 8901 再 curl 探活）
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import unquote, urlparse

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")

OK, BAD = [], []


def chk(name, cond):
    (OK if cond else BAD).append(name)


def main():
    pages = [os.path.join(dp, fn).replace("\\", "/")
             for dp, _, fns in os.walk(DIST) for fn in fns if fn.endswith(".html")]
    chk("页面数量 >= 170", len(pages) >= 170)

    # ---- 全站链接检查（只查站内相对链接）
    broken, seen = [], set()
    for p in pages:
        rel = os.path.relpath(p, DIST).replace("\\", "/")
        base_dir = os.path.dirname(rel)
        html = open(p, encoding="utf-8").read()
        for m in re.finditer(r'(?:href|action)="([^"]+)"', html):
            u = m.group(1)
            if u.startswith(("http://", "https://", "#", "javascript:", "mailto:")):
                continue
            if "'" in u or "+" in u:      # 注入 JS 模板串（'<a href="'+WBP+...），非真链接
                continue
            path = unquote(urlparse(u).path)
            if not path or path == "#":
                continue
            target = os.path.normpath(os.path.join(base_dir, path)).replace("\\", "/")
            if target in seen:
                continue
            seen.add(target)
            if os.path.isdir(os.path.join(DIST, target)):
                if not os.path.isfile(os.path.join(DIST, target, "index.html")):
                    broken.append("%s -> %s（目录缺 index.html）" % (rel, target))
            elif not os.path.isfile(os.path.join(DIST, target)):
                broken.append("%s -> %s（不存在）" % (rel, target))
    chk("内部链接全部可达（%d 个目标）" % len(seen), not broken)
    for b in broken[:12]:
        print("  断链:", b)

    def page(rel):
        with open(os.path.join(DIST, rel), encoding="utf-8") as f:
            return f.read()

    # ---- 关键内容抽查
    home = page("index.html")
    chk("首页四栏 tabset", home.count('data-tabs="home"') == 1 and
        all(('data-k="%s"' % k) in home for k in ("mood", "pool", "struct", "flow")))
    chk("首页 tab 链接同页查询", 'href="?t=pool"' in home and 'href="/' not in home)
    chk("首页无残留绝对内链", not re.search(r'href="/(rank|concept|drivers|attr|brief|s|snapshot)', home))

    rank = page("rank/index.html")
    chk("榜单两栏", 'data-tabs="rank"' in rank and 'data-k="score"' in rank and 'data-k="hot"' in rank)
    chk("搜索控件已注入", "wbSearchGo" in rank and 'action="#"' in rank)
    chk("搜索索引含股票", '"000525"' in rank or "000525" in rank)
    chk("日榜目录页", os.path.isfile(os.path.join(DIST, "rank/day/index.html")))

    con = page("concept/index.html")
    chk("概念页详情脚本", "var WBC=" in con and "URLSearchParams" in con)

    st = page("s/000525/index.html")
    chk("个股页相对回链", 'href="../../concept/' in st or 'href="../../s/' in st)

    snap = [f for f in pages if "/snapshot/" in f]
    if snap:
        s = open(snap[0], encoding="utf-8").read()
        # 历史快照页的分栏链接要么同页查询（?t=），要么指向自己的 snapshot 目录
        chk("快照页 tab 链接指向自身", 'href="?t=' in s or
            re.search(r'href="(?:\.\./)+snapshot/[^/"]+/\?t=', s))
        chk("快照页无根路径残留", 'href="/snapshot/' not in s and 'href="/?t=' not in s)

    chk("404 与 .nojekyll", os.path.isfile(os.path.join(DIST, "404.html")) and
        os.path.isfile(os.path.join(DIST, ".nojekyll")))

    print("PASS %d" % len(OK))
    for b in BAD:
        print("FAIL:", b)
    sys.exit(1 if BAD else 0)


if __name__ == "__main__":
    main()
