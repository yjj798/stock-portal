# -*- coding: utf-8 -*-
"""首页：DeepSeek 登录页式布局 + 系统介绍。

版式（2026-11-02 用户指定「仿照 platform.deepseek.com/sign_in」）
---------------------------------------------------------------
    ┌ 品牌（居中：标记 + 站名 + 一句话）
    ├ 登录卡（居中，宽 400：账号密码两栏 + 全宽主按钮 + 忘记密码 / 注册）
    ├ 一行协议与免责（小字，居中，DeepSeek 那句的位置）
    ├ 分隔线
    └ 介绍区（这个系统在答什么问题 / 九个栏目 / 分数怎么来）

为什么登录卡在介绍之前
----------------------
DeepSeek 那页的动线是「先给我登录，别讲太多」。所以表单必须第一屏可见、不用滚，
介绍退到第二屏——老用户直接登录走人，新用户往下滑一段就明白这是什么站。

不做的事
--------
- 没有微信 / QQ / 手机号登录：用户明确要求只要账号密码（+ 邮箱找回）。
- 不放「AI 智能选股」「稳赚」这类话：站里没有这些能力，写了就是骗人。
- 不藏免责：不荐股、不构成投资建议那句放在首屏协议行里，不用小字糊过去。
"""
from __future__ import annotations

from .components import esc
from .shell import footer, page

FEATURES = [
    ("/board", "总览", "复盘",
     "情绪温度、连板梯队、封板率、赚钱效应、明日观察池。回答「今天能干活还是该收手」。"),
    ("/theme", "主线", "消息面",
     "把全市场涨停、龙虎榜、热榜的异动解析原文读一遍，数出今天在炒哪条消息。"),
    ("/rank", "榜单", "个股评分",
     "120 分制，每只票都能点进去看这分是怎么一项项加出来的。"),
    ("/industry", "行业", "产业",
     "496 个行业指数：涨幅分位、上涨广度、主力净额，分开「只有行业热」与「双轮」。"),
    ("/concept", "题材", "故事",
     "531 个概念板块，与行业同一套算法、同一张表，防宽板块刷分。"),
    ("/drivers", "驱动词", "归因",
     "把上榜原因拆成词，看哪些词反复出现在涨停票上。"),
    ("/attr", "归因", "涨停 / 炸板",
     "今日涨停与炸板逐只归因，行业原因与公司原因都是原文。"),
    ("/brief", "简报", "复盘文字",
     "自动生成的当日复盘底稿：情绪、主线、梯队、明日关注。"),
    ("/rank", "个股", "单票全景",
     "从榜单或搜索点进任意一只票：趋势、概念与行业全链、消息面归属、异动原文、评分拆解。"),
]

SCORE_ROWS = [
    ("趋势 35", "近 20 日人气排名斜率 + 单调性 + 位置"),
    ("概念 25", "归并后的主线标签强度 + 上升广度"),
    ("上榜原因 20", "同花顺写的上榜理由，按词频与集中度折算"),
    ("资金 20", "成交额、换手率、龙虎榜净买分位"),
    ("行业 14", "最细一级行业在 496 个行业里的涨幅 / 广度 / 净额分位"),
    ("双轮 6", "行业热与概念热同时成立才给，单边刻意 0 分"),
]

CSS_LOCAL = """
.brandblk{text-align:center;padding:34px 0 20px}
.bmark{width:44px;height:44px;border-radius:12px;margin:0 auto 12px;
  background:linear-gradient(135deg,var(--up) 0%,#e8804a 55%,var(--acc) 100%);
  display:flex;align-items:center;justify-content:center;color:#fff;
  font-weight:800;font-size:19px;letter-spacing:-.04em}
.bname{font-size:21px;font-weight:800;letter-spacing:-.01em;margin:0}
.bsub{font-size:12.5px;color:var(--muted);margin:6px 0 0}
.authbox{max-width:400px;margin:0 auto}
.authcard{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:26px 26px 22px;box-shadow:0 1px 2px rgba(16,24,40,.04),0 12px 32px -20px rgba(16,24,40,.28)}
.authcard h2{font-size:19px;margin:0 0 18px;display:block;font-weight:700}
.ifld{margin-bottom:12px;position:relative}
.ifld input{width:100%;font:inherit;font-size:14.5px;padding:12px 14px;border-radius:10px;
  border:1px solid transparent;background:var(--soft);color:var(--ink)}
.ifld input:focus{outline:none;background:var(--card);border-color:var(--acc);
  box-shadow:0 0 0 3px rgba(37,99,235,.13)}
.ifld input::placeholder{color:var(--muted);opacity:.8}
.ifld .eye{position:absolute;right:6px;top:50%;transform:translateY(-50%);border:0;
  background:transparent;color:var(--muted);font-size:12px;padding:6px 8px;cursor:pointer;border-radius:6px}
.ifld .eye:hover{color:var(--ink);background:var(--hover)}
.wbtn{width:100%;font:inherit;font-size:14.5px;font-weight:600;padding:12px;border-radius:10px;
  border:1px solid transparent;background:var(--acc);color:#fff;cursor:pointer;margin-top:4px}
.wbtn:hover{filter:brightness(1.07)}
.arow{display:flex;justify-content:space-between;align-items:center;margin-top:14px;font-size:13px}
.arow a{color:var(--muted);text-decoration:none}
.arow a:hover{color:var(--acc)}
.arow a.b{color:var(--acc);font-weight:600}
.legal{font-size:11.5px;color:var(--muted);text-align:center;line-height:1.85;
  max-width:460px;margin:16px auto 0}
.legal a{color:var(--t2);text-decoration:none;border-bottom:1px dashed var(--slb)}
.legal b{color:var(--t2);font-weight:600}
.hello{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:24px 26px;max-width:400px;margin:0 auto;text-align:center}
.hello .who{font-size:16px;font-weight:700;margin:2px 0 4px}
.hello .em{font-size:12px;color:var(--muted);word-break:break-all}
.hello .acts{display:flex;gap:8px;justify-content:center;margin-top:16px;flex-wrap:wrap}
.sep{display:flex;align-items:center;gap:14px;max-width:520px;margin:38px auto 26px;
  font-size:11.5px;color:var(--muted);letter-spacing:.16em}
.sep::before,.sep::after{content:"";flex:1;height:1px;background:var(--line)}
.l3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px}
@media(max-width:760px){.l3{grid-template-columns:1fr}}
.nine{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
@media(max-width:900px){.nine{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.nine{grid-template-columns:1fr}}
.nine a{display:block;background:var(--card);border:1px solid var(--line);border-radius:11px;
  padding:12px 14px;text-decoration:none;color:inherit}
.nine a:hover{background:var(--hover);border-color:var(--srchb)}
.nine .t{font-size:13.5px;font-weight:700;color:var(--ink)}
.nine .t i{font-style:normal;font-size:11px;font-weight:400;color:var(--muted);margin-left:6px}
.nine .d{font-size:12px;color:var(--t2);line-height:1.65;margin-top:4px}
.sgrid{display:grid;grid-template-columns:1fr 1fr;gap:0 26px}
@media(max-width:760px){.sgrid{grid-template-columns:1fr}}
.sline{display:grid;grid-template-columns:96px 1fr;gap:10px;padding:8px 0;
  border-top:1px solid var(--line);font-size:12.5px}
.sline:first-child{border-top:0}
.sline b{font-weight:700;font-size:12.5px}
.sline span{color:var(--t2);line-height:1.6}
"""


def _num(data, key) -> int:
    try:
        v = (data or {}).get(key)
        if isinstance(v, dict):
            return len(v)
        if isinstance(v, (list, tuple)):
            return len(v)
        return int(v or 0)
    except Exception:                       # noqa: BLE001
        return 0


def _brand() -> str:
    return ('<div class="brandblk">'
            '<div class="bmark">A</div>'
            '<p class="bname">A 股全景</p>'
            '<p class="bsub">收盘后的情绪、主线与归因 · 数据可复核</p>'
            '</div>')


def _auth_card(err: str = "", ok: str = "", next_: str = "/board") -> str:
    msg = ""
    if err:
        msg = '<div class="fmsg err" style="margin-bottom:12px">%s</div>' % esc(err)
    elif ok:
        msg = '<div class="fmsg ok" style="margin-bottom:12px">%s</div>' % esc(ok)
    nxt = '<input type="hidden" name="next" value="%s">' % esc(next_)
    return (
        '<div class="authbox"><div class="authcard">'
        '<h2>登录</h2>'
        '<form method="post" action="/login">' + nxt + msg +
        '<div class="ifld"><input name="ident" autocomplete="username" required '
        'autocapitalize="off" spellcheck="false" placeholder="邮箱或用户名" '
        'aria-label="邮箱或用户名"></div>'
        '<div class="ifld"><input id="hp" name="pwd" type="password" required '
        'autocomplete="current-password" placeholder="密码" aria-label="密码">'
        '<button class="eye" type="button" onclick="wbEye()" aria-label="显示密码">显示</button></div>'
        '<button class="wbtn" type="submit">登录</button>'
        '<div class="arow"><a href="/forgot">忘记密码？</a>'
        '<a class="b" href="/register">注册账号 →</a></div>'
        '</form></div></div>'
        '<script>function wbEye(){var i=document.getElementById("hp"),'
        'b=i.nextElementSibling,on=i.type==="password";'
        'i.type=on?"text":"password";b.textContent=on?"隐藏":"显示"}</script>'
    )


def _hello(user) -> str:
    name = esc(user.get("username") or "")
    mail = esc(user.get("email") or "")
    return ('<div class="hello">'
            '<div style="font-size:12px;color:var(--muted)">已登录</div>'
            '<div class="who">%s</div><div class="em">%s</div>'
            '<div class="acts"><a class="btn p" href="/board">进总览</a>'
            '<a class="btn g" href="/me">我的自选</a>'
            '<form method="post" action="/logout" style="margin:0">'
            '<button class="btn g" type="submit">退出</button></form></div>'
            '</div>' % (name, mail))


def _intro(data) -> str:
    qd = (data or {}).get("quote_date") or "—"
    cells = (
        '<div class="grid4" style="margin-bottom:14px">'
        '<div class="cell"><div class="k">行情日</div><div class="v" style="font-size:16px">%s</div>'
        '<div class="n">收盘后 15:10 / 16:00 两轮更新</div></div>'
        '<div class="cell"><div class="k">人气池</div><div class="v">%d</div>'
        '<div class="n">只 · 近几日被反复关注</div></div>'
        '<div class="cell"><div class="k">全市场涨停</div><div class="v">%d</div>'
        '<div class="n">只 · 含人气池外</div></div>'
        '<div class="cell"><div class="k">异动解析</div><div class="v">%d</div>'
        '<div class="n">只 · 逐只读涨停原因原文</div></div>'
        '</div>' % (esc(str(qd)), _num(data, "stocks"), _num(data, "zt_pool"),
                    _num(data, "abnormal")))
    three = (
        '<div class="l3">'
        '<div class="lcard"><div class="n">问题一</div><h3>今天该不该动手</h3>'
        '<p>情绪温度由封板率、首板晋级率、涨停家数、连板高度、上涨占比五项加权，'
        '分五档。退潮期再好的票也容易一日游。</p></div>'
        '<div class="lcard"><div class="n">问题二</div><h3>今天在炒哪条消息</h3>'
        '<p>把涨停、龙虎榜、热榜里每只票的异动解析原文读一遍，数出关键词与主线，'
        '不是靠人预设的词表去猜。</p></div>'
        '<div class="lcard"><div class="n">问题三</div><h3>这只票为什么涨</h3>'
        '<p>趋势排名、概念与行业标签全链、消息面归属、异动原文、资金构成，'
        '每一分都能倒推回原始数据。</p></div>'
        '</div>')
    return '<div class="sep">这个系统在回答什么</div>' + three + cells


def _features() -> str:
    cards = "".join(
        '<a href="%s"><div class="t">%s<i>%s</i></div><div class="d">%s</div></a>'
        % (esc(h), esc(n), esc(k), esc(d)) for h, n, k, d in FEATURES)
    return ('<div class="card"><h2>九个栏目<span>从情绪到单票，一条链走完</span></h2>'
            '<div class="nine">%s</div></div>' % cards)


def _score() -> str:
    lines = "".join('<div class="sline"><b>%s</b><span>%s</span></div>' % (esc(a), esc(b))
                    for a, b in SCORE_ROWS)
    return ('<div class="card"><h2>个股分数怎么来<span>满分 120</span></h2>'
            '<div class="sgrid">%s</div>'
            '<div class="warn" style="margin-top:12px">分数是<b>同日相对强度</b>，'
            '不是收益预测。横着比同一天的不同票才有意义，跨日比会失真。</div></div>' % lines)


def _static_cta() -> str:
    """静态站（GitHub Pages）没有后端：登录改成外链到动态站，不出表单。

    为什么不直接保留表单：静态页 <form action="/login"> 会被改写成站内死链；
    就算指向动态站，也是跨站 POST，SameSite=Lax 下登录态能不能落地取决于浏览器，
    不如老老实实跳过去登录。
    """
    from .nav import SITE_LIVE
    live = SITE_LIVE.rstrip("/")
    return ('<div class="authbox"><div class="authcard" style="text-align:center">'
            '<h2 style="text-align:center">会员登录</h2>'
            '<p style="font-size:13px;color:var(--t2);line-height:1.8;margin:0 0 18px">'
            '这个页面是静态镜像，没有后端。<br>登录、注册、找回密码在动态站进行。</p>'
            '<a class="wbtn" style="display:block;text-decoration:none" '
            'href="%s/login">去登录</a>'
            '<div class="arow" style="justify-content:center;gap:18px">'
            '<a href="%s/register">注册账号</a>'
            '<a href="%s/forgot">忘记密码</a></div>'
            '</div></div>' % (esc(live), esc(live), esc(live)))


def render(data=None, meta=None, user=None, stats=None, err: str = "", ok: str = "",
           next_: str = "/board", static: bool = False) -> str:
    d = data or {}
    st = stats or {}
    nuser = st.get("users") or 0
    if user:
        mid = _hello(user)
        legal = ('<div class="legal">自选股跟着账号走，换设备也在。'
                 '<a href="/me">会员中心</a> 里可以改密码、做邮箱验证、退出登录。</div>')
    elif static:
        mid = _static_cta()
        legal = ('<div class="legal">这个页面是把动态站的数据静态化后的镜像，'
                 '每天收盘后自动重建。<br>'
                 '<b>本站不荐股、不提供买卖信号、不构成投资建议</b>，'
                 '数据为收盘后的公开数据，仅供研究参考。</div>')
    else:
        mid = _auth_card(err, ok, next_)
        legal = ('<div class="legal">注册登录即表示你已阅读并同意本站的'
                 '<a href="/terms">使用条款</a> 与 <a href="/privacy">隐私说明</a>；'
                 '未注册的邮箱可直接注册。<br>'
                 '<b>本站不荐股、不提供买卖信号、不构成投资建议</b>，'
                 '数据为收盘后的公开数据，仅供研究参考。'
                 + ('<br>已有 %d 个账号在用。' % nuser if nuser else "")
                 + '</div>')
    body = "".join([
        _brand(), mid, legal,
        _intro(d), _features(), _score(),
        footer("A 股全景 · 本地数据真值　行情日 %s" % (d.get("quote_date") or "—"),
               "数据来源：同花顺 / 东方财富公开接口、龙虎榜公开信息　仅供研究参考，不构成投资建议"),
    ])
    return page("A 股全景 · 收盘后的情绪、主线与归因", "/", body,
                extra_head="<style>%s</style>" % CSS_LOCAL)
