# -*- coding: utf-8 -*-
"""页面外壳：<head> + 导航 + .wrap 容器 + 页脚。

三个新页面（榜单/题材/个股）都套这一个壳，保证 title/meta/nav 的写法只有一处，
不会出现"某一页忘了加 viewport"这种事。
"""
from __future__ import annotations

from .components import esc
from .nav import nav
from .theme import CSS, THEME_BOOT, THEME_TOGGLE_JS


def page(title: str, active: str, body: str, *, subtitle: str = "",
         extra_head: str = "", tail: str = "") -> str:
    return "".join([
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        # 主题必须在 <style> 之前定好，否则暗黑用户每次进页先闪一屏白
        THEME_BOOT,
        "<title>%s</title>" % esc(title),
        "<style>%s</style>" % CSS,
        extra_head,
        "</head><body>",
        nav(active, subtitle or "本地 · 数据真值"),
        '<div class="wrap">',
        body,
        "</div>",
        tail,
        THEME_TOGGLE_JS,
        "</body></html>",
    ])


def footer(*lines: str) -> str:
    return '<footer>%s</footer>' % "<br>".join(esc(x) for x in lines)


def no_bundle() -> str:
    """bundle.json 不存在时的整页提示——不是 500，也不是空白。"""
    return page("还没有数据", "/rank", (
        '<div class="card"><h2>还没有实时数据<span>data/live/bundle.json 不存在</span></h2>'
        '<div class="empty">榜单、题材、个股三个页面读的都是同一份合并数据，'
        "现在这份还没生成。</div>"
        '<div class="warn">在工程目录跑一次 <b>python refresh.py</b> 就好。'
        "它会把人气榜、tdx、同花顺热榜抓下来合并；抓完刷新本页即可。</div></div>"))
