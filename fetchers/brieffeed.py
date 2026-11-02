# -*- coding: utf-8 -*-
"""简报源（finance-auto-gen）抓取 + 解析 → data/live/brief.json。

源的性质（2026-11-01 已核）：**AI 生成的复盘早晚报**，不是行情数据。
所以本站只用它三样东西，且都标明出处与"叙事参考"属性：
    ① 指数收盘点位与涨跌幅（可以拿新浪/腾讯对拍的部分）
    ② 未来事件日历（唯一的不可替代项——本站算不出来）
    ③ 多空词频基调（弱信号，只做背景色）

通道顺序按实测（2026-11-02，同一篇 20,437 B 三路同源）：
    raw + 代理        1.7s
    jsDelivr + 代理   3.1s
    jsDelivr 直连     7.5s（能用但慢）
    raw 直连          **不可用**：本机是黑洞丢包，socket timeout 8s 也照样挂 64s
所以 raw 只在走代理时尝试，直连只给 jsDelivr。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brief_parse  # noqa: E402

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
PROXY = os.environ.get("PORTAL_PROXY") or "http://127.0.0.1:7890"
RAW = "https://raw.githubusercontent.com/jixiangying/finance-auto-gen/main/reports/{d}-{s}.md"
JSD = "https://cdn.jsdelivr.net/gh/jixiangying/finance-auto-gen@main/reports/{d}-{s}.md"
CHANNELS = [("raw+proxy", RAW, True), ("jsdelivr+proxy", JSD, True),
            ("jsdelivr", JSD, False)]


def _get(url: str, via_proxy: bool, timeout: float = 6.0):
    if via_proxy:
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    else:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
        raw = r.read()
    # raw.githubusercontent 不带 charset，按 latin-1 解会把中文全弄成乱码
    return raw.decode("utf-8", "ignore")


def grab(day: str, session: str):
    """取一篇；三通道都失败就是没拿到（可能是真没有、也可能网络断了）。"""
    for name, tpl, via_proxy in CHANNELS:
        try:
            txt = _get(tpl.format(d=day, s=session), via_proxy)
            if len(txt) > 500:
                return txt
        except Exception:  # noqa: BLE001
            continue
    return None


def fetch(days: int = 5) -> dict:
    """并发抓，不串行：一篇要 1~2 秒，7 天早晚两篇串起来就 20 秒起步，
    而调用方是刷新脚本，串行抓会让整次刷新从 40 秒变成 3 分钟。"""
    from concurrent.futures import ThreadPoolExecutor

    today = date.today()
    tasks = []
    for i in range(days + 2):
        d = (today - timedelta(days=i)).isoformat()
        for s in ("evening", "morning"):
            tasks.append((d, s))

    def one(t):
        d, s = t
        md = grab(d, s)
        if not md:
            return None
        try:
            return brief_parse.parse(md, "%s-%s.md" % (d, s))
        except Exception:  # noqa: BLE001 —— 单篇解析失败不影响其余
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        reports = [r for r in ex.map(one, tasks) if r]
    # 排序必须是「日期 → 当天先 evening 后 morning」：字符串倒序会把 morning 排到前面
    # （"evening" < "morning"），最新一篇就成了当天早报，title 与「最新」标签对不上。
    reports.sort(key=lambda r: (r["date"], 1 if r["session"] == "evening" else 0),
                 reverse=True)

    # 事件日历取所有篇的并集：越新的篇写的窗口越新，旧篇里已过去的事件自然被滤掉
    today_s = today.isoformat()
    events = {}
    for r in reports[:6]:
        for e in r.get("events") or []:
            k = (e.get("date"), e.get("title"))
            if e.get("date") and e["date"] >= today_s and k not in events:
                events[k] = {"date": e["date"], "title": e.get("title") or "",
                             "from": r["date"] + " " + r["session"]}

    latest = reports[0] if reports else None
    return {
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "jixiangying/finance-auto-gen（AI 生成，仅作叙事参考）",
        "latest": latest,
        "reports": reports,
        "indices": (latest or {}).get("indices") or {},
        "events": sorted(events.values(), key=lambda e: e["date"]),
        "tone": (latest or {}).get("tone") or {},
    }


def save(obj: dict) -> str:
    from store import LIVE_DIR
    os.makedirs(LIVE_DIR, exist_ok=True)
    p = os.path.join(LIVE_DIR, "brief.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return p


if __name__ == "__main__":
    r = fetch(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
    p = save(r)
    print("抓到 %d 篇，最新 %s" % (len(r["reports"]),
                                r["latest"] and (r["latest"]["date"] + " " + r["latest"]["session"])))
    print("  指数 %d 个　事件 %d 条" % (len(r["indices"]), len(r["events"])))
    print("写入", p)
