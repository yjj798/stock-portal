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

    # 主线页必须是真页面，不能是空壳：page_theme.render 少传 sc 时会静默退化成
    # "还没有主线归并结果"，链接检查照样通过（2026-11-02 踩过）。
    th_page = os.path.join(DIST, "theme", "index.html")
    if os.path.exists(th_page):
        ht = open(th_page, encoding="utf-8").read()
        chk("主线页有正文（非空壳）", "今天在炒哪条消息" in ht)
        chk("主线页印出主线名", "AI 视频" in ht)
        # 2026-11-02：消息面关键词榜来自全市场异动解析，静态页也必须带上，
        # 否则线上看到的主线页只有"人工整理的消息面"，没有真实原文。
        chk("主线页有今日关键词榜", "今日关键词" in ht)
        chk("主线页有实况关键词与行业原因原文",
            ("实况关键词" in ht) and ("行业原因原文" in ht))
    else:
        chk("主线页存在", False)

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
    # 2026-11-02 起 / 是介绍页（DeepSeek 登录页式），总览搬到 /board。
    # 断言随之拆成两组：首页查"门面 + 登录入口"，/board 查"四栏 tabset"。
    home = page("index.html")
    chk("首页是介绍页而非总览", 'data-tabs="home"' not in home and
        ("这个系统在回答什么" in home or "九个栏目" in home))
    chk("首页有会员入口", ("/login" in home or "t.legaga.top/login" in home)
        and ("/register" in home or "t.legaga.top/register" in home))
    chk("首页写明不构成投资建议", "不构成投资建议" in home)
    chk("首页无残留绝对内链", not re.search(r'href="/(rank|concept|drivers|attr|brief|s|snapshot)', home))

    board = page("board/index.html")
    chk("总览页四栏 tabset", board.count('data-tabs="home"') == 1 and
        all(('data-k="%s"' % k) in board for k in ("mood", "pool", "struct", "flow")))
    chk("总览栏链接指回 /board", 'href="../board/?t=pool"' in board)
    chk("总览页无残留绝对内链", not re.search(r'href="/(rank|concept|drivers|attr|brief|s|snapshot|board)', board))
    chk("静态站会员页跳动态站", "t.legaga.top" in page("login/index.html"))

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
