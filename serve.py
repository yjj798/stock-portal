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
from urllib.parse import parse_qs, urlparse

import store
import score as scoring
from picks import pick_stocks
from sec_core import derive, to_row, WIDE  # noqa: F401  (WIDE 供后续页面复用)
from render import (page_attr, page_brief, page_concept, page_drivers, page_home,
                    page_industry, page_rank, page_stock)
from render.components import esc
from render.nav import nav
from render.shell import no_bundle
from render.theme import CSS


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
            "/attr": "/attr", "/brief": "/brief"}.get(title, "/")


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "stock-portal/0.1"

    def log_message(self, fmt, *args):  # 安静一点
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, code: int, body, ctype="text/html; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False),
                   "application/json; charset=utf-8")

    def do_GET(self):
        raw = self.path
        u = urlparse(raw)
        path = u.path.rstrip("/") or "/"
        q = parse_qs(u.query or "")
        try:
            if path == "/":
                return self._home(None, q)
            if path == "/mp":
                return self._mp()
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
            # 分栏链接要带原路径：历史快照页是 /snapshot/20261031，写成 "/" 会把人送回最新一天
            base=("/snapshot/%s" % date8) if date8 else "/")
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
        e = (data.get("stocks") or {}).get(c)
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
