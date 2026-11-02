# -*- coding: utf-8 -*-
"""把动态站静态化，产出 dist/ —— 发布 GitHub Pages / 任意静态托管用。

为什么可以静态化：serve.py 的设计就是「请求期只读 data/live、不联网、不写状态」，
唯一的动态来源是三个查询参数：
  ?t=    分栏   → PAGE_JS 载入初始化 + popstate 兜底，静态页同样生效
  ?q=    搜索   → 换成客户端搜索控件（内嵌代码/名称索引，submit 跳第一个命中）
  ?c=    概念   → 概念页内嵌「概念→成分」JSON，JS 按 ?c= 画成员卡
  hot=hour|day  → 生成 rank/ 与 rank/day/ 两个目录页

链接改写规则（rewrite 函数）：所有绝对路径 href/action 按所在文件深度改成相对路径，
目录式带尾斜杠（GitHub Pages 的 /rank 会 301 到 /rank/，直接生成 rank/ 免一次跳转）。

用法：python build_static.py   （先跑过 refresh.py / snapshot_job.py 有数据）
"""
from __future__ import annotations

import html as htmllib
import json
import os
import re
import shutil
import sys

import score as scoring
import store
from render import page_attr, page_brief, page_concept, page_drivers, page_home, \
    page_industry, page_rank, page_stock
from sec_core import derive

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")

# 概念名里 Windows/URL 不友好的字符 → 目录名替换
ILLEGAL = re.compile(r'[\\/:*?"<>|\s#%&{}$!\']+')
KNOWN_SEGS = ["rank", "concept", "drivers", "industry", "attr", "brief", "s", "snapshot"]


def safe_name(name: str) -> str:
    s = ILLEGAL.sub("_", name).strip("_")
    return s or "_"


def root_of(depth: int) -> str:
    return "" if depth <= 0 else "../" * depth


def rewrite(html: str, depth: int) -> str:
    """绝对路径 → 相对路径。depth = 文件在 dist/ 下的目录层数。"""
    root = root_of(depth)

    def rep(m):
        attr, raw = m.group(1), m.group(2)
        path = htmllib.unescape(raw)
        if path.startswith("/?"):
            return '%s="%s"' % (attr, raw[1:])          # 同页查询，任何深度都成立
        p, _, q = path.partition("?")
        tail = ""
        if p == "/":
            out, tail = root, q                          # snapshot 分栏要保住 ?t=
        elif p == "/rank":
            out = root + ("rank/day/" if "hot=day" in q else "rank/")
        elif p == "/concept":
            # 概念详情走单页 + ?c= 查询（JS 按 c 画成分卡），不为 400+ 概念各出一个目录
            out, tail = root + "concept/", q
        elif p.startswith("/snapshot/"):
            out, tail = root + p[1:] + "/", q            # 保留 ?t=
        elif p.startswith("/s/"):
            out = root + p[1:] + "/"
        elif p in ("/drivers", "/attr", "/brief", "/industry"):
            out = root + p[1:] + "/"
        elif p == "/mp":
            return '%s="%s"' % (attr, root)              # 打印视图并入首页
        else:
            return m.group(0)                            # 未知/外链不动
        return '%s="%s%s"' % (attr, out, ("?" + tail) if tail else "")

    return re.sub(r'(href|action)="(/[^"]*)"', rep, html)


def _search_widget(depth: int, stocks: dict) -> str:
    """rank 页搜索：服务端 ?q= 在静态托管下不存在，换客户端控件。"""
    idx = sorted(([c, (e.get("name") or "")] for c, e in stocks.items()),
                 key=lambda x: x[0])
    prefix = root_of(depth + 1) + "s/"      # rank/ → ../s/；rank/day/ → ../../s/
    js = """
var WBI=%s, WBP=%s;
function wbHit(v){
  v=v.trim().toLowerCase(); if(!v) return [];
  var r=[];
  for(var i=0;i<WBI.length;i++){
    var c=WBI[i][0], n=WBI[i][1].toLowerCase(), k=-1;
    if(v===c||v===n)k=0; else if(c.indexOf(v)===0)k=2; else if(n.indexOf(v)===0)k=3;
    else if(c.indexOf(v)>=0||n.indexOf(v)>=0)k=4;
    if(k>=0)r.push([k,i]);
  }
  r.sort(function(a,b){return a[0]-b[0]||a[1]-b[1]});
  return r.slice(0,12).map(function(x){return WBI[x[1]]});
}
function wbSug(){
  var d=document.getElementById("wbd"), v=document.getElementById("wbq").value;
  if(!v.trim()){d.style.display="none";return}
  var hs=wbHit(v), h;
  if(hs.length){
    h=hs.map(function(e){return '<a href="'+WBP+e[0]+'/">'+e[0]+' '+e[1]+'</a>'}).join("");
  }else{
    h='<span class="wbnone">没有匹配</span>';
  }
  d.innerHTML=h; d.style.display="block";
}
function wbSearchGo(){
  var hs=wbHit(document.getElementById("wbq").value);
  if(hs.length)location.href=WBP+hs[0][0]+"/";
  return false;
}
document.addEventListener("click",function(e){
  var d=document.getElementById("wbd");
  if(d&&!d.contains(e.target))d.style.display="none";
});
""" % (json.dumps(idx, ensure_ascii=False), json.dumps(prefix))
    return (
        '<form class="search" action="#" onsubmit="return wbSearchGo()">'
        '<input id="wbq" name="q" placeholder="输入代码或中文名，例如 002172 / 澳洋健康" '
        'autocomplete="off" oninput="wbSug()" onfocus="wbSug()">'
        '<button type="submit">搜索</button>'
        '<div id="wbd"></div></form>'
        "<style>#wbd{display:none;position:absolute;z-index:9;left:0;right:0;top:100%;"
        "background:var(--bg,#fff);border:1px solid var(--line,#ddd);border-radius:8px;"
        "max-height:300px;overflow:auto}"
        "#wbd a{display:block;padding:7px 12px;text-decoration:none}"
        '#wbd .wbnone{padding:8px 12px;opacity:.6}</style>'
        "<script>__WBJ__</script>".replace("__WBJ__", js)
    )


def _concept_data_js(stocks: dict) -> str:
    """概念 → 成员（代码+名称），给 concept 页的 ?c= 详情卡用。"""
    cons: dict = {}
    for c, e in stocks.items():
        for t in scoring.tags_of(e):
            cons.setdefault(t, []).append([c, e.get("name") or c])
    for v in cons.values():
        v.sort()
    return json.dumps(cons, ensure_ascii=False)


_RE_FORM = re.compile(r'<form class="search".*?</form>', re.S)


def put(dirpath: str, html: str, depth: int, stocks: dict = None,
        concept_js: bool = False):
    os.makedirs(dirpath, exist_ok=True)
    html = rewrite(html, depth)
    if stocks is not None:                       # rank 页：替换搜索表单
        html = _RE_FORM.sub(lambda _: _search_widget(depth, stocks), html, count=1)
    if concept_js:                               # concept 页：注入 ?c= 详情脚本
        js = """
var WBC=%s;
(function(){
  var q=new URLSearchParams(location.search).get("c");
  if(!q)return;
  var ms=WBC[q], box=document.createElement("div");
  box.className="card";
  if(ms){
    box.innerHTML="<h2>"+q+"<span>"+ms.length+" 只成分</span></h2>"+
      ms.map(function(m){return '<a class="sl" href="../s/'+m[0]+'/">'+m[1]+' '+m[0]+'</a>'}).join(" ");
  }else{
    box.innerHTML="<h2>"+q+"</h2>"+'<div class="empty">当前榜单里没有这个概念</div>';
  }
  var c0=document.querySelector(".card");
  if(c0)c0.parentNode.insertBefore(box,c0);
})();
""" % _concept_data_js(stocks or {})
        html = html.replace("</body>", "<script>%s</script></body>" % js, 1)
    with open(os.path.join(dirpath, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def _404() -> str:
    return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>404 · A 股全景</title>"
            '<script>(function(){var segs=location.pathname.split("/").filter(Boolean);'
            'var KNOWN=["rank","concept","drivers","industry","attr","brief","s","snapshot"];'
            'var root="/";for(var i=0;i<segs.length;i++){'
            'if(KNOWN.indexOf(segs[i])<0){root="/"+segs.slice(0,i+1).join("/")+"/";break}}'
            'document.write(\'<meta http-equiv="refresh" content="0;url=\'+root+\'">\')})();'
            "</script></head><body style=\"font-family:system-ui;padding:40px\">"
            "<h2>404</h2><p>这个路径在静态版里不存在，正在带你回首页……</p></body></html>")


def main():
    data, meta = store.load_bundle()
    if not data:
        sys.exit("data/live/bundle.json 不存在，先跑 refresh.py")
    stocks = data.get("stocks") or {}
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)
    open(os.path.join(DIST, ".nojekyll"), "w").close()
    with open(os.path.join(DIST, "404.html"), "w", encoding="utf-8") as f:
        f.write(_404())

    n = 0
    # ---- 首页 + 历史快照（snapshot_job 侧）
    from serve import build_home
    dates = store.snapshot_dates()
    for d in dates:
        snap, hist, dv, pk, sc = build_home(d)
        if not snap:
            continue
        base = "/snapshot/%s" % d if d != dates[-1] else "/"
        depth = 2 if d != dates[-1] else 0
        out = os.path.join(DIST, "snapshot", d) if d != dates[-1] else DIST
        put(out, page_home.render(snap, hist, dv, pk, sc=sc, base=base), depth)
        n += 1
    if not dates:
        sys.exit("没有快照，先跑 snapshot_job.py")

    # ---- 榜单（hour 默认 + day）＋ 客户端搜索
    put(os.path.join(DIST, "rank"), page_rank.render(data, meta, tab=""), 1, stocks)
    put(os.path.join(DIST, "rank", "day"),
        page_rank.render(data, meta, hot="day", tab="hot"), 2, stocks)
    n += 2

    # ---- 概念（单页 + ?c= 客户端详情）
    put(os.path.join(DIST, "concept"),
        page_concept.render(data, meta), 1, stocks, concept_js=True)
    n += 1

    # ---- 其余栏目
    rd, _ = store.load_reasons()
    put(os.path.join(DIST, "drivers"), page_drivers.render(data, meta, rd=rd), 1)
    n += 1
    put(os.path.join(DIST, "industry"), page_industry.render(data, meta), 1)
    n += 1
    at, _ = store.load_attr()
    put(os.path.join(DIST, "attr"), page_attr.render(at, rd=rd), 1)
    n += 1
    br, _ = store.load_brief()
    put(os.path.join(DIST, "brief"), page_brief.render(br), 1)
    n += 1

    # ---- 个股详情
    for c, e in stocks.items():
        put(os.path.join(DIST, "s", c), page_stock.render(c, e, data, meta), 2)
        n += 1

    # ---- 补齐「被链接但不在池内」的个股页（归因页等会链到涨停池股票；
    #      动态版 page_stock.render 支持 e=None 出占位，静态版同样补上，不留 404）
    extra = set()
    for dp, _, fns in os.walk(DIST):
        for fn in fns:
            if not fn.endswith(".html"):
                continue
            with open(os.path.join(dp, fn), encoding="utf-8") as f:
                for m in re.finditer(r'href="(?:\.\./)+s/(\d{6})/"', f.read()):
                    extra.add(m.group(1))
    for c in sorted(extra - set(stocks)):
        put(os.path.join(DIST, "s", c), page_stock.render(c, None, data, meta), 2)
        n += 1

    size = sum(os.path.getsize(os.path.join(dp, fn))
               for dp, _, fns in os.walk(DIST) for fn in fns)
    print("dist/ 共 %d 页，%.1f MB" % (n, size / 1048576))


if __name__ == "__main__":
    main()
