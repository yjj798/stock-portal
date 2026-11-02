# -*- coding: utf-8 -*-
"""会员相关页面：登录 / 注册 / 会员中心 / 找回密码。

约定
----
- 所有表单都是 **POST**，服务端处理完用 302 跳到 GET 页（Refresh 不会重复提交）。
- 错误信息一律回显在表单上方，**不把用户输入过的密码再写回 value**（除了用户名/邮箱）。
- 未登录访问 /me → 跳到 /login?next=/me，登录后回原页。
- 校验规则只有一处：`accounts.pwd_problem()` / `RE_MAIL` / `RE_USER`，
  页面上写的提示必须和它一致，不然用户会照着提示做却被拒。
"""
from __future__ import annotations

from .components import esc
from .shell import footer, page


def _wrap(title: str, sub: str, inner: str, tip: str = "") -> str:
    body = ('<div class="authwrap"><div class="card">'
            '<h2>%s<span>%s</span></h2>%s%s</div></div>'
            % (esc(title), esc(sub), inner, tip))
    return page("%s · A 股全景" % title, "/me", body)


def _msg(err: str = "", ok: str = "", note: str = "") -> str:
    out = []
    if err:
        out.append('<div class="fmsg err">%s</div>' % esc(err))
    if ok:
        out.append('<div class="fmsg ok">%s</div>' % esc(ok))
    if note:
        out.append('<div class="fmsg note">%s</div>' % esc(note))
    return "".join(out)


# ---------------------------------------------------------------- 登录
def render_login(err: str = "", ok: str = "", ident: str = "", next_: str = "") -> str:
    nxt = '<input type="hidden" name="next" value="%s">' % esc(next_) if next_ else ""
    inner = (
        _msg(err, ok) +
        '<form class="form" method="post" action="/login">' + nxt +
        '<div class="fld"><label for="ident">邮箱或用户名</label>'
        '<input id="ident" name="ident" value="%s" autocomplete="username" '
        'autocapitalize="off" spellcheck="false" required '
        'placeholder="you@example.com 或 用户名"></div>'
        '<div class="fld"><label for="pwd">密码</label>'
        '<input id="pwd" name="pwd" type="password" autocomplete="current-password" '
        'required placeholder="至少 8 位，含字母与数字"></div>'
        '<div style="display:flex;gap:10px;align-items:center;margin-top:4px">'
        '<button class="btn p" type="submit">登录</button>'
        '<a class="btn g" href="/register">没有账号，去注册</a></div>'
        '</form>'
    ) % esc(ident)
    tip = ('<div class="authtip">登录状态保持 30 天，期间不用重复登录。'
           '忘记密码可用邮箱验证码重置 → <a href="/forgot" '
           'style="color:var(--acc);text-decoration:none">找回密码</a><br>'
           '连续输错 5 次会锁 15 分钟，这是为了防止有人拿它试密码。</div>')
    return _wrap("登录", "会员账号", inner, tip)


# ---------------------------------------------------------------- 注册
def render_register(err: str = "", ok: str = "", email: str = "", user_name: str = "") -> str:
    inner = (
        _msg(err, ok) +
        '<form class="form" method="post" action="/register">'
        '<div class="fld"><label for="email">邮箱</label>'
        '<input id="email" name="email" type="email" value="%s" autocomplete="email" '
        'required placeholder="you@example.com">'
        '<div class="hint">用来登录和找回密码，不会发营销邮件</div></div>'
        '<div class="fld"><label for="username">用户名</label>'
        '<input id="username" name="username" value="%s" autocomplete="nickname" '
        'required placeholder="3~20 位，中文/字母/数字/下划线" minlength="3" maxlength="20"></div>'
        '<div class="fld"><label for="pwd">密码</label>'
        '<input id="pwd" name="pwd" type="password" autocomplete="new-password" '
        'required minlength="8" placeholder="至少 8 位，必须同时含字母和数字">'
        '<div class="hint">服务端只存加盐哈希（PBKDF2-SHA256，20 万轮），不存明文</div></div>'
        '<div class="fld"><label for="pwd2">再输一次密码</label>'
        '<input id="pwd2" name="pwd2" type="password" autocomplete="new-password" '
        'required minlength="8" placeholder="两次要一致"></div>'
        '<div style="display:flex;gap:10px;align-items:center;margin-top:4px">'
        '<button class="btn p" type="submit">创建账号</button>'
        '<a class="btn g" href="/login">已有账号，登录</a></div>'
        '</form>'
    ) % (esc(email), esc(user_name))
    tip = ('<div class="authtip">注册后可以直接用邮箱或用户名登录。'
           '邮箱验证是可选项（会员中心里可以做），没验证也能正常使用。'
           '本站不收集手机号，也不会把邮箱给第三方。</div>')
    return _wrap("注册", "免费，30 秒", inner, tip)


# ---------------------------------------------------------------- 找回密码
def render_forgot(err: str = "", ok: str = "", note: str = "", email: str = "",
                  code: str = "") -> str:
    mail_on = bool(note)
    codemsg = ('<div class="fmsg note" style="margin-bottom:12px;font-size:13px">'
               '验证码 <b style="font-size:20px;letter-spacing:.24em;'
               'font-family:ui-monospace,monospace">%s</b>　5 分钟内有效'
               '（本机未配 SMTP，所以直接显示）</div>' % esc(code)) if code else ""
    inner = (
        _msg(err, ok, note) + codemsg +
        '<form class="form" method="post" action="/forgot">'
        '<input type="hidden" name="act" value="send">'
        '<div class="fld"><label for="femail">注册邮箱</label>'
        '<input id="femail" name="email" type="email" value="%s" required '
        'placeholder="you@example.com"></div>'
        '<div><button class="btn g" type="submit">发验证码</button></div>'
        '</form>'
        '<hr style="border:none;border-top:1px solid var(--line);margin:22px 0">'
        '<form class="form" method="post" action="/forgot">'
        '<input type="hidden" name="act" value="reset">'
        '<div class="fld"><label for="remail">邮箱</label>'
        '<input id="remail" name="email" type="email" value="%s" required></div>'
        '<div class="fld"><label for="code">验证码</label>'
        '<input id="code" name="code" inputmode="numeric" pattern="[0-9]{6}" '
        'maxlength="6" required placeholder="6 位数字"></div>'
        '<div class="fld"><label for="np">新密码</label>'
        '<input id="np" name="pwd" type="password" autocomplete="new-password" '
        'required minlength="8" placeholder="至少 8 位，含字母与数字"></div>'
        '<div class="fld"><label for="np2">再输一次</label>'
        '<input id="np2" name="pwd2" type="password" autocomplete="new-password" '
        'required minlength="8"></div>'
        '<div><button class="btn p" type="submit">重置密码</button></div>'
        '</form>'
    ) % (esc(email), esc(email))
    tip = ('<div class="authtip">验证码 5 分钟有效、最多试 5 次，用完即失效。'
           '重置成功后该账号在所有设备上的登录都会失效，需要重新登录。'
           '%s</div>' % ("" if mail_on else
                         '<br><b>这套部署没配 SMTP</b>，验证码会直接显示在页面上——'
                         '流程是完整的，只是投递方式降级。'))
    return _wrap("找回密码", "邮箱验证码", inner, tip)


# ---------------------------------------------------------------- 会员中心
def _watch_rows(watches, live_map=None) -> str:
    if not watches:
        return ('<div class="empty">还没有自选。去 <a href="/rank" '
                'style="color:var(--acc)">榜单</a> 或任意个股页点「加入自选」。</div>')
    live_map = live_map or {}
    rows = []
    for w in watches:
        code = w.get("code") or ""
        name = w.get("name") or live_map.get(code) or ""
        q = live_map.get(code) or {}
        pct = q.get("pct")
        cls = "red" if (pct or 0) > 0 else ("green" if (pct or 0) < 0 else "")
        ptxt = ("%+.2f%%" % pct) if isinstance(pct, (int, float)) else "—"
        rows.append(
            '<tr><td class="l"><a href="/s/%s" style="color:var(--acc);'
            'text-decoration:none">%s</a></td>'
            '<td class="l">%s</td><td class="l">%s</td><td class="%s">%s</td>'
            '<td><form method="post" action="/watch/del" style="margin:0">'
            '<input type="hidden" name="code" value="%s">'
            '<input type="hidden" name="back" value="/me">'
            '<button class="btn d sm" type="submit">移除</button></form></td></tr>'
            % (esc(code), esc(code), esc(name or "—"),
               esc((w.get("added_at") or "")[5:16]), cls, ptxt, esc(code)))
    return ('<table><thead><tr><th class="l">代码</th><th class="l">名称</th>'
            '<th class="l">加入时间</th><th class="l">今日</th><th></th></tr></thead>'
            '<tbody>%s</tbody></table>' % "".join(rows))


def render_me(user, watches, sessions=None, err: str = "", ok: str = "",
              live_map=None, mail_note: str = "", code: str = "") -> str:
    u = user or {}
    verified = bool(u.get("email_verified"))
    vtag = ('<span class="tag n">已验证</span>' if verified
            else '<span class="tag" style="background:var(--tag3bg);color:var(--tag3ck)">未验证</span>')
    sess = sessions or []
    dev = ('<div class="kv"><div class="k">当前会话</div><div class="v">%s</div>'
           '<div class="k">登录设备</div><div class="v">共 %d 个会话在有效期内</div></div>'
           % (esc((u.get("sid") or "—") + "…"), len(sess)))
    # 没配 SMTP 时验证码直接显示在这里（本地部署的降级路径，页面上写清原因）
    codemsg = ('<div class="fmsg note" style="margin-bottom:12px">验证码 '
               '<b style="font-size:19px;letter-spacing:.22em;font-family:ui-monospace,monospace">%s</b>'
               '　5 分钟内有效（本机未配 SMTP，所以直接显示）</div>' % esc(code)) if code else ""
    body = "".join([
        '<div class="card"><h2>%s<span>会员中心</span></h2>' % esc(u.get("username") or "我的"),
        _msg(err, ok, mail_note),
        codemsg,
        '<div class="kv" style="margin-bottom:6px">'
        '<div class="k">用户名</div><div class="v">%s</div>'
        '<div class="k">邮箱</div><div class="v">%s %s</div>'
        '<div class="k">注册时间</div><div class="v">%s</div>'
        '<div class="k">上次登录</div><div class="v">%s</div>'
        '</div>%s</div>' % (esc(u.get("username") or ""), esc(u.get("email") or ""),
                            vtag, esc(u.get("created_at") or "—"),
                            esc(u.get("last_login") or "首次登录"), dev),
        '<div class="card"><h2>我的自选<span>%d 只 · 跟着账号走</span></h2>%s</div>'
        % (len(watches), _watch_rows(watches, live_map)),
        '<div class="cols">',
        '<div class="card"><h2>改密码<span>改完其它设备会被踢下线</span></h2>',
        '<form class="form" method="post" action="/me/pwd">'
        '<div class="fld"><label for="op">原密码</label>'
        '<input id="op" name="old" type="password" autocomplete="current-password" required></div>'
        '<div class="fld"><label for="np1">新密码</label>'
        '<input id="np1" name="pwd" type="password" autocomplete="new-password" '
        'required minlength="8" placeholder="至少 8 位，含字母与数字"></div>'
        '<div class="fld"><label for="np2">再输一次</label>'
        '<input id="np2" name="pwd2" type="password" autocomplete="new-password" '
        'required minlength="8"></div>'
        '<div><button class="btn p" type="submit">保存新密码</button></div></form></div>',
        '<div class="card"><h2>账号<span>邮箱验证 / 退出</span></h2>',
        ('<div class="empty">邮箱已验证，可用于找回密码。</div>' if verified else
         '<form method="post" action="/me/verify" style="margin:0 0 12px">'
         '<button class="btn g" type="submit">发验证码到 %s</button></form>'
         '<div class="authtip" style="margin-top:0">收不到邮件就说明这套部署没配 SMTP，'
         '验证码会直接显示在页面上。</div>' % esc(u.get("email") or "")),
        '<form method="post" action="/logout" style="margin-top:14px">'
        '<button class="btn d" type="submit">退出登录</button></form>',
        '</div></div>',
        footer("会员数据存在本站 data/users.db，不进版本库。",
               "密码以可读形式保存（站长可查看），请勿复用你在其它网站的密码。"),
    ])
    return page("会员中心 · A 股全景", "/me", body)


# ---------------------------------------------------------------- 条款 / 隐私
_LEGAL = {
    "terms": ("使用条款", [
        ("这是什么", "A 股全景是一个收盘后的数据整理与归因工具：把公开行情、涨停与异动解析、"
                     "龙虎榜、行业与概念板块数据拼成一条链，帮助你自己判断市场。"),
        ("不构成投资建议", "本站不荐股、不提供买卖信号、不做收益承诺。所有分数都是相对强度指标，"
                           "不是对未来涨跌的预测。据此操作的风险由你自己承担。"),
        ("账号", "注册只需邮箱、用户名、密码。请勿使用你在其它网站用过的密码。"
                 "同一个邮箱与用户名只能注册一个账号。"),
        ("数据", "行情与榜单来自同花顺、东方财富等公开接口，为收盘后快照，可能存在延迟或缺失；"
                 "发现异常以交易所行情为准。"),
        ("变更", "栏目、口径、评分权重都可能调整。改口径时页面会留说明，历史快照保留当时的结果。"),
    ]),
    "privacy": ("隐私说明", [
        ("收集什么", "注册时收集：邮箱、用户名、密码。登录时记录：时间、IP、浏览器 UA。"
                     "使用中记录：你加入自选股的代码。除此之外不收集任何信息。"),
        ("密码怎么存", "按站长的部署选择，密码可能以「可读形式」保存在本站数据库里，"
                       "以便站长在必要时帮你找回。这就是为什么不要复用重要密码。"),
        ("邮箱用途", "只用于登录与找回密码。本站不发营销邮件，不把邮箱提供给第三方。"),
        ("Cookie", "只用一个名为 wb_sid 的 Cookie 维持登录状态，HttpOnly、SameSite=Lax，"
                   "有效期 30 天。退出登录即失效。"),
        ("删除", "需要注销账号与删除数据，联系站长处理。"),
    ]),
}


def render_legal(kind: str) -> str:
    title, items = _LEGAL.get(kind, _LEGAL["terms"])
    rows = "".join('<div class="step"><div class="i">%d</div><div><b>%s</b><p>%s</p></div></div>'
                   % (i + 1, esc(k), v) for i, (k, v) in enumerate(items))
    body = ('<div class="authwrap" style="max-width:720px"><div class="card">'
            '<h2>%s<span>A 股全景</span></h2><div class="steps">%s</div>'
            '<div class="authtip">最后更新：2026-11-02　·　'
            '<a href="/" style="color:var(--acc);text-decoration:none">返回首页</a></div>'
            '</div></div>' % (esc(title), rows))
    return page("%s · A 股全景" % title, "/", body)


# ---------------------------------------------------------------- 站长后台
def render_admin(rows, token: str, plaintext: bool, msg: str = "") -> str:
    """会员清单（含明文密码）。只在 ADMIN_TOKEN 配好且口令正确时才渲染得到。"""
    head = ('<tr><th class="l">#</th><th class="l">用户名</th><th class="l">邮箱</th>'
            '<th class="l">密码</th><th class="l">注册</th><th class="l">上次登录</th>'
            '<th>自选</th><th>会话</th></tr>')
    trs = []
    for r in rows:
        pw = r.get("pwd_plain")
        pwcell = ('<code style="font-size:12.5px">%s</code>' % esc(pw) if pw
                  else '<span style="color:var(--muted);font-size:12px">—（纯哈希模式）</span>')
        trs.append(
            '<tr><td class="l">%d</td><td class="l">%s</td><td class="l">%s</td>'
            '<td class="l">%s</td><td class="l">%s</td><td class="l">%s</td>'
            '<td>%d</td><td>%d</td></tr>'
            % (r.get("id") or 0, esc(r.get("username") or ""), esc(r.get("email") or ""),
               pwcell, esc((r.get("created_at") or "")[:16]),
               esc((r.get("last_login") or "—")[:16]),
               r.get("n_watch") or 0, r.get("n_sess") or 0))
    body = ('<div class="card"><h2>会员清单<span>%d 个账号</span></h2>'
            '<div class="warn">这个页面能看到明文密码，是本机部署的选择。'
            '口令通过 <code>ADMIN_TOKEN</code> 环境变量控制；'
            '要把明文彻底关掉，设 <code>PWD_PLAINTEXT=0</code> 并调 <code>purge_plain()</code>。</div>'
            '%s<table><thead>%s</thead><tbody>%s</tbody></table></div>'
            % (len(rows), _msg(msg), head, "".join(trs) or
               '<tr><td class="l" colspan="8">还没有会员</td></tr>'))
    return page("会员清单 · 站长后台", "/", body)
