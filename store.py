# -*- coding: utf-8 -*-
"""本地历史库读写。所有页面只从这里取数，请求期不联网。

目录：
    data/snapshots/<YYYY-MM-DD>.json   每日完整快照
    data/series.json                   派生指标日序列（情绪温度等）
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("PORTAL_DATA") or os.path.join(HERE, "data")
SNAP_DIR = os.path.join(DATA, "snapshots")
SERIES = os.path.join(DATA, "series.json")
LIVE_DIR = os.path.join(DATA, "live")
BUNDLE = os.path.join(LIVE_DIR, "bundle.json")

_lock = threading.Lock()
_cache = {"key": None, "snap": None}


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def snapshot_dates() -> list:
    if not os.path.isdir(SNAP_DIR):
        return []
    return sorted(n[:-5] for n in os.listdir(SNAP_DIR) if n.endswith(".json"))


def load_snapshot(date8: Optional[str] = None) -> Tuple[Optional[str], Optional[dict]]:
    """读某日快照；date8 为空取最新。带 mtime 缓存，热路径不重复解析 JSON。"""
    if not date8:
        ds = snapshot_dates()
        if not ds:
            return None, None
        date8 = ds[-1]
    path = os.path.join(SNAP_DIR, date8 + ".json")
    if not os.path.exists(path):
        return None, None
    mtime = os.path.getmtime(path)
    key = (path, mtime)
    with _lock:
        if _cache["key"] == key:
            return date8, _cache["snap"]
    snap = _read_json(path)
    with _lock:
        _cache["key"] = key
        _cache["snap"] = snap
    return date8, snap


def load_series() -> list:
    if not os.path.exists(SERIES):
        return []
    try:
        rows = _read_json(SERIES)
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def history_before(date8: str) -> list:
    """返回 date8 之前（不含当日）的序列，供情绪温度的"历史分位"用。"""
    return [r for r in load_series() if str(r.get("date")) < date8]


def save_snapshot(snap: dict) -> str:
    os.makedirs(SNAP_DIR, exist_ok=True)
    day = snap["trade_date"]
    with open(os.path.join(SNAP_DIR, day + ".json"), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    _cache["key"] = None
    return day


def save_series(rows: list) -> None:
    os.makedirs(DATA, exist_ok=True)
    with open(SERIES, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 实时层（三源合并）
def load_bundle() -> Tuple[Optional[dict], dict]:
    """读 data/live/bundle.json —— 榜单/题材/个股页的唯一数据入口。

    请求期不联网：这里只读文件。文件不存在就返回 (None, {})，页面显示
    "还没刷新过"，而不是现场去抓（那样上游一抖动整站白屏）。
    带 mtime 缓存，因为这几个页面每次都要这几百 KB。
    """
    if not os.path.exists(BUNDLE):
        return None, {}
    mtime = os.path.getmtime(BUNDLE)
    key = (BUNDLE, mtime)
    with _lock:
        if _cache.get("bkey") == key:
            return _cache["bundle"], _cache["bmeta"]
    with open(BUNDLE, encoding="utf-8") as f:
        p = json.load(f)
    data = p.get("data") or {}
    meta = dict(p.get("meta") or {})
    meta["fetched_at"] = p.get("fetched_at")
    with _lock:
        _cache["bkey"] = key
        _cache["bundle"] = data
        _cache["bmeta"] = meta
    return data, meta


def save_bundle(data: dict, meta: dict) -> str:
    os.makedirs(LIVE_DIR, exist_ok=True)
    import time as _t
    payload = {"fetched_at": _t.strftime("%Y-%m-%dT%H:%M:%S"), "meta": meta, "data": data}
    tmp = BUNDLE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, BUNDLE)
    _cache["bkey"] = None
    return BUNDLE


def stock(code6: str):
    """按 6 位代码取单只票。返回 (entry, meta)；没有就 (None, meta)。"""
    data, meta = load_bundle()
    if not data:
        return None, meta
    return (data.get("stocks") or {}).get(code6), meta


# ---------------------------------------------------------------- P3 三个栏目
def _live_json(name: str):
    """读 data/live/<name>.json（带 mtime 缓存）。不存在返回 (None, {})。"""
    p = os.path.join(LIVE_DIR, name + ".json")
    if not os.path.exists(p):
        return None, {}
    mtime = os.path.getmtime(p)
    key = (p, mtime)
    with _lock:
        hit = _cache.get("j:" + name)
        if hit and hit[0] == key:
            return hit[1], hit[2]
    try:
        with open(p, encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return None, {}
    meta = {"mtime": mtime}
    with _lock:
        _cache["j:" + name] = (key, obj, meta)
    return obj, meta


def load_attr():
    """涨停/炸板池快照（fetchers/attr.py 产出）。"""
    return _live_json("attr")


def load_brief():
    """简报源解析快照（fetchers/brieffeed.py 产出）。"""
    return _live_json("brief")


def load_reasons():
    """驱动词缓存：取 data/reasons/ 下最新日期的文件。"""
    d = os.path.join(DATA, "reasons")
    if not os.path.isdir(d):
        return None, {}
    files = sorted(x for x in os.listdir(d) if x.endswith(".json"))
    if not files:
        return None, {}
    p = os.path.join(d, files[-1])
    mtime = os.path.getmtime(p)
    key = (p, mtime)
    with _lock:
        hit = _cache.get("j:reasons")
        if hit and hit[0] == key:
            return hit[1], hit[2]
    try:
        with open(p, encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return None, {}
    meta = {"file": files[-1], "mtime": mtime}
    with _lock:
        _cache["j:reasons"] = (key, obj, meta)
    return obj, meta
