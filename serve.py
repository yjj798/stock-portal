# -*- coding: utf-8 -*-
"""本地 :888 总入口。

设计要点
--------
1. **只读本地 data/**：请求期不联网。抓取是 snapshot_job 的事，页面只负责渲染，
   这样"页面打不开"永远不可能是"上游挂了"造成的。
2. **模块级降级**：任何一个模块渲染抛异常，只把该模块换成提示条，整页照出。
   宁可见到"这块没数据"，也不给白屏。
3. **建设中栏目**：/rank /concept /drivers /attr /brief 在 P2/P3 迁移，
   现在返回带导航的说明页而不是 404——导航已上线，点进去不能是死胡同。

用法：
    python serve.py            # 127.0.0.1:888
    python serve.py 0.0.0.0    # 同网段手机也能看
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

import accounts
import store
import score as scoring
from picks import pick_stocks
from sec_core import derive, to_row, WIDE  # noqa: F401  (WIDE 供后续页面复用)
from render import (page_attr, page_auth, page_brief, page_concept, page_drivers,
                    page_home, page_industry, page_landing, page_rank, page_stock,
                    page_theme)
from render import nav as navmod
from render.components import esc
from render.nav import nav
from render.shell import no_bundle
from render.theme import CSS

COOKIE = "wb_sid"
SESS_MAX_AGE = accounts.SESS_DAYS * 86400


# ---------------------------------------------------------------- 页面构建
def build_home(date8=None):
    date8, snap = store.load_snapshot(date8)
    if not snap:
        return None, None, None, None, None
    hist = store.history_before(date8)
    # 必须把"最近一个历史日"作为 prev_row 传进去，否则首板晋级率算不出来，
    # 那 25% 权重的分项会被静默丢掉 —— 温度会整体偏低（实测 39.0 vs 正确 39.4）。
    prev = hist[-1] if hist else None
    dv = derive(snap, hist, prev)
    # 四维分（榜单页那套）也要给复盘页用：A 档的"榜单通道"靠它判断。
    # bundle 缺失时给 None，A 档退回纯共振分口径，不报错。
    sc = None
    live, _meta = store.load_bundle()
    if live:
        try:
            sc = scoring.build(live)
        except Exception:
            traceback.print_exc()
    pk = pick_stocks(snap, dv, sc)
    return snap, hist, dv, pk, sc


def safe(fn, label: str, placeholder: str = "") -> str:
    """模块级容错：出错就把这一块换成提示条，不牵连整页。"""
    try:
        return fn()
    except Exception as e:
        traceback.print_exc()
        return ('<div class="card"><h2>%s</h2><div class="warn">本模块渲染失败：%s。'
                "其余模块不受影响；数据文件在 data/snapshots/ 可直接查看。</div></div>"
                % (esc(label), esc("%s: %s" % (type(e).__name__, e))))


def page_placeholder(title: str, desc: str, todo: str) -> str:
    return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>%s · 建设中</title><style>%s</style></head><body>%s"
            '<div class="wrap"><div class="card"><h2>%s<span>迁移中</span></h2>'
            '<div class="empty">%s</div>'
            '<div class="warn">%s</div></div></div></body></html>'
            % (esc(title), CSS, nav(_active_of(title)), esc(title), esc(desc), esc(todo)))


def _active_of(title: str) -> str:
    return {"/rank": "/rank", "/concept": "/concept", "/drivers": "/drivers",
            "/attr": "/attr", "/brief": "/brief"}.get(title, "/board")


def _one(q, key: str, default: str = "") -> str:
    """从 parse_qs 的 {k: [v]} 或 _body 的 {k: v} 里取单个值，取不到给默认。"""
    if not q:
        return default
    v = q.get(key)
    if isinstance(v, list):
        return v[0] if v else default
    return default if v is None else str(v)


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "stock-portal/0.2"

    # 每个请求的登录态。do_GET/do_POST 开头都会 _boot()，之后 self.user 就是
    # 当前会员（None = 未登录）。导航栏读的是 nav 模块的请求级上下文，
    # 所以这里要顺手 set_ctx，页面里 9 个 render 都不用改签名。
    user = None
    token = ""

    def log_message(self, fmt, *args):  # 安静一点
        # 登录/注册这类 POST 不把查询串写进日志：URL 里可能带邮箱
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ---- cookie / 上下文
    def _cookies(self) -> dict:
        out = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k:
                out[k] = unquote(v)
        return out

    def _boot(self) -> None:
        """解析会话 + 设置导航上下文。任何一个入口进来都必须先跑它。"""
        self.token = self._cookies().get(COOKIE) or ""
        self.user = accounts.user_by_token(self.token) if self.token else None
        navmod.set_ctx(user=self.user, static=False)

    def _secure(self) -> bool:
        """https 下才加 Secure（本地 http://127.0.0.1 加了就收不到 cookie）。"""
        return ((self.headers.get("X-Forwarded-Proto") or "").lower() == "https")

    def _cookie_header(self, token: str, max_age: int) -> str:
        v = "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (COOKIE, token, max_age)
        return v + ("; Secure" if self._secure() else "")

    def _same_origin(self) -> bool:
        """POST 的同源校验。SameSite=Lax 已经挡掉跨站带 cookie 的 POST，
        这里再做一层 Origin 比对，防"浏览器差异 + 老客户端"两种情况。"""
        o = self.headers.get("Origin")
        if not o:
            return True
        return urlparse(o).netloc == (self.headers.get("Host") or "")

    def _send(self, code: int, body, ctype="text/html; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or []):
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False),
                   "application/json; charset=utf-8")

    def _redirect(self, loc: str, cookie: str = ""):
        self.send_response(302)
        self.send_header("Location", loc)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _qs(self, **kw) -> str:
        """拼回跳用的查询串，丢掉空值。"""
        d = {k: v for k, v in kw.items() if v}
        return ("?" + urlencode(d)) if d else ""

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        if n > 65536:                     # 表单不该这么大，直接当攻击处理
            return {}
        raw = self.rfile.read(n).decode("utf-8", "replace")
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def do_GET(self):
        raw = self.path
        u = urlparse(raw)
        path = u.path.rstrip("/") or "/"
        q = parse_qs(u.query or "")
        self._boot()
        try:
            if path == "/":
                return self._landing(q)
            if path == "/board":
                return self._home(None, q)
            if path == "/mp":
                return self._mp()
            if path == "/login":
                if self.user:
                    return self._redirect("/me")
                return self._send(200, page_auth.render_login(
                    err=_one(q, "err"), next_=_one(q, "next")))
            if path == "/register":
                if self.user:
                    return self._redirect("/me")
                return self._send(200, page_auth.render_register(err=_one(q, "err")))
            if path == "/forgot":
                return self._send(200, page_auth.render_forgot(
                    err=_one(q, "err"), ok=_one(q, "ok"), note=_one(q, "note")))
            if path == "/me":
                return self._me(q)
            if path in ("/terms", "/privacy"):
                return self._send(200, page_auth.render_legal(path[1:]))
            if path == "/admin/users":
                # 没配 ADMIN_TOKEN 就当这个页面不存在（404 而不是 403，不暴露入口）
                if not accounts.admin_ok(_one(q, "t")):
                    return self._send(404, page_placeholder(
                        "页面不存在", "没有这个路径：%s" % path, "从顶部导航进入各栏目。"))
                return self._send(200, page_auth.render_admin(
                    accounts.admin_list(), _one(q, "t"), accounts.plaintext_on()))
            if path == "/api/latest":
                return self._api_latest()
            if path == "/api/series":
                return self._json(store.load_series())
            if path.startswith("/api/snap/"):
                return self._api_snap(path.rsplit("/", 1)[-1])
            if path.startswith("/snapshot/"):
                return self._home(path.rsplit("/", 1)[-1].replace(".html", ""), q)
            if path == "/rank":
                return self._rank(q)
            if path == "/concept":
                return self._concept(q)
            if path == "/theme":
                return self._theme()
            if path == "/industry":
                return self._industry()
            if path.startswith("/s/"):
                return self._stock(path.rsplit("/", 1)[-1], q)
            if path == "/drivers":
                return self._drivers()
            if path == "/attr":
                return self._attr()
            if path == "/brief":
                return self._brief()
            if path == "/api/index":
                return self._api_index()
            return self._send(404, page_placeholder("页面不存在", "没有这个路径：%s" % path,
                                                    "从顶部导航进入各栏目。"))
        except Exception:
            traceback.print_exc()
            self._send(500, "<h1>500</h1><pre>%s</pre>"
                       % esc(traceback.format_exc()[-1500:]))

    # ---- POST：会员操作全部走这里
    def _back(self, f, default: str = "/me") -> str:
        """回跳地址只接受站内相对路径，防止被当开放重定向用。"""
        b = (f.get("back") or f.get("next") or "").strip()
        if b.startswith("/") and not b.startswith("//"):
            return b
        return default

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        self._boot()
        if not self._same_origin():
            return self._send(403, page_placeholder(
                "拒绝提交", "这个请求来自站外（Origin 不匹配）。", "回到首页重新操作。"))
        f = self._body()
        try:
            if path == "/login":
                return self._post_login(f)
            if path == "/register":
                return self._post_register(f)
            if path == "/logout":
                return self._post_logout()
            if path == "/forgot":
                return self._post_forgot(f)
            if path == "/me/pwd":
                return self._post_pwd(f)
            if path == "/me/verify":
                return self._post_verify(f)
            if path in ("/watch/add", "/watch/del"):
                return self._post_watch(path, f)
            return self._send(404, page_placeholder(
                "页面不存在", "没有这个提交地址：%s" % path, "回到首页。"))
        except Exception:
            traceback.print_exc()
            self._send(500, "<h1>500</h1><pre>%s</pre>"
                       % esc(traceback.format_exc()[-1200:]))

    def _ip(self) -> str:
        xf = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return xf or (self.client_address[0] if self.client_address else "")

    def _post_login(self, f):
        ident = (f.get("ident") or "").strip()[:120]
        pwd = f.get("pwd") or ""
        nxt = self._back(f, "/board")
        ok, res, _u = accounts.login(ident, pwd, ip=self._ip(),
                                     ua=self.headers.get("User-Agent") or "")
        if not ok:
            # 原样回填账号（方便改错别字），密码一律不回填
            return self._send(200, page_auth.render_login(err=res, ident=ident, next_=nxt))
        return self._redirect(nxt, self._cookie_header(res, SESS_MAX_AGE))

    def _post_register(self, f):
        email = (f.get("email") or "").strip()[:120]
        uname = (f.get("username") or "").strip()[:20]
        pwd = f.get("pwd") or ""
        pwd2 = f.get("pwd2") or ""
        ok, res = accounts.register(email, uname, pwd, pwd2)
        if not ok:
            return self._send(200, page_auth.render_register(err=res, email=email,
                                                             user_name=uname))
        ok, tok, _u = accounts.login(email, pwd, ip=self._ip(),
                                     ua=self.headers.get("User-Agent") or "")
        if not ok:      # 注册成功但自动登录失败（极少见）：让人工登录一次
            return self._redirect("/login" + self._qs(ok="注册成功，请登录"))
        return self._redirect("/me" + self._qs(ok="注册成功，欢迎"),
                              self._cookie_header(tok, SESS_MAX_AGE))

    def _post_logout(self):
        accounts.logout(self.token)
        return self._redirect("/", self._cookie_header("", 0))

    def _post_pwd(self, f):
        if not self.user:
            return self._redirect("/login" + self._qs(next="/me"))
        ok, why = accounts.change_pwd(self.user["id"], f.get("old") or "",
                                      f.get("pwd") or "", f.get("pwd2") or "",
                                      keep_token=self.token)
        return self._redirect("/me" + (self._qs(ok="密码已更新，其它设备已下线") if ok
                                       else self._qs(err=why)))

    def _post_verify(self, f):
        if not self.user:
            return self._redirect("/login" + self._qs(next="/me"))
        ok, msg, code = accounts.send_code(self.user.get("email") or "", "verify")
        if not ok:
            return self._redirect("/me" + self._qs(err=msg))
        return self._redirect("/me" + self._qs(note=msg, code=code))

    def _post_forgot(self, f):
        email = (f.get("email") or "").strip()[:120]
        act = (f.get("act") or "send").strip()
        if act == "send":
            ok, msg, code = accounts.send_code(email, "reset")
            if not ok:
                return self._send(200, page_auth.render_forgot(err=msg, email=email))
            return self._send(200, page_auth.render_forgot(
                ok=msg, note=msg if not code else "", email=email, code=code))
        ok, why = accounts.reset_pwd(email, f.get("code") or "",
                                     f.get("pwd") or "", f.get("pwd2") or "")
        if not ok:
            return self._send(200, page_auth.render_forgot(err=why, email=email))
        return self._redirect("/login" + self._qs(ok="密码已重置，请用新密码登录"))

    def _post_watch(self, path: str, f):
        if not self.user:
            return self._redirect("/login" + self._qs(next=self._back(f, "/rank")))
        code = (f.get("code") or "").strip()
        if path == "/watch/del":
            accounts.watch_del(self.user["id"], code)
            return self._redirect(self._back(f), "")
        name = (f.get("name") or "").strip()
        if not accounts.watch_add(self.user["id"], code, name):
            return self._redirect(self._back(f), "")
        return self._redirect(self._back(f), "")

    # ---- 会员相关页面
    def _landing(self, q):
        data, meta = store.load_bundle()
        try:
            st = accounts.stats()
        except Exception:                 # noqa: BLE001  账号库坏了不该拖垮首页
            traceback.print_exc()
            st = {}
        self._send(200, page_landing.render(data, meta, user=self.user, stats=st,
                                            err=_one(q, "err"), ok=_one(q, "ok"),
                                            next_=_one(q, "next") or "/board"))

    def _me(self, q):
        if not self.user:
            return self._redirect("/login" + self._qs(next="/me"))
        watches = accounts.watch_list(self.user["id"])
        data, _meta = store.load_bundle()
        live = data.get("stocks") or {}
        zt = {e.get("code"): e for e in (data.get("zt_pool") or [])}
        live_map = {}
        for code in {w["code"] for w in watches}:
            e = live.get(code) or zt.get(code) or {}
            if e:
                live_map[code] = {"name": e.get("name"), "pct": e.get("pct")}
        self._send(200, page_auth.render_me(
            self.user, watches, sessions=accounts.sessions_of(self.user["id"]),
            err=_one(q, "err"), ok=_one(q, "ok"), live_map=live_map,
            mail_note=_one(q, "note"), code=_one(q, "code")))

    # ---- 页面
    def _home(self, date8=None, q=None):
        snap, hist, dv, pk, sc = build_home(date8)
        if not snap:
            return self._send(200, page_placeholder(
                "暂无快照", "data/snapshots/ 里还没有任何一天的快照。",
                "先跑一次采集：python snapshot_job.py"))
        q = q or {}
        html = page_home.render(
            snap, hist, dv, pk, sc=sc,
            tab=(q.get("t") or [""])[0],
            # 分栏链接要带原路径：历史快照页是 /snapshot/20261031，写成 "/board" 会把人送回最新一天
            base=("/snapshot/%s" % date8) if date8 else "/board")
        self._send(200, html)

    def _mp(self):
        snap, hist, dv, pk, sc = build_home(None)
        if not snap:
            return self._send(404, "暂无数据")
        self._send(200, page_home.render_mp(snap, dv, pk))

    # ---- 新栏目（读 data/live/bundle.json，请求期不联网）
    def _rank(self, q):
        data, meta = store.load_bundle()
        if not data:
            return self._send(200, no_bundle())
        html = page_rank.render(data, meta,
                                q=(q.get("q") or [""])[0],
                                hot=(q.get("hot") or ["hour"])[0],
                                tab=(q.get("t") or [""])[0])
        self._send(200, html)

    def _concept(self, q):
        data, meta = store.load_bundle()
        if not data:
            return self._send(200, no_bundle())
        html = page_concept.render(data, meta, c=(q.get("c") or [""])[0])
        self._send(200, html)

    def _theme(self):
        data, meta = store.load_bundle()
        if not data:
            return self._send(200, no_bundle())
        self._send(200, page_theme.render(data, meta))

    def _industry(self):
        data, meta = store.load_bundle()
        if not data:
            return self._send(200, no_bundle())
        self._send(200, page_industry.render(data, meta))

    def _stock(self, code, q):
        data, meta = store.load_bundle()
        if not data:
            return self._send(200, no_bundle())
        c = "".join(ch for ch in str(code) if ch.isdigit())[:6]
        # 池外涨停（人气池 141 只与全市场涨停只有 43 只交集）用涨停池兜底成轻量页
        e = page_stock.entry_of(c, data)
        self._send(200, page_stock.render(c or str(code), e, data, meta))

    def _drivers(self):
        data, meta = store.load_bundle()
        rd, rmeta = store.load_reasons()
        self._send(200, page_drivers.render(data, meta, rd=rd))

    def _attr(self):
        at, _ = store.load_attr()
        rd, _ = store.load_reasons()
        self._send(200, page_attr.render(at, rd=rd))

    def _brief(self):
        br, _ = store.load_brief()
        self._send(200, page_brief.render(br))

    def _api_index(self):
        data, meta = store.load_bundle()
        if not data:
            return self._json({"ok": False, "error": "no bundle"}, 404)
        self._json({"ok": True, "meta": meta,
                    "quote_date": data.get("quote_date"),
                    "stocks": data.get("stocks")})

    # ---- API
    def _api_latest(self):
        date8, snap = store.load_snapshot(None)
        if not snap:
            return self._json({"ok": False, "error": "no snapshot"}, 404)
        hist = store.history_before(date8)
        dv = derive(snap, hist, hist[-1] if hist else None)
        pk = pick_stocks(snap, dv)
        self._json({"ok": True,
                    "last": {"trade_date": date8, "temp": dv["temp"]["score"],
                             "level": dv["temp"]["level"],
                             "degraded": snap.get("degraded") or []},
                    "derived": dv, "picks": pk, "snapshot": snap})

    def _api_snap(self, date8):
        d, snap = store.load_snapshot(date8)
        if not snap:
            return self._json({"ok": False, "error": "no snapshot %s" % date8}, 404)
        self._json({"ok": True, "trade_date": d, "snapshot": snap})


def main():
    host = os.environ.get("HOST") or (sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1")
    port = int(os.environ.get("PORT") or (sys.argv[2] if len(sys.argv) > 2 else 888))
    if os.environ.get("AUTO_REFRESH", "1") != "0":
        start_refresh_daemon()
    ds = store.snapshot_dates()
    print("stock-portal  http://%s:%d" % (host, port))
    print("  数据目录 %s（%d 个快照，最新 %s）"
          % (store.SNAP_DIR, len(ds), ds[-1] if ds else "无"))
    ThreadingHTTPServer((host, port), H).serve_forever()


# ---------------------------------------------------------------- 云端自动刷新
# 托管沙箱里没有 cron，用进程内线程顶替计划任务。四个档位（用户 2026-11-02 定）：
#   09:00 早间 —— 开盘前看昨日复盘：行情/人气榜刷新，但源口径还是上一交易日，
#                  snapshot_job 会判"历史日已有快照"直接跳过，不动归档
#   12:00 午盘 —— 11:30 收盘后半小时，上午的真实口径（涨跌/成交/涨停池/驱动词）
#   15:10 收盘 —— 收盘数据落库
#   16:00 复盘 —— 简报/归因/龙虎榜那一批生成完，复盘总结可以出
# 每轮刷完自动同步 GitHub Pages 镜像（AUTO_PUBLISH=0 可关）。
# 失败只打日志，不影响服务；下一轮再试。数据写 data/，页面请求期只读，不互斥。
import threading  # noqa: E402
import subprocess  # noqa: E402
import time as _time  # noqa: E402
from datetime import datetime  # noqa: E402

SLOTS = (("morning", 9, 0), ("midday", 12, 0), ("close", 15, 10), ("review", 16, 0))

_DAEMON_DONE: set = set()


def _is_trading_day() -> bool:
    """粗判：周一~周五。节假日会空跑一轮——源不更新，失败留 degraded，无害。"""
    return datetime.now().weekday() < 5


def _refresh_once(label: str) -> None:
    print("[daemon] %s 开始刷新" % label, flush=True)
    for cmd, name in (([sys.executable, "snapshot_job.py"], "snapshot"),
                      ([sys.executable, "refresh.py", "--allow-partial"], "refresh")):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            tail = (r.stdout or "").strip().splitlines()[-3:]
            print("[daemon] %s exit=%s %s" % (name, r.returncode, " | ".join(tail)),
                  flush=True)
        except Exception as e:
            print("[daemon] %s 异常：%s" % (name, e), flush=True)
    # GitHub Pages 是静态托管，没有后端也没有 cron：不主动推，它就永远停在
    # 上一次构建那一刻（本地已刷新、线上还是旧数）。每轮刷完顺手把镜像推上去。
    # AUTO_PUBLISH=0 可关掉（比如只想本地看、不想动远端）；云端沙箱发布时排除了
    # .git、也没有凭据，用 .git 存在与否当开关，省掉每天四次注定失败的 git 调用。
    _root = os.path.dirname(os.path.abspath(__file__))
    if (os.environ.get("AUTO_PUBLISH", "1") != "0"
            and os.path.isdir(os.path.join(_root, ".git"))):
        try:
            r = subprocess.run([sys.executable, "publish_static.py"],
                               cwd=_root,
                               capture_output=True, text=True, timeout=900)
            tail = (r.stdout or "").strip().splitlines()[-2:]
            print("[daemon] publish exit=%s %s" % (r.returncode, " | ".join(tail)),
                  flush=True)
        except Exception as e:
            print("[daemon] publish 异常：%s" % e, flush=True)


def _due_slot(now, done):
    """当前时刻该跑哪一档。返回 (slot, key) 或 (None, None)。

    判据是"同一小时、分钟已到、今天这一档没跑过"——进程启动晚了几分钟也能补上，
    不会像 == 精确比对那样错过整点。
    """
    for slot, hh, mm in SLOTS:
        key = "%s-%s" % (now.strftime("%Y%m%d"), slot)
        if key not in done and now.hour == hh and now.minute >= mm:
            return slot, key
    return None, None


def _daemon_loop():
    while True:
        now = datetime.now()
        if _is_trading_day():
            slot, key = _due_slot(now, _DAEMON_DONE)
            if slot:
                _DAEMON_DONE.add(key)
                threading.Thread(target=_refresh_once, args=(slot,),
                                 daemon=True).start()
        _time.sleep(30)


def start_refresh_daemon():
    threading.Thread(target=_daemon_loop, daemon=True).start()
    print("[daemon] 自动刷新已启动：交易日 %s 各一轮（刷完自动同步 GitHub Pages 镜像）"
          % " / ".join("%02d:%02d" % (h, m) for _, h, m in SLOTS), flush=True)
    # 启动时若数据陈旧（最新快照不是今天且现在已过 15:00），先补一轮
    ds = store.snapshot_dates()
    today = datetime.now().strftime("%Y-%m-%d")
    if ds and ds[-1] != today and datetime.now().hour >= 15:
        threading.Thread(target=_refresh_once, args=("boot-catchup",),
                         daemon=True).start()


if __name__ == "__main__":
    main()
