# -*- coding: utf-8 -*-
"""涨停归因页 /attr —— 全市场涨停/炸板池的截面归因（原 d 站深色 1500px 版的浅色重做）。

数据源：东财 push2ex 涨停池/炸板池（fetchers/attr.py 抓成离线快照），
驱动词列接本站 reasons_core 的同花顺 keywordList。

与原版（zt-quant tools/attr_page.py）的差别，逐条说明理由：
    ① 「双概念」列换成「驱动词」：原版靠题材分发服务器 4427/4450/4421 取双概念，
       该服务器 2026-11-02 实测**全日期 404**；本站本来就有同花顺逐股驱动词，
       而且「个股驱动」比「行业题材链」更细（见 page_drivers 的口径说明）。
    ② 去掉 60s 自动刷新：本站三页统一是「请求期不联网、只读快照」，
       单页自动刷新会让一个页面的节奏跟其它页不一致，也对上游不礼貌。
       要最新数据就重跑 refresh.py。
    ③ 保留四 Tab 与按板数分组：这是原版最有用的结构——同一板数的票放在一起，
       才看得出「这个高度上有几只、谁先封」。
"""
from __future__ import annotations

from .components import card, empty, esc, pct_span, rnd, table, td, trim, yi
from .shell import footer, page

EXTRA_CSS = """
<style>
.kpi5{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 16px}
.kpi .k{font-size:11.5px;color:var(--muted);display:flex;gap:6px;align-items:baseline}
.kpi .k small{font-size:10px;opacity:.7}
.kpi .v{font-size:27px;font-weight:800;letter-spacing:-.5px;margin-top:4px;
  font-variant-numeric:tabular-nums}
.kpi .v small{font-size:12px;font-weight:400;color:var(--muted);margin-left:2px}
.kpi .n{font-size:11px;color:var(--muted);margin-top:2px}
.tabbar{display:flex;gap:4px;margin:0 0 14px;flex-wrap:wrap}
.tabbar button{font:inherit;font-size:12.5px;padding:6px 14px;border-radius:8px;cursor:pointer;
  border:1px solid var(--line);background:var(--soft);color:var(--t2)}
.tabbar button.on{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:600}
.pane{display:none}.pane.show{display:block}
tr.grp td{background:var(--soft2);font-weight:700;font-size:12px;color:var(--t2);
  padding:5px 10px!important}
.gnum{color:var(--muted);font-weight:400;margin-left:4px}
.dim{color:var(--muted)}
.wt{font-size:11.5px;color:var(--tag2ck);background:var(--tag2bg);border-radius:4px;
  padding:0 6px;margin-right:4px;display:inline-block}
@media(max-width:900px){.kpi5{grid-template-columns:repeat(2,1fr)}}
</style>
"""

TAB_JS = """
<script>
function atab(k,btn){
  var i,ts=document.querySelectorAll('.tabbar button'),ps=document.querySelectorAll('.pane');
  for(i=0;i<ts.length;i++){ts[i].classList.toggle('on',ts[i]===btn);}
  for(i=0;i<ps.length;i++){ps[i].classList.toggle('show',ps[i].id==='pane-'+k);}
  try{sessionStorage.setItem('attr_tab',k);}catch(e){}
}
try{var k0=sessionStorage.getItem('attr_tab');
  if(k0){var b=document.querySelector('.tabbar button[data-k="'+k0+'"]');if(b)atab(k0,b);}
}catch(e){}
</script>
"""


def _hhmmss(v) -> str:
    """东财 fbt 是 92500 这样的整数（时分秒），不是时间戳。"""
    n = int(v or 0)
    if not n:
        return "—"
    s = str(n).zfill(6)
    return "%s:%s:%s" % (s[0:2], s[2:4], s[4:6])


def _board_label(it) -> str:
    """连板高度（lbc）为主；区间口径（16天8板）只作灰色补充，两者不等时以 lbc 为准。"""
    b = int(it.get("board") or 1)
    base = "首板" if b <= 1 else "%d 连板" % b
    days, ct = int(it.get("days") or 0), int(it.get("ct") or 0)
    if ct and days > ct:
        base += '<span class="sub">（%d天%d板）</span>' % (days, ct)
    return base


def _stock_cell(code, name) -> str:
    return '<a class="sl" href="/s/%s">%s</a><div class="sub">%s</div>' % (
        esc(code), esc(name), esc(code))


def _kw_of(code, kw_map) -> str:
    ws = kw_map.get(code) or []
    if not ws:
        return '<span class="sub">—</span>'
    return "".join('<span class="chip">%s</span>' % esc(w) for w in ws[:3])


def _ladder_table(pool, kw_map, note="") -> str:
    """按连板高度分组：同高度的票排在一起才看得出这个高度上有几只、谁先封。"""
    if not pool:
        return empty("该池子今日为空。")
    groups = {}
    for it in pool:
        groups.setdefault(int(it.get("board") or 1), []).append(it)
    rows = []
    for b in sorted(groups, reverse=True):
        members = sorted(groups[b], key=lambda x: (int(x.get("fbt") or 999999),
                                                   -float(x.get("fund") or 0)))
        label = "首板组" if b <= 1 else "%d 板组" % b
        rows.append('<tr class="grp"><td colspan="9">▾ %s<span class="gnum">（%d 只）</span></td></tr>'
                    % (label, len(members)))
        for it in members:
            code = it["code"]
            rows.append("<tr>%s%s%s%s%s%s%s%s%s</tr>" % (
                td(_stock_cell(code, it.get("name")), left=True),
                td(_board_label(it)),
                td(_hhmmss(it.get("fbt"))),
                td(yi(it.get("fund"))),
                td(pct_span(it.get("pct"))),
                td("%s%%" % trim(it.get("turnover"), 1) if it.get("turnover") is not None else "—"),
                td(esc(it.get("industry") or "—"), "sub"),
                td(_kw_of(code, kw_map), left=True),
                td('<a class="sub" href="/s/%s">原因 →</a>' % esc(code)),
            ))
    return table(["股票", "板数", "首封", "封单", "涨幅", "换手", "行业", "驱动词", ""],
                 "".join(rows), "l r r r r r l l r")


def _zb_table(pool, kw_map) -> str:
    if not pool:
        return empty("今日无炸板。")
    rows = []
    for it in sorted(pool, key=lambda x: -(int(x.get("zbc") or 0))):
        code = it["code"]
        rows.append("<tr>%s%s%s%s%s%s%s%s</tr>" % (
            td(_stock_cell(code, it.get("name")), left=True),
            td(str(int(it.get("zbc") or 0)) + " 次"),
            td(pct_span(it.get("pct"))),
            td(_hhmmss(it.get("fbt"))),
            td("%.2f" % float(it.get("price") or 0)),
            td(yi(it.get("amount"))),
            td(esc(it.get("industry") or "—"), "sub"),
            td(_kw_of(code, kw_map), left=True),
        ))
    return table(["股票", "炸板次数", "涨幅", "首次封板", "现价", "成交额", "行业", "驱动词"],
                 "".join(rows), "l r r r r r l l")


def _watch_pool(pool) -> list:
    """盯盘打板：梯队（≥2 板）+ 炸过又回封 + 尾盘首封。三条各有独立含义。"""
    out, seen = [], set()
    for it in pool:
        code = it["code"]
        b = int(it.get("board") or 1)
        zbc = int(it.get("zbc") or 0)
        fbt = int(it.get("fbt") or 0)
        why = []
        if b >= 2:
            why.append("梯队 %d 板" % b)
        if zbc >= 1:
            why.append("炸 %d 次回封" % zbc)
        if fbt >= 140000:
            why.append("尾盘首封")
        if why and code not in seen:
            seen.add(code)
            out.append((why, it))
    out.sort(key=lambda t: (-int(t[1].get("board") or 1), int(t[1].get("fbt") or 0)))
    return out


def _watch_table(pool, kw_map) -> str:
    cands = _watch_pool(pool)
    if not cands:
        return empty("今日无梯队 / 回封 / 尾盘封标的。")
    rows = []
    for why, it in cands:
        code = it["code"]
        rows.append("<tr>%s%s%s%s%s%s%s</tr>" % (
            td("".join('<span class="wt">%s</span>' % esc(w) for w in why), left=True),
            td(_stock_cell(code, it.get("name")), left=True),
            td(_board_label(it)),
            td(_hhmmss(it.get("fbt"))),
            td(str(int(it.get("zbc") or 0))),
            td(yi(it.get("fund"))),
            td(_kw_of(code, kw_map), left=True),
        ))
    return table(["盯盘理由", "股票", "板数", "首封", "炸板", "封单", "驱动词"],
                 "".join(rows), "l l r r r r l")


def _kpi(today, prev, y8, qdate) -> str:
    zt, zb = today["zt"], today["zb"]
    zt_y, zb_y = prev["zt"], prev["zb"]
    rate = len(zb) / (len(zt) + len(zb)) * 100 if (zt or zb) else 0.0
    rate_y = len(zb_y) / (len(zt_y) + len(zb_y)) * 100 if (zt_y or zb_y) else 0.0
    # 炸板率越高＝封板质量越差，所以「低」是好事：颜色反过来标，别让人误读
    d = rate - rate_y
    cells = [
        ("昨日涨停", len(zt_y), "只", y8[4:6] + "/" + y8[6:] if len(y8) == 8 else "上一交易日",
         "var(--t2)"),
        ("今日涨停", len(zt), "只", "全市场", "var(--up)"),
        ("今日炸板", len(zb), "只", "封上又开", "#e8804a"),
        ("昨日炸板率", "%.1f" % rate_y, "%", "封板质量基准", "#7c3aed"),
        ("当前炸板率", "%.1f" % rate, "%",
         "较昨日 %+.1f 个点" % d if (zt_y or zb_y) else "无昨日基准", "#2563eb"),
    ]
    out = []
    for k, v, u, n, c in cells:
        out.append('<div class="kpi"><div class="k">%s</div>'
                   '<div class="v" style="color:%s">%s<small>%s</small></div>'
                   '<div class="n">%s</div></div>' % (esc(k), c, v, esc(u), esc(n)))
    return '<div class="kpi5">%s</div>' % "".join(out)


def _concept_strip(pool, rd, kw_map, gains, names) -> str:
    """概念 TOP10（只取**具体**驱动词）+ 区间最强 TOP5。

    为什么剔泛词：涨停归因要回答「钱在哪个方向」，而「三季报增长」15 只里
    大半是沾边的，把它排第一等于没归因。泛词的完整名单在 /drivers 有专门一列。
    """
    from collections import Counter
    generic = {d["keyword"] for d in (rd.get("drivers") or []) if d.get("generic")}
    cnt = Counter()
    for it in pool:
        # 逐个按字典序遍历：set 的迭代顺序受 PYTHONHASHSEED 影响，跨进程不稳定，
        # 会让 Counter 的首次插入顺序漂移 → 同分词的先后每次都变 → 构建产物不可复现，
        # 发布链路就无法用"树相同则跳过"判断真变更。排序后插入，才可复现。
        for w in sorted({kw for kw in (kw_map.get(it["code"]) or [])
                         if kw not in generic}):
            cnt[w] += 1
    # 同计数按词名排序，避免并列项顺序随数据顺序漂移
    top = sorted(cnt.items(), key=lambda t: (-t[1], t[0]))[:10]
    chips = "".join('<span class="chip">%d.&nbsp;%s&nbsp;<b>%d</b></span>'
                    % (i, esc(w), n) for i, (w, n) in enumerate(top, 1))
    rng = sorted(gains.items(), key=lambda t: (-t[1], t[0]))[:5]
    rchips = "".join('<span class="chip">%s&nbsp;<b class="red">+%.1f%%</b></span>'
                     % (esc(names.get(c, c)), g) for c, g in rng)
    return (
        '<div class="card"><h2>概念热度 TOP10<span>今日涨停股按具体驱动词归属计数，泛词不计（全表见驱动词页）</span></h2>'
        '<div class="chips">%s</div>'
        '<h2 style="margin-top:16px">区间最强 TOP5<span>涨停池内 10 个交易日涨幅（新浪日K不复权，东财兜底）</span></h2>'
        '<div class="chips">%s</div></div>'
        % (chips or '<span class="sub">无驱动词数据</span>',
           rchips or '<span class="sub">涨幅计算中/无数据</span>'))


def render(attr=None, rd=None, bundle=None) -> str:
    if not attr:
        body = card("涨停归因", empty(
            "还没有归因快照（data/live/attr.json）。在工程目录跑一次 python refresh.py。"))
        return page("涨停归因", "/attr", body,
                    tail=footer("数据源：东财涨停池/炸板池 push2ex.eastmoney.com",
                                "本页只做汇总展示，不构成投资建议。"))

    qdate, y8 = attr.get("qdate") or "", attr.get("prev_date") or ""
    today, prev = attr.get("today") or {}, attr.get("prev") or {}
    gains = attr.get("gains") or {}
    zt = today.get("zt") or []
    zb = today.get("zb") or []

    rd = rd or {}
    kw_map = {r["code"]: [k for k in (r.get("keywords") or []) if k]
              for r in (rd.get("records") or [])}
    names = {r["code"]: r.get("name") or "" for r in (rd.get("records") or [])}
    for it in zt:
        names.setdefault(it["code"], it.get("name") or "")

    d8 = "%s-%s-%s" % (qdate[:4], qdate[4:6], qdate[6:]) if len(qdate) == 8 else qdate
    head = ('<div class="hero"><div class="eyebrow">涨停归因 · %s</div>'
            '<div class="hd"><h1>涨停 / 炸板 · 全市场截面</h1>'
            '<span class="c">%d 只涨停 · %d 只炸板 · 上一交易日 %s（%d 涨停 / %d 炸板）'
            "· 快照 %s</span></div></div>"
            % (esc(d8), len(zt), len(zb),
               "%s-%s-%s" % (y8[:4], y8[4:6], y8[6:]) if len(y8) == 8 else "—",
               len(prev.get("zt") or []), len(prev.get("zb") or []),
               esc((attr.get("fetched_at") or "").replace("T", " "))))

    tabs = [("zt", "今日涨停", len(zt)), ("yzt", "昨日涨停", len(prev.get("zt") or [])),
            ("zb", "今日炸板", len(zb)), ("watch", "盯盘打板",
                                          len(_watch_pool(zt)))]
    bar = '<div class="tabbar">%s</div>' % "".join(
        '<button data-k="%s" onclick="atab(\'%s\',this)"%s>%s <span class="gnum">%d</span></button>'
        % (k, k, ' class="on"' if i == 0 else "", esc(n), c)
        for i, (k, n, c) in enumerate(tabs))

    panes = "".join([
        '<div class="pane show" id="pane-zt">%s</div>' % _ladder_table(zt, kw_map),
        '<div class="pane" id="pane-yzt">%s</div>'
        % _ladder_table(prev.get("zt") or [], kw_map,
                        note="上一交易日截面；当日表现需次日行情才能评估"),
        '<div class="pane" id="pane-zb">%s</div>' % _zb_table(zb, kw_map),
        '<div class="pane" id="pane-watch">%s</div>' % _watch_table(zt, kw_map),
    ])

    errs = attr.get("errors") or []
    warn = ('<div class="warn">数据源降级：%s</div>'
            % esc("；".join(errs))) if errs else ""

    body = "".join([
        head,
        _kpi(today, prev, y8, qdate),
        warn,
        _concept_strip(zt, rd, kw_map, gains, names),
        card("四张表<span>今日 / 昨日 / 炸板 / 盯盘 —— 按连板高度分组</span>" + bar, panes),
        card("口径说明", (
            '<div class="dv-detail">'
            "<b>涨停池 / 炸板池</b>都来自东财 push2ex 接口，是全市场口径（约 47 涨停 / 31 炸板），"
            "和本站榜单/题材页的「人气池 167 只」不是同一个集合——前者是今天封住的全市场，"
            "后者是有热度的票。<br>"
            "<b>板数</b>用 lbc（连板高度）分组：东财还给了 zttj 区间口径（如 16 天 8 板），"
            "两个不等时按连板高度分组，区间口径只作灰色补充——否则「8 板」会把"
            "反复开板的老票也归进高标组。<br>"
            "<b>炸板率</b> = 炸板数 /（涨停 + 炸板）。它越高说明封板质量越差，"
            "所以这是一项<b>反向</b>指标：降下来才是好转。<br>"
            "<b>驱动词</b>来自同花顺逐股异动（本题材页不依赖已失效的题材分发服务器 4427）。"
            "概念 TOP10 是「今日涨停股按驱动词计数」，同日多词各计一次，"
            "所以计数之和会大于涨停家数。<br>"
            "<b>区间最强</b>是涨停池内 10 个交易日涨幅，日K首末收盘现算（主通道新浪、不复权，10 日窗口内除权的票会有小幅偏差；东财兜底），"
            "不是连板数——它回答「这一波谁涨得最多」，与「今天谁最高」是两个问题。"
            "</div>")),
    ])
    return page("涨停归因 · %s" % d8, "/attr", body,
                extra_head=EXTRA_CSS + TAB_JS,
                tail=footer("数据源：东财涨停池/炸板池（push2ex.eastmoney.com）"
                            "· 驱动词 同花顺逐股异动 · 区间涨幅 腾讯日K",
                            "本页只做汇总展示，不构成投资建议。"))
