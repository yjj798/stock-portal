# -*- coding: utf-8 -*-
"""会员系统验收：注册 / 登录 / 会话 / 找回密码 / 自选 / 安全边界。

为什么单独起一个服务来测
------------------------
验收会写库（注册、失败计数、自选），跑在 data/users.db 上会把真实会员数据搅乱，
而且"重复邮箱"这条用例第二次跑就必然失败。所以这里用临时库 + 独立端口起一个
serve.py 子进程，测完连库一起删——每次都是干净的初始状态，可重复跑。

判据都落在"用户能观察到的事实"上：状态码、跳转目标、页面上的中文提示、
Set-Cookie 的属性、SQLite 里的存储形态。不测内部函数名。
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8911
BASE = "http://127.0.0.1:%d" % PORT
ADMIN = "verify-token-9f2c"

PASS = []
FAIL = []


def chk(name: str, cond, expect=None, actual=None):
    if cond:
        PASS.append(name)
        print("  ✓ %s" % name)
    else:
        FAIL.append(name)
        extra = ""
        if expect is not None or actual is not None:
            extra = "　期望 %r 实际 %r" % (expect, actual)
        print("  ✗ %s%s" % (name, extra))


class NoRedir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def opener_factory():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedir)
    op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    return cj, op, op2


def post(op, path, data, headers=None):
    req = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data).encode(),
                                 method="POST")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        r = op.open(req, timeout=30)
        return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


def get(op, path):
    try:
        r = op.open(BASE + path, timeout=30)
        return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


def wait_port(port, sec=25):
    t0 = time.time()
    while time.time() - t0 < sec:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def main():
    tmp = tempfile.mkdtemp(prefix="wb_verify_auth_")
    db = os.path.join(tmp, "users.db")
    env = dict(os.environ)
    env.update({
        "WB_USERS_DB": db,
        "WB_MAIL_OUTBOX": os.path.join(tmp, "mail.log"),
        "ADMIN_TOKEN": ADMIN,
        "PWD_PLAINTEXT": "1",
        "AUTO_REFRESH": "0",             # 验收期间不要触发抓取/发布
    })
    srv = subprocess.Popen([sys.executable, "serve.py", "127.0.0.1", str(PORT)],
                           cwd=HERE, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_port(PORT):
            print("服务起不来，验收中止")
            return 2

        print("== A 页面与导航 ==")
        cj, op, opf = opener_factory()
        s, b, _ = get(opf, "/")
        chk("首页 200", s == 200)
        chk("首页是登录门面", ("邮箱或用户名" in b) or ("会员登录" in b))
        chk("首页有注册/找回入口", "/register" in b and "/forgot" in b)
        chk("首页不出现微信登录", "微信" not in b)
        s, b, _ = get(opf, "/board")
        chk("总览在 /board", s == 200 and 'data-tabs="home"' in b)
        chk("导航有首页与总览两项", 'href="/"' in b and 'href="/board"' in b)
        for p in ("/register", "/forgot", "/terms", "/privacy"):
            s, b, _ = get(opf, p)
            chk("%s 200" % p, s == 200)
        s, b, h = get(op, "/me")
        chk("未登录 /me 跳登录", s == 302 and "/login" in h.get("Location", ""))
        s, b, _ = get(opf, "/admin/users?t=wrong")
        chk("后台无口令返回 404", s == 404)
        s, b, _ = get(opf, "/admin/users?t=" + ADMIN)
        chk("后台口令正确可进", s == 200 and "会员清单" in b)

        print("== B 注册校验 ==")
        _cj, op, opf = opener_factory()
        s, b, _ = post(op, "/register", {"email": "bad", "username": "tester",
                                         "pwd": "abc12345", "pwd2": "abc12345"})
        chk("邮箱格式不对被拦", s == 200 and "邮箱格式不对" in b)
        s, b, _ = post(op, "/register", {"email": "u1@test.com", "username": "ab",
                                         "pwd": "abc12345", "pwd2": "abc12345"})
        chk("用户名太短被拦", s == 200 and "用户名" in b)
        for pwd, why in (("abc1234", "至少 8 位"), ("abcdefgh", "要含数字"),
                         ("12345678", "要含字母")):
            s, b, _ = post(op, "/register", {"email": "u1@test.com", "username": "tester",
                                             "pwd": pwd, "pwd2": pwd})
            chk("弱密码被拦（%s）" % why, s == 200 and why in b)
        s, b, _ = post(op, "/register", {"email": "u1@test.com", "username": "tester",
                                         "pwd": "abc12345", "pwd2": "abc12346"})
        chk("两次密码不一致被拦", s == 200 and "不一致" in b)

        s, b, h = post(op, "/register", {"email": "u1@test.com", "username": "会员甲",
                                         "pwd": "abc12345", "pwd2": "abc12345"})
        ck = h.get("Set-Cookie", "")
        chk("注册成功跳转", s == 302 and "/me" in h.get("Location", ""))
        chk("注册即登录（有会话 cookie）", "wb_sid=" in ck)
        chk("cookie 是 HttpOnly", "HttpOnly" in ck)
        chk("cookie 是 SameSite=Lax", "SameSite=Lax" in ck)

        s, b, _ = post(opener_factory()[1], "/register",
                       {"email": "u1@test.com", "username": "另一个人",
                        "pwd": "abc12345", "pwd2": "abc12345"})
        chk("重复邮箱被拦", s == 200 and "已经注册" in b)
        s, b, _ = post(opener_factory()[1], "/register",
                       {"email": "u2@test.com", "username": "会员甲",
                        "pwd": "abc12345", "pwd2": "abc12345"})
        chk("重复用户名被拦", s == 200 and "被占用" in b)

        print("== C 登录与限流 ==")
        _cj2, op2, opf2 = opener_factory()
        s, b, _ = post(op2, "/login", {"ident": "u1@test.com", "pwd": "wrongpass1"})
        chk("密码错给提示", s == 200 and "账号或密码不对" in b)
        s, b, _ = post(op2, "/login", {"ident": "nobody@test.com", "pwd": "wrongpass1"})
        chk("账号不存在同一句（不泄露注册状态）", s == 200 and "账号或密码不对" in b)
        s, b, h = post(op2, "/login", {"ident": "会员甲", "pwd": "abc12345"})
        chk("用户名可登录", s == 302 and "wb_sid=" in h.get("Set-Cookie", ""))
        s, b, h = post(opener_factory()[1], "/login",
                       {"ident": "u1@test.com", "pwd": "abc12345", "next": "/me"})
        chk("登录回跳 next", s == 302 and h.get("Location") == "/me")
        s, b, h = post(opener_factory()[1], "/login",
                       {"ident": "u1@test.com", "pwd": "abc12345", "next": "//evil.com/x"})
        chk("next 不能跳出站外", s == 302 and not h.get("Location", "").startswith("//"))

        # 连续失败锁定：换一个账号，避免影响后面的用例
        _cj3, op3, _ = opener_factory()
        post(opener_factory()[1], "/register", {"email": "lock@test.com", "username": "锁定测试",
                                                "pwd": "abc12345", "pwd2": "abc12345"})
        last = ""
        for _i in range(6):
            s, b, _ = post(op3, "/login", {"ident": "lock@test.com", "pwd": "badpass12"})
            last = b
        chk("连续失败后被限流", "尝试太频繁" in last)

        print("== D 会话与退出 ==")
        s, b, _ = get(opf2, "/me")
        chk("会话可用（/me 200）", s == 200 and "会员中心" in b)
        chk("会员中心显示邮箱", "u1@test.com" in b)
        s, b, _ = get(opener_factory()[1], "/me")
        chk("未登录浏览器看不到会员中心", s == 302)

        _cjx, opx, opfx = opener_factory()
        opx.addheaders = [("Cookie", "wb_sid=forged-token-abcdef")]
        s, b, _ = get(opx, "/me")
        chk("伪造 token 不认", s == 302)

        print("== E 密码存储形态 ==")
        con = sqlite3.connect(db)
        row = con.execute("SELECT pwd, pwd_plain FROM users WHERE email='u1@test.com'").fetchone()
        con.close()
        chk("库里有该用户", bool(row))
        if row:
            chk("pwd 是 PBKDF2 哈希", row[0].startswith("pbkdf2_sha256$200000$"))
            chk("哈希里不含明文", "abc12345" not in row[0])
            chk("按用户要求存了明文（可查看）", row[1] == "abc12345")
        s, b, _ = get(opf2, "/me")
        chk("会员中心页面不印密码", "abc12345" not in b)

        print("== F 邮箱找回密码 ==")
        post(opener_factory()[1], "/register", {"email": "u2@test.com", "username": "会员乙",
                                                "pwd": "abc12345", "pwd2": "abc12345"})
        _cjy, opy, opfy = opener_factory()
        s, b, _ = post(opy, "/forgot", {"act": "send", "email": "u2@test.com"})
        m = re.search(r'monospace">(\d{6})<', b)
        chk("发码成功且有 6 位码（未配 SMTP 直接显示）", s == 200 and bool(m))
        code = m.group(1) if m else "000000"
        s, b, _ = post(opy, "/forgot", {"act": "reset", "email": "u2@test.com",
                                        "code": "000000" if code != "000000" else "111111",
                                        "pwd": "newpass123", "pwd2": "newpass123"})
        chk("错码不放行", s == 200 and "验证码" in b)
        s, b, h = post(opy, "/forgot", {"act": "reset", "email": "u2@test.com",
                                        "code": code, "pwd": "newpass123",
                                        "pwd2": "newpass123"})
        chk("正确验证码可重置", s == 302 and "login" in h.get("Location", ""))
        s, b, _ = post(opener_factory()[1], "/login",
                       {"ident": "u2@test.com", "pwd": "newpass123"})
        chk("新密码能登录", s == 302)
        s, b, _ = post(opener_factory()[1], "/login",
                       {"ident": "u2@test.com", "pwd": "abc12345"})
        chk("旧密码失效", s == 200 and "账号或密码不对" in b)

        print("== G 自选股与越权 ==")
        post(opy, "/login", {"ident": "u2@test.com", "pwd": "newpass123"})
        s, b, h = post(opy, "/watch/add", {"code": "002292", "name": "奥飞娱乐",
                                           "back": "/me"})
        chk("登录后可加自选", s == 302)
        s, b, _ = get(opy, "/me")
        chk("自选出现在会员中心", "002292" in b and "奥飞娱乐" in b)
        post(opy, "/watch/add", {"code": "1234567", "name": "非法代码", "back": "/me"})
        s, b, _ = get(opy, "/me")
        chk("非 6 位代码不被写入", "1234567" not in b)
        _cjz, opz, _ = opener_factory()
        s, b, h = post(opz, "/watch/add", {"code": "600000", "back": "/me"})
        chk("未登录加自选跳登录", s == 302 and "/login" in h.get("Location", ""))
        # 越权：甲账号看不到乙账号的自选
        s, b, _ = get(opf2, "/me")
        chk("别人的自选看不到（按 uid 隔离）", "002292" not in b)
        s, b, h = post(opy, "/watch/del", {"code": "002292", "back": "/me"})
        s, b, _ = get(opy, "/me")
        chk("可移除自选", "002292" not in b or "还没有自选" in b)

        print("== H 安全边界 ==")
        _cjw, opw, _ = opener_factory()
        s, b, _ = post(opw, "/login", {"ident": "u1@test.com", "pwd": "abc12345"},
                       headers={"Origin": "https://evil.example"})
        chk("跨站 Origin 被拒", s == 403)
        s, b, _ = post(opw, "/register", {"email": "u3@test.com", "username": "同源测试",
                                          "pwd": "abc12345", "pwd2": "abc12345"},
                       headers={"Origin": BASE})
        chk("同源 Origin 正常放行", s == 302)
        s, b, h = get(opener_factory()[1], "/me")
        s2, b2, h2 = post(opener_factory()[1], "/login",
                          {"ident": "u1@test.com", "pwd": "abc12345"})
        chk("Set-Cookie 不含密码等敏感值",
            "abc12345" not in h2.get("Set-Cookie", ""))
        s, b, h = post(opener_factory()[1], "/logout", {})
        chk("退出清 cookie", s == 302 and "Max-Age=0" in h.get("Set-Cookie", ""))

        print("== I 静态站 ==")
        dist = os.path.join(HERE, "dist")
        if os.path.isdir(dist):
            with open(os.path.join(dist, "index.html"), encoding="utf-8") as f:
                hh = f.read()
            chk("静态首页不出登录表单", 'action="/login"' not in hh)
            chk("静态首页把会员入口指向动态站", "t.legaga.top/login" in hh)
            p = os.path.join(dist, "login", "index.html")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    lh = f.read()
                chk("静态 /login 跳动态站", "t.legaga.top/login" in lh)
            else:
                chk("静态 /login 存在", False)
        else:
            print("  （dist 不存在，跳过静态检查）")

    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:                # noqa: BLE001
            srv.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nPASS %d · FAIL %d" % (len(PASS), len(FAIL)))
    if FAIL:
        for x in FAIL:
            print("  失败：%s" % x)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
