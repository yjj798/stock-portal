# -*- coding: utf-8 -*-
"""栏目导航 + 登录态。

2026-11-02 起站里多了一个「门面」：`/` 变成介绍页（landing），原来的复盘总览
搬到 `/board`。导航顺序按"从归因到个股"的阅读顺序排：

    首页 → 总览 → 主线 → 榜单 → 行业 → 题材 → 驱动词 → 归因 → 简报

登录态怎么进来
--------------
`nav()` 被 9 个页面间接调用（都走 shell.page），给每个 render 函数加一个 user 参数
会连带改 9 个签名、9 个调用点。改用一个请求级上下文：请求一开始
`set_ctx(user=..., static=False)`，nav 自己读。线程模型是 ThreadingHTTPServer
（一请求一线程），threading.local 天然隔离；静态构建是单线程，设一次就够。

静态站没有后端，`static=True` 时登录/注册/我的三个入口指向 `SITE_LIVE`
（默认 https://t.legaga.top），而不是站内死链。
"""
from __future__ import annotations

import threading

# (路径, 名称, 是否建设中)
TABS = [
    ("/", "首页", False),
    ("/board", "总览", False),
    ("/theme", "主线", False),
    ("/rank", "榜单", False),
    ("/industry", "行业", False),
    ("/concept", "题材", False),
    ("/drivers", "驱动词", False),
    ("/attr", "归因", False),
    ("/brief", "简报", False),
]

SUB = "本地 · 数据真值"

# 静态站点的会员入口指向这个域名（静态托管没有后端）
SITE_LIVE = "https://t.legaga.top"

_l = threading.local()


def set_ctx(user=None, static: bool = False, live: str = "") -> None:
    """每个请求/每次构建开头调一次。user 为 None 表示未登录。"""
    _l.user = user
    _l.static = bool(static)
    _l.live = live or SITE_LIVE


def get_ctx() -> tuple:
    return (getattr(_l, "user", None),
            getattr(_l, "static", False),
            getattr(_l, "live", SITE_LIVE))


def _auth_links(user, static: bool, live: str) -> str:
    """右上角：未登录给「登录 / 注册」，已登录给「用户名 → 会员中心」。"""
    from .components import esc

    def href(p: str) -> str:
        return (live.rstrip("/") + p) if static else p

    if user:
        name = esc(user.get("username") or user.get("email") or "我的")
        return ('<div class="nauth"><a class="me" href="%s" title="会员中心">%s</a></div>'
                % (href("/me"), name))
    return ('<div class="nauth"><a href="%s">登录</a>'
            '<a class="cta" href="%s">免费注册</a></div>'
            % (href("/login"), href("/register")))


def nav(active: str = "/", subtitle: str = SUB) -> str:
    """渲染顶部导航。active 传当前路径，用于高亮。"""
    from .components import esc

    user, static, live = get_ctx()
    links = []
    for href, name, building in TABS:
        cls = ' class="on"' if href == active else ""
        mark = "" if not building else '<span style="font-size:10px;opacity:.55">·</span>'
        links.append('<a%s href="%s">%s%s</a>' % (cls, href, esc(name), mark))
    return (
        '<nav class="nav"><div class="navin">'
        '<a class="brand" href="/">A 股全景<i>%s</i></a>'
        '<div class="tabs">%s</div>'
        '%s'
        '<button class="tmode" id="tmode" type="button" onclick="wbToggleTheme()" '
        'title="切换 深色 / 浅色 主题">◐</button>'
        '</div></nav>'
    ) % (esc(subtitle), "".join(links), _auth_links(user, static, live))
