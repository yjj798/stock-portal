# -*- coding: utf-8 -*-
"""抓取层公共件：HTTP 取数 + 多通道回退 + 本地缓存。

为什么要有"通道回退"
--------------------
实测本机网络：`raw.githubusercontent.com` 必须走代理才通，`cdn.jsdelivr.net` 和
`1.legaga.top` 反而直连更快。同一份数据常常有三个镜像，硬编码一条线路等于把
单点故障写进代码。这里按"通道列表"逐个试，第一个成功的胜出，并把实际生效的
通道记在返回值里——出问题时能一眼看出是"源挂了"还是"线路挂了"。

两条硬规则
----------
1. **抓取不在请求期发生**。页面只读 data/live/ 下的缓存文件；缓存不存在就显示
   "还没刷新"，不是现场去抓。否则上游一抖动整站白屏。
2. **抓到的原始字节落盘**，解析失败还能人工看原文，不用重抓。
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIVE = os.environ.get("PORTAL_LIVE") or os.path.join(ROOT, "data", "live")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class FetchError(Exception):
    pass


def _open(url: str, use_proxy: bool, timeout: float):
    if use_proxy:
        opener = urllib.request.build_opener()
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Referer": "https://eq.10jqka.com.cn/",
    })
    return opener.open(req, timeout=timeout)


def get(url: str, timeout: float = 12.0, tries_proxy=(True, False)):
    """取一个 URL，代理/直连都试一遍。返回 (bytes, 说明)。"""
    errs = []
    for use_proxy in tries_proxy:
        tag = "proxy" if use_proxy else "direct"
        try:
            with _open(url, use_proxy, timeout) as r:
                body = r.read()
                if not body:
                    raise FetchError("空响应")
                return body, "%s %d B" % (tag, len(body))
        except (urllib.error.URLError, socket.timeout, FetchError, OSError) as e:
            errs.append("%s:%s" % (tag, type(e).__name__))
        except Exception as e:  # noqa: BLE001  http.client 的各种怪异常
            errs.append("%s:%s" % (tag, type(e).__name__))
    raise FetchError("%s 全部通道失败（%s）" % (url, ", ".join(errs)))


def get_json(url: str, timeout: float = 12.0, tries_proxy=(True, False)):
    body, note = get(url, timeout, tries_proxy)
    return json.loads(body.decode("utf-8", "replace")), note


def pick_json(channels, timeout: float = 12.0, tries_proxy=(True, False)):
    """channels: [(名字, url)] 或 [(名字, url, 该通道的代理尝试顺序)]。

    逐个试，第一个成功的胜出。通道顺序按**实测成功率**排，不按官方程度排——
    2026-11-02 实测：jsDelivr 0.6s 通、raw.githubusercontent 两边都超时。
    """
    errs = []
    for ch in channels:
        name, url = ch[0], ch[1]
        tp = ch[2] if len(ch) > 2 else tries_proxy
        try:
            obj, note = get_json(url, timeout, tp)
            return obj, "%s · %s" % (name, note)
        except Exception as e:  # noqa: BLE001
            errs.append("%s(%s)" % (name, type(e).__name__))
    raise FetchError("所有通道均失败：" + ", ".join(errs))


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def save(name: str, obj, meta: dict = None) -> str:
    """落盘到 data/live/<name>.json，外层包一层元信息（抓取时间/通道）。"""
    os.makedirs(LIVE, exist_ok=True)
    path = os.path.join(LIVE, name + ".json")
    payload = {"_fetched_at": _stamp(), "_meta": meta or {}, "data": obj}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)  # 原子替换：读端永远看到完整文件
    return path


def load(name: str, max_age: float = None):
    """读 data/live/<name>.json。返回 (data, meta)；不存在返回 (None, None)。

    max_age（秒）给定时，超龄视为过期但仍返回数据，由调用方决定用不用——
    这里不擅自删，因为"昨天的榜"比"空白"对用户有用得多。
    """
    path = os.path.join(LIVE, name + ".json")
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            p = json.load(f)
    except Exception:
        return None, None
    meta = dict(p.get("_meta") or {})
    meta["fetched_at"] = p.get("_fetched_at")
    if max_age is not None:
        try:
            age = time.time() - os.path.getmtime(path)
        except OSError:
            age = 0
        meta["age"] = age
        meta["stale"] = age > max_age
    return p.get("data"), meta


def code6(c) -> str:
    """'002172.SZ' / '002172' / 2172 → '002172'。全站主键统一用 6 位代码。"""
    s = str(c or "").strip()
    if "." in s:
        s = s.split(".", 1)[0]
    s = "".join(ch for ch in s if ch.isdigit())
    return s.zfill(6) if s else ""
