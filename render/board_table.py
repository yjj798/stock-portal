# -*- coding: utf-8 -*-
"""板块榜通用组件：行业页与概念页共用同一张表。

为什么抽出来
------------
用户 2026-11-02 的原话：「行业板块跟概念板块，他们输出应该格式都一样。我看行业板块里边
写了很多个股，但是概念板块里边没有，如果有都有，如果没有都没。」

两页各写一套表，必然漂：这边加一列"领涨股"、那边忘了；这边给"池内 N 只"、那边没有。
底层的板块读数本来就是**同一套接口字段**（东财 m:90+t:2 行业 / m:90+t:3 概念，f3 涨幅、
f62 主力净额、f104/f105 涨跌家数、f128 领涨股完全一致），打分也是同一个函数，那表就该是
同一张。这里只留一份实现，调用方传 kind 决定标题措辞。

热度分怎么来的（与 sector._rows 一致，不重复实现）
    涨幅 45（全板块涨幅分位）+ 广度 25（收缩后的广度分位）
    + 涨停 20（池内封板数，5 只封顶）+ 均涨 10（池内成员平均涨幅）
"""
from __future__ import annotations

from .components import card, empty, esc, num, signed, table, td, yi


def _pct_cell(v) -> str:
    if v is None:
        return '<span class="sub">—</span>'
    return '<b class="%s">%s%%</b>' % ("red" if num(v) >= 0 else "green", signed(v, 2))


def _bar(frac, label: str) -> str:
    f = max(0.0, min(1.0, num(frac)))
    return ('<div class="dcell"><b>%s</b><div class="dbar"><i style="width:%.0f%%"></i></div></div>'
            % (esc(label), f * 100))


def board_table(rows, title: str, sub: str = "", kind: str = "ind",
                limit: int = None, hot_word: str = "热") -> str:
    """rows 来自 sector._rows()。kind 只影响措辞，不影响列与算法。"""
    if not rows:
        return card(title, empty("今天没有板块数据"), sub)
    rows = rows[:limit] if limit else rows
    trs = []
    for r in rows:
        delta = r.get("delta")
        dcell = ('<span class="%s">%s pp</span>'
                 % ("red" if num(delta) >= 0 else "green", signed(delta, 2))
                 if delta is not None else '<span class="sub">—</span>')
        lu = ('<span class="tag n">%d</span>' % r["lu"]) if r["lu"] else '<span class="sub">0</span>'
        trs.append("<tr>%s%s%s%s%s%s%s%s%s%s%s%s</tr>" % (
            td('<span class="rk%s">%d</span>'
               % (" t1" if r["rank"] == 1 else (" t2" if r["rank"] == 2 else
                                                (" t3" if r["rank"] == 3 else "")), r["rank"])),
            td("<b>%s</b>%s" % (esc(r["name"]),
                               '<span class="tag n" style="margin-left:6px">%s</span>' % hot_word
                               if r["hot"] else ""), left=True),
            td(_pct_cell(r["pct"])),
            td(_bar(r["pct_rank"], "%.0f%%" % (r["pct_rank"] * 100)), left=True),
            td("%s / %s" % (r["up"] if r["up"] is not None else "—",
                            r["down"] if r["down"] is not None else "—")),
            td(_bar(r.get("breadth_rank") or 0,
                    "%.0f%%" % ((r.get("breadth") or 0) * 100)), left=True),
            td(yi(r["net"]) if r.get("net") is not None else '<span class="sub">—</span>'),
            td("%d 只" % r["n"]),
            td(lu),
            td(dcell),
            td(esc(r.get("leader") or "—"), left=True),
            td('<b class="%s">%s</b>' % ("red" if r["total"] >= 70 else "", "%.1f" % r["total"])),
        ))
    body = table(["#", "板块" if kind == "ind" else "概念板块", "涨幅", "涨幅分位", "涨 / 跌",
                  "上涨广度", "主力净额", "池内", "涨停", "较昨日", "领涨股", "热度分"],
                 "".join(trs), "l l r l r l r r r r l r")
    return card(title, body, sub)
