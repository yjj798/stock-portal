# -*- coding: utf-8 -*-
"""原子落盘：JSON 写文件 + rename。

为什么单独抽出来
----------------
原来三处各写一份 `path + ".tmp"` 再 `os.replace()`：
    store.py:120        data/bundle.json
    sector.py:181       data/sector_hist.json
    fetchers/base.py:101 data/live/<name>.json
单进程跑没问题，可这台机器上**同一个进程会有两个**（daemon 定时 refresh +
手动 `python refresh.py`）。两边共用同一个 tmp 路径时：

    16:31 daemon 写完 tmp → 正要 replace
    16:31 手动那一轮把 tmp 打开重写（Windows 上已被别人打开的文件不能重新打开写）
    → PermissionError [WinError 5] '...json.tmp' -> '...json'

实测 2026-11-02 16:31 就是这条，bundle.degraded 里挂了一整轮 industry，
数据本身没错（另一轮成功写入），但降级标记会让人以为抓取失败。

两条修法，缺一不行
------------------
1. **tmp 名唯一**：`<path>.<pid>-<tid>-<seq>.tmp`。两个进程各写各的，互不覆盖。
2. **replace 重试**：Windows 的 rename 不是原子抢占，目标文件被杀毒/编辑器/另一
   个 replace 短暂持有句柄时会抛 WinError 5 / 32。指数退避重试 6 次（合计约 1.2s
   封顶）足够跨过这种瞬时占用；真占住了就抛原错，不吞。

只做这一件事，不掺业务逻辑——调用方仍旧只关心"文件最后是不是完整的新内容"。
"""
from __future__ import annotations

import itertools
import json
import os
import threading
import time

_seq = itertools.count(1)
_tls = threading.local()

# WinError 5（拒绝访问）/ 32（正被另一进程使用）/ 33（锁定冲突）都当瞬时占用
_TRANSIENT = {5, 32, 33}


def tmp_name(path: str) -> str:
    """同目录下的唯一临时名。同进程不同线程、不同进程都不会撞。"""
    d, base = os.path.split(path)
    return os.path.join(d, ".%s.%d-%d-%d.tmp" % (
        base, os.getpid(), threading.get_ident() % 100000, next(_seq)))


def _retry(fn, tries: int = 6, base: float = 0.02):
    last = None
    for i in range(tries):
        try:
            return fn()
        except OSError as e:                      # noqa: PERF203
            code = getattr(e, "winerror", None)
            if code not in _TRANSIENT:
                raise
            last = e
            time.sleep(base * (2 ** i))
    raise last


def write_json(path: str, obj, **dump_kw) -> str:
    """把 obj 写成 JSON 并原子替换到 path。返回 path。

    `dump_kw` 透传给 json.dump（ensure_ascii / indent / sort_keys …）。
    """
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    dump_kw.setdefault("ensure_ascii", False)
    tmp = tmp_name(path)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, **dump_kw)
            f.flush()
            os.fsync(f.fileno())
        _retry(lambda: os.replace(tmp, path))
    except BaseException:
        # 失败就别在 data/ 里留垃圾；删不掉也不算错（可能是别人正在读）
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def sweep(directory: str) -> int:
    """清掉历史遗留的 `<name>.tmp` 与 `.<name>.*.tmp`（崩溃/竞态残留）。返回删除数。

    只删本模块命名规则能识别的临时文件，不碰任何正式数据。
    """
    if not os.path.isdir(directory):
        return 0
    n = 0
    for fn in os.listdir(directory):
        if not (fn.endswith(".tmp") and (fn.startswith(".") or fn.count(".") == 1)):
            continue
        p = os.path.join(directory, fn)
        try:
            if os.path.isfile(p):
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n
