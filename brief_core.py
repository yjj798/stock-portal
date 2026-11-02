# -*- coding: utf-8 -*-
"""【已退役 2026-11-02】本模块的抓取逻辑已并入 fetchers/brieffeed.py。

退役原因：①import parse_brief 从搬进来那天就是错的（文件叫 brief_parse），
从未跑通过一次；②通道顺序没有按实测排（raw 直连在本机是黑洞丢包）。
解析器 brief_parse.py 仍在役（brieffeed 依赖它）。别再修这个文件，直接用：
    python -m fetchers.brieffeed 4
"""
raise SystemExit("brief_core.py 已退役 → 用 python -m fetchers.brieffeed")
