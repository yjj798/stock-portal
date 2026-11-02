# -*- coding: utf-8 -*-
"""栏目导航：一个项目一个站，六栏 + 个股详情。

与 d 站现有 NAV 的差别：原来三栏（复盘/简报/归因）且简报是 GitHub Pages 外链；
合并后六栏全部在本站内（/rank /concept /drivers 新增，/brief 取代外链）。
"""

# (路径, 名称, 是否建设中)
TABS = [
    ("/", "复盘", False),
    ("/rank", "榜单", False),
    ("/industry", "行业", False),
    ("/concept", "题材", False),
    ("/drivers", "驱动词", False),
    ("/attr", "归因", False),
    ("/brief", "简报", False),
]

SUB = "本地 · 数据真值"


def nav(active: str = "/", subtitle: str = SUB) -> str:
    """渲染顶部导航。active 传当前路径，用于高亮。"""
    from .components import esc

    links = []
    for href, name, building in TABS:
        cls = ' class="on"' if href == active else ""
        mark = "" if not building else '<span style="font-size:10px;opacity:.55">·</span>'
        links.append('<a%s href="%s">%s%s</a>' % (cls, href, esc(name), mark))
    return (
        '<nav class="nav"><div class="navin">'
        '<a class="brand" href="/">A 股全景<i>%s</i></a>'
        '<div class="tabs">%s</div>'
        '<button class="tmode" id="tmode" type="button" onclick="wbToggleTheme()" '
        'title="切换 深色 / 浅色 主题">◐</button>'
        '</div></nav>'
    ) % (esc(subtitle), "".join(links))
