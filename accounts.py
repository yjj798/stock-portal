# -*- coding: utf-8 -*-
"""会员账号：注册 / 登录 / 会话 / 自选股 / 邮箱验证码。

为什么自己写而不是上框架
------------------------
这个站是「一个 serve.py + 一个 build_static.py」的单文件后端，没有 ORM 也没有依赖。
会员只做四件事：账号密码邮箱、登录态、自选股、改密码。用标准库 sqlite3 +
hashlib + secrets 足够，多引一个框架反而让静态构建那条路变复杂。

安全基线（这几条不满足就是白做）
--------------------------------
1. **密码只存 PBKDF2-HMAC-SHA256**，200k 轮、16 字节随机盐，格式
   `pbkdf2_sha256$200000$<salt_hex>$<hash_hex>`。校验用 `hmac.compare_digest`，
   不用 `==`（防时序侧信道）。
2. **会话只存随机 token 的哈希**。Cookie 里给的是原文，库里存 sha256(token)——
   库泄露也不能直接拿去登录。30 天有效，剩余不足 7 天自动续期（滑动窗口）。
3. **登录限流**：同一「账号标识 + IP」15 分钟内失败 5 次即锁，锁定期不再比对密码
   （避免把库当校验预言机）。计数在进程内存里——单进程服务够用，重启清零是
   刻意的取舍（宁可放宽也不要因为重启把用户永久锁死）。
4. **邮箱验证码**存哈希、5 分钟过期、最多试 5 次、用后即焚。目的必须区分
   verify / reset，不能拿注册验证码去改密码。
5. **越权**：所有自选股操作都带 uid 条件，`uid` 只从会话取，从不从请求参数取。

明文密码（2026-11-02 用户指定）
------------------------------
用户明确要求「会员账号密码明文存储」。照做，但把它做成**可控、可见、可关闭**：

- `users.pwd_plain` 存明文，供站长在 `/admin/users?t=<ADMIN_TOKEN>` 查看；
  `users.pwd` 仍然存 PBKDF2 哈希，登录校验走哈希——明文只用于"看"，不用于比对。
- `PWD_PLAINTEXT` 开关（环境变量 `PWD_PLAINTEXT=0` 关）。关掉后新注册不再写明文，
  并且 `purge_plain()` 可把存量明文清空，随时能退回纯哈希模式。
- 风险写在用户看得见的地方：注册页与会员中心都有一行提示
  「密码以可读形式保存（站长可查看），请勿复用你在其它网站的密码」。
  不写这句就是骗用户。
- 后台默认是关闭的：`ADMIN_TOKEN` 没设时 `/admin/users` 直接 404，连页面都不存在。

**这不是推荐做法**。它换来的是"站长能帮用户找回密码"这一个便利，代价是数据库
一旦泄露，所有账号密码直接可用。要长期运营、面向陌生人开放，应当把
`PWD_PLAINTEXT` 设为 0 并停用后台页。


邮箱投递
--------
没有 SMTP 时**不假装发信**：`mail_configured()` 返回 False，验证码写进
`data/mail_outbox.log` 并在页面上明示「未配置 SMTP，验证码直接显示」。
配了 SMTP（环境变量 SMTP_HOST/PORT/USER/PASS/FROM）就走真投递。
这样流程本身是完整的、可验证的，也不会骗用户说"请查收邮件"。

数据文件 `data/users.db` 含密码哈希与 session，**不进 git**（.gitignore 已排除 data/*.db）。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import smtplib
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from email.message import EmailMessage

DB = os.environ.get("WB_USERS_DB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "users.db")
OUTBOX = os.environ.get("WB_MAIL_OUTBOX") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "mail_outbox.log")

SESS_DAYS = 30
SESS_RENEW_DAYS = 7          # 剩余不足 7 天时续期
CODE_TTL_MIN = 5
CODE_MAX_TRIES = 5
PBKDF2_ROUNDS = 200_000
MIN_PWD = 8

# 明文密码开关（用户 2026-11-02 指定开启）。设 PWD_PLAINTEXT=0 即停写明文。
PWD_PLAINTEXT = os.environ.get("PWD_PLAINTEXT", "1") != "0"
# 后台查看会员密码的口令。没设 = 没有这个页面（返回 404，不是 403）。
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()

RE_MAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
RE_USER = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{3,20}$")

_init_lock = threading.Lock()
_inited = False


# ---------------------------------------------------------------- 基础
def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=8.0)
    c.row_factory = sqlite3.Row
    # WAL：ThreadingHTTPServer 每个请求一个线程，读写并发不互锁
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init() -> None:
    """建表（幂等）。每个进程第一次用到时跑一次。"""
    global _inited
    if _inited:
        return
    with _init_lock:
        if _inited:
            return
        with _conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                pwd TEXT NOT NULL,
                pwd_plain TEXT,
                created_at TEXT NOT NULL,
                last_login TEXT,
                plan TEXT NOT NULL DEFAULT 'free',
                email_verified INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS sessions(
                thash TEXT PRIMARY KEY,
                uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                ua TEXT,
                ip TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_sessions_uid ON sessions(uid);
            CREATE TABLE IF NOT EXISTS watchlist(
                uid INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                code TEXT NOT NULL,
                name TEXT,
                added_at TEXT NOT NULL,
                PRIMARY KEY(uid, code)
            );
            CREATE TABLE IF NOT EXISTS codes(
                email TEXT NOT NULL COLLATE NOCASE,
                purpose TEXT NOT NULL,
                chash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                tries INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY(email, purpose)
            );
            """)
            # 老库补列：CREATE TABLE IF NOT EXISTS 不会给已存在的表加字段，
            # 这里显式迁移一次（幂等，加过就跳过）。
            cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
            if "pwd_plain" not in cols:
                c.execute("ALTER TABLE users ADD COLUMN pwd_plain TEXT")
        _inited = True


def _now() -> datetime:
    return datetime.now()


def _s(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 密码
def hash_pwd(pwd: str, salt: str = "") -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS)
    return "pbkdf2_sha256$%d$%s$%s" % (PBKDF2_ROUNDS, salt, h.hex())


def check_pwd(pwd: str, stored: str) -> bool:
    try:
        algo, rounds, salt, want = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"),
                                  bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(got, want)
    except Exception:            # noqa: BLE001  坏数据一律当校验失败
        return False


def pwd_problem(pwd: str) -> str:
    """返回不合规原因，空串表示通过。规则写死一处，注册与改密共用。"""
    if not pwd or len(pwd) < MIN_PWD:
        return "密码至少 %d 位" % MIN_PWD
    if len(pwd) > 128:
        return "密码太长（上限 128 位）"
    if not re.search(r"[A-Za-z]", pwd):
        return "密码要含字母"
    if not re.search(r"\d", pwd):
        return "密码要含数字"
    if pwd.lower() in ("12345678", "password", "abcd1234", "qwerty123"):
        return "这个密码太常见了，换一个"
    return ""


# ---------------------------------------------------------------- 限流
_fail: dict = {}
_fail_lock = threading.Lock()
FAIL_WINDOW = 15 * 60
FAIL_MAX = 5


def _fail_key(ident: str, ip: str) -> str:
    return ("%s|%s" % (ident.lower().strip(), ip or "-"))[:200]


def locked(ident: str, ip: str) -> int:
    """还要等几秒解锁；0 表示没锁。"""
    k = _fail_key(ident, ip)
    with _fail_lock:
        v = [t for t in _fail.get(k, []) if time.time() - t < FAIL_WINDOW]
        _fail[k] = v
        if len(v) >= FAIL_MAX:
            return int(FAIL_WINDOW - (time.time() - v[0])) + 1
    return 0


def note_fail(ident: str, ip: str) -> None:
    k = _fail_key(ident, ip)
    with _fail_lock:
        _fail.setdefault(k, []).append(time.time())


def clear_fail(ident: str, ip: str) -> None:
    with _fail_lock:
        _fail.pop(_fail_key(ident, ip), None)


# ---------------------------------------------------------------- 注册 / 登录
def register(email: str, username: str, pwd: str, pwd2: str = "") -> tuple:
    """成功返回 (True, uid)，失败 (False, 原因)。"""
    init()
    email = (email or "").strip()
    username = (username or "").strip()
    if not RE_MAIL.match(email):
        return False, "邮箱格式不对"
    if len(email) > 120:
        return False, "邮箱太长"
    if not RE_USER.match(username):
        return False, "用户名 3~20 位，可用中文/字母/数字/下划线"
    bad = pwd_problem(pwd or "")
    if bad:
        return False, bad
    if pwd2 and pwd != pwd2:
        return False, "两次输入的密码不一致"

    with _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO users(email,username,pwd,pwd_plain,created_at) VALUES(?,?,?,?,?)",
                (email, username, hash_pwd(pwd),
                 (pwd if PWD_PLAINTEXT else None), _s(_now())))
            uid = cur.lastrowid
        except sqlite3.IntegrityError as e:
            msg = str(e).lower()
            if "email" in msg:
                return False, "这个邮箱已经注册过，直接登录或找回密码"
            if "username" in msg:
                return False, "用户名被占用了，换一个"
            return False, "注册失败（数据约束）"
    return True, uid


def find_user(ident: str):
    init()
    ident = (ident or "").strip()
    if not ident:
        return None
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE email=? OR username=?",
                      (ident, ident)).fetchone()
    return dict(r) if r else None


def login(ident: str, pwd: str, ip: str = "", ua: str = "") -> tuple:
    """成功返回 (True, token, user)，失败 (False, 原因)。"""
    init()
    wait = locked(ident, ip)
    if wait:
        return False, "尝试太频繁，请 %d 秒后再试" % wait, None
    u = find_user(ident)
    # 用户不存在与密码错给同一句话，不告诉对方"这个邮箱存在"
    if not u or not check_pwd(pwd or "", u["pwd"]):
        note_fail(ident, ip)
        return False, "账号或密码不对", None
    if (u.get("status") or "active") != "active":
        return False, "这个账号已被停用", None
    clear_fail(ident, ip)
    token = new_session(u["id"], ip, ua)
    with _conn() as c:
        c.execute("UPDATE users SET last_login=? WHERE id=?", (_s(_now()), u["id"]))
    u["last_login"] = _s(_now())
    u.pop("pwd", None)      # 绝不把密码哈希带到渲染层
    return True, token, u


# ---------------------------------------------------------------- 会话
def _thash(token: str) -> str:
    return hashlib.sha256(("wb-sess:" + (token or "")).encode("utf-8")).hexdigest()


def new_session(uid: int, ip: str = "", ua: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    with _conn() as c:
        c.execute("INSERT INTO sessions(thash,uid,created_at,seen_at,expires_at,ua,ip)"
                  " VALUES(?,?,?,?,?,?,?)",
                  (_thash(token), uid, _s(now), _s(now),
                   _s(now + timedelta(days=SESS_DAYS)), (ua or "")[:200], (ip or "")[:60]))
        # 顺手清过期会话，省一个定时任务
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (_s(now),))
    return token


def user_by_token(token: str):
    """按 cookie 里的 token 取用户；过期/不存在返回 None。顺带滑动续期。"""
    if not token:
        return None
    init()
    th = _thash(token)
    now = _now()
    with _conn() as c:
        r = c.execute("SELECT * FROM sessions WHERE thash=?", (th,)).fetchone()
        if not r:
            return None
        try:
            exp = datetime.strptime(r["expires_at"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            c.execute("DELETE FROM sessions WHERE thash=?", (th,))
            return None
        if exp < now:
            c.execute("DELETE FROM sessions WHERE thash=?", (th,))
            return None
        u = c.execute("SELECT * FROM users WHERE id=?", (r["uid"],)).fetchone()
        if not u or (u["status"] or "active") != "active":
            return None
        if exp - now < timedelta(days=SESS_RENEW_DAYS):
            c.execute("UPDATE sessions SET expires_at=?, seen_at=? WHERE thash=?",
                      (_s(now + timedelta(days=SESS_DAYS)), _s(now), th))
        else:
            c.execute("UPDATE sessions SET seen_at=? WHERE thash=?", (_s(now), th))
    d = dict(u)
    d.pop("pwd", None)
    d["sid"] = th[:12]
    return d


def logout(token: str) -> None:
    if not token:
        return
    init()
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE thash=?", (_thash(token),))


def logout_all(uid: int) -> int:
    init()
    with _conn() as c:
        cur = c.execute("DELETE FROM sessions WHERE uid=?", (uid,))
    return cur.rowcount


def change_pwd(uid: int, old: str, new: str, new2: str = "", keep_token: str = "") -> tuple:
    init()
    with _conn() as c:
        r = c.execute("SELECT pwd FROM users WHERE id=?", (uid,)).fetchone()
    if not r or not check_pwd(old or "", r["pwd"]):
        return False, "原密码不对"
    bad = pwd_problem(new or "")
    if bad:
        return False, bad
    if new2 and new != new2:
        return False, "两次输入的新密码不一致"
    if old == new:
        return False, "新密码不能和原密码一样"
    with _conn() as c:
        c.execute("UPDATE users SET pwd=?, pwd_plain=? WHERE id=?",
                  (hash_pwd(new), (new if PWD_PLAINTEXT else None), uid))
    # 改密后踢掉其它设备，只留当前这条会话
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE uid=? AND thash<>?", (uid, _thash(keep_token)))
    return True, ""


def sessions_of(uid: int) -> list:
    init()
    with _conn() as c:
        rows = c.execute("SELECT thash,created_at,seen_at,expires_at,ua,ip FROM sessions"
                         " WHERE uid=? ORDER BY seen_at DESC", (uid,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 自选股
def watch_add(uid: int, code: str, name: str = "") -> bool:
    init()
    code = (code or "").strip()
    if not re.match(r"^\d{6}$", code):
        return False
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO watchlist(uid,code,name,added_at) VALUES(?,?,?,?)",
                  (uid, code, (name or "")[:20], _s(_now())))
    return True


def watch_del(uid: int, code: str) -> bool:
    init()
    with _conn() as c:
        cur = c.execute("DELETE FROM watchlist WHERE uid=? AND code=?", (uid, (code or "").strip()))
    return cur.rowcount > 0


def watch_list(uid: int) -> list:
    init()
    with _conn() as c:
        rows = c.execute("SELECT code,name,added_at FROM watchlist WHERE uid=?"
                         " ORDER BY added_at DESC", (uid,)).fetchall()
    return [dict(r) for r in rows]


def watch_codes(uid: int) -> set:
    return {w["code"] for w in watch_list(uid)}


# ---------------------------------------------------------------- 邮箱验证码
def mail_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def _send_mail(to: str, subject: str, body: str) -> bool:
    """真投递。没配 SMTP 就写 outbox 文件并返回 False（调用方据此在页面显示验证码）。"""
    if not mail_configured():
        os.makedirs(os.path.dirname(OUTBOX), exist_ok=True)
        with open(OUTBOX, "a", encoding="utf-8") as f:
            f.write("[%s] to=%s subject=%s\n%s\n\n" % (_s(_now()), to, subject, body))
        return False
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT") or 465)
    user = os.environ.get("SMTP_USER") or ""
    pwd = os.environ.get("SMTP_PASS") or ""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = to
    msg.set_content(body)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as s:
                if user:
                    s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls()
                if user:
                    s.login(user, pwd)
                s.send_message(msg)
        return True
    except Exception as e:                     # noqa: BLE001
        with open(OUTBOX, "a", encoding="utf-8") as f:
            f.write("[%s] FAIL to=%s %s: %s\n" % (_s(_now()), to, type(e).__name__, e))
        return False


def send_code(email: str, purpose: str = "verify") -> tuple:
    """发 6 位码。返回 (ok, 提示, 明文码或空)。"""
    init()
    email = (email or "").strip()
    if not RE_MAIL.match(email):
        return False, "邮箱格式不对", ""
    if purpose not in ("verify", "reset"):
        return False, "用途不对", ""
    with _conn() as c:
        last = c.execute("SELECT created_at FROM codes WHERE email=? AND purpose=?",
                         (email, purpose)).fetchone()
        if last:
            try:
                gap = (_now() - datetime.strptime(last["created_at"], "%Y-%m-%d %H:%M:%S")).total_seconds()
                if gap < 60:
                    return False, "刚发过，%d 秒后再试" % int(60 - gap), ""
            except ValueError:
                pass
    code = "%06d" % secrets.randbelow(1000000)
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO codes(email,purpose,chash,expires_at,tries,created_at)"
                  " VALUES(?,?,?,?,0,?)",
                  (email, purpose, _thash("code:" + code),
                   _s(_now() + timedelta(minutes=CODE_TTL_MIN)), _s(_now())))
    subject = "A 股全景 · %s" % ("邮箱验证码" if purpose == "verify" else "重置密码验证码")
    body = ("你的验证码是 %s，%d 分钟内有效。\n如果不是你本人操作，忽略这封邮件即可。"
            % (code, CODE_TTL_MIN))
    sent = _send_mail(email, subject, body)
    if sent:
        return True, "验证码已发到 %s，%d 分钟内有效" % (email, CODE_TTL_MIN), ""
    # 没配 SMTP：不装发信，直接把码给页面，并写清原因
    return True, "未配置 SMTP，验证码直接显示（生产环境请配 SMTP_HOST/SMTP_FROM）", code


def check_code(email: str, code: str, purpose: str = "verify") -> tuple:
    init()
    email = (email or "").strip()
    code = (code or "").strip()
    with _conn() as c:
        r = c.execute("SELECT * FROM codes WHERE email=? AND purpose=?",
                      (email, purpose)).fetchone()
        if not r:
            return False, "请先获取验证码"
        try:
            if datetime.strptime(r["expires_at"], "%Y-%m-%d %H:%M:%S") < _now():
                c.execute("DELETE FROM codes WHERE email=? AND purpose=?", (email, purpose))
                return False, "验证码已过期，重新获取"
        except ValueError:
            return False, "验证码状态异常，重新获取"
        if r["tries"] >= CODE_MAX_TRIES:
            c.execute("DELETE FROM codes WHERE email=? AND purpose=?", (email, purpose))
            return False, "试错次数太多，重新获取"
        if not hmac.compare_digest(r["chash"], _thash("code:" + code)):
            c.execute("UPDATE codes SET tries=tries+1 WHERE email=? AND purpose=?", (email, purpose))
            return False, "验证码不对"
        c.execute("DELETE FROM codes WHERE email=? AND purpose=?", (email, purpose))
    return True, ""


def mark_verified(email: str) -> None:
    init()
    with _conn() as c:
        c.execute("UPDATE users SET email_verified=1 WHERE email=?", ((email or "").strip(),))


def reset_pwd(email: str, code: str, new: str, new2: str = "") -> tuple:
    """邮箱验证码重置密码。成功后踢掉该账号全部会话。"""
    email = (email or "").strip()
    u = find_user(email)
    if not u:
        return False, "这个邮箱没有注册"
    bad = pwd_problem(new or "")
    if bad:
        return False, bad
    if new2 and new != new2:
        return False, "两次输入的新密码不一致"
    ok, why = check_code(email, code, "reset")
    if not ok:
        return False, why
    with _conn() as c:
        c.execute("UPDATE users SET pwd=?, pwd_plain=?, email_verified=1 WHERE id=?",
                  (hash_pwd(new), (new if PWD_PLAINTEXT else None), u["id"]))
        c.execute("DELETE FROM sessions WHERE uid=?", (u["id"],))
    return True, ""


# ---------------------------------------------------------------- 站长后台
def plaintext_on() -> bool:
    return PWD_PLAINTEXT


def admin_ok(token: str) -> bool:
    """后台口令校验。没配 ADMIN_TOKEN 时永远 False（页面当不存在）。"""
    if not ADMIN_TOKEN or not token:
        return False
    return hmac.compare_digest(token, ADMIN_TOKEN)


def admin_list(limit: int = 300) -> list:
    """会员清单（含明文密码，供站长查看）。明文为空的用户说明是关闭明文后注册/改密的。"""
    init()
    with _conn() as c:
        rows = c.execute(
            "SELECT u.id,u.email,u.username,u.pwd_plain,u.created_at,u.last_login,"
            "u.email_verified,u.status,"
            "(SELECT COUNT(*) FROM watchlist w WHERE w.uid=u.id) AS n_watch,"
            "(SELECT COUNT(*) FROM sessions s WHERE s.uid=u.id AND s.expires_at>?) AS n_sess"
            " FROM users u ORDER BY u.id DESC LIMIT ?", (_s(_now()), int(limit))).fetchall()
    return [dict(r) for r in rows]


def purge_plain() -> int:
    """把存量明文清空（退回纯哈希模式时用）。返回清掉的条数。"""
    init()
    with _conn() as c:
        cur = c.execute("UPDATE users SET pwd_plain=NULL WHERE pwd_plain IS NOT NULL")
    return cur.rowcount


# ---------------------------------------------------------------- 统计（首页/会员中心用）
def stats() -> dict:
    init()
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        act = c.execute("SELECT COUNT(*) FROM sessions WHERE expires_at > ?",
                        (_s(_now()),)).fetchone()[0]
    return {"users": n, "sessions": act, "plaintext": PWD_PLAINTEXT}
