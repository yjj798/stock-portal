# -*- coding: utf-8 -*-
"""个股所属板块采集（东财 F10「核心题材」接口）。

为什么需要它
------------
原来每只票只有一个行业名（行情接口 f100），只能落到**申万二级**：沈阳机床 →
通用设备。可通用设备全市场 212 只，板块指数涨幅天天贴着大盘中位数，永远判"行业不热"；
而它真正所在的细口径是三级「机床工具」（19 只），在那一层它才是领涨股。

用户 2026-11-02 的原话是「每个股的行业标签要从 F10 里找」，要的就是这层：
一只票通常挂 3 个行业（一/二/三级）＋若干概念板块，标签不是唯一的。

接口
----
GET https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax?code=SZ000410
返回 ssbk（所属板块）列表，每条带 BOARD_CODE / BOARD_NAME / BOARD_RANK / IS_PRECISE：
    BOARD_RANK 1~3  行业链：机械设备 → 通用设备 → 机床工具（越往后越细）
    BOARD_RANK 4    地域板块（辽宁板块）
    IS_PRECISE=1    概念板块（工业母机、人工智能、央国企改革…）
    其余            风格/事件板块（小盘成长、昨日涨停、连续亏损…）

BOARD_CODE 是纯数字，东财板块行情的代码是 BK + 四位补零（545 → BK0545，
1395 → BK1395），两边能精确 join，不用按名字猜。

口径注意
--------
* 必须按代码并发抓（137 只约 15 秒）；单线程一只 0.3s 也能跑，但 refresh 里会拖时间。
* 接口对个别票返回空（新股/停牌），**不编造**：该票 industries 为空，页面标「无板块数据」。
* 缓存按日：同一天重复刷新直接读 data/live/f10.json，不重复打接口。
"""
from __future__ import annotations

import gzip
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

from . import base

NAME = "f10"

F10_URL = ("https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax"
           "?code=%s")

MAX_WORKERS = 6
RETRY_SLEEP = 0.15


def _sec(code: str) -> str:
    c = str(code).zfill(6)
    return ("SH" if c[0] in "65" else "SZ") + c


def _get_json(url: str, timeout: float = 20.0):
    """取 JSON。东财这个接口会**无条件 gzip 压缩**（不管有没有发 Accept-Encoding），
    base.get 只返回原始 bytes，不解压就会 JSONDecodeError —— 一开始 20 只挂 10 只
    就是这个原因，看着像限流，其实是压缩体没解。
    """
    body, _note = base.get(url, timeout=timeout, tries_proxy=(False, True))
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return json.loads(body.decode("utf-8", "replace"))


def one(code: str) -> dict:
    """抓一只票的所属板块。失败抛异常，由上层决定是否降级。"""
    obj = _get_json(F10_URL % _sec(code))
    if not isinstance(obj, dict):
        raise base.FetchError("F10 返回异常：%s" % type(obj))
    if obj.get("status") not in (None, 0):
        raise base.FetchError("F10 拒绝：%s" % obj.get("message"))
    rows = obj.get("ssbk") or []
    inds, cons = [], []
    for r in rows:
        name = str(r.get("BOARD_NAME") or "").strip()
        bcode = str(r.get("BOARD_CODE") or "").strip()
        if not name or not bcode:
            continue
        rank = r.get("BOARD_RANK")
        item = {"code": "BK%04d" % int(bcode) if bcode.isdigit() else bcode,
                "name": name, "rank": rank}
        if isinstance(rank, int) and 1 <= rank <= 3:
            inds.append(item)                 # 行业链，越靠后越细
        elif r.get("IS_PRECISE") in (1, "1"):
            cons.append(item)                 # 概念板块
    return {"industries": inds, "concepts": cons,
            "n_boards": len(rows)}


def fetch(codes, save: bool = True) -> dict:
    """并发抓一批票。返回 {code: {industries, concepts, n_boards, err?}}。"""
    codes = [str(c).zfill(6) for c in codes]
    out, errs = {}, 0
    t0 = time.time()

    def work(c):
        for i in range(2):
            try:
                return c, one(c), None
            except Exception as e:            # noqa: BLE001
                if i == 0:
                    time.sleep(RETRY_SLEEP)
                    continue
                return c, None, str(e)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for c, got, err in ex.map(work, codes):
            if got:
                out[c] = got
            else:
                errs += 1
                out[c] = {"industries": [], "concepts": [], "n_boards": 0, "err": err}

    if save:
        base.save(NAME, out, {
            "n": len(out), "n_err": errs,
            "n_with_ind": sum(1 for v in out.values() if v["industries"]),
            "n_with_con": sum(1 for v in out.values() if v["concepts"]),
            "secs": round(time.time() - t0, 1),
        })
    return out


def load(max_age: float = None):
    """返回 ({code: 板块}, meta)。base.load 已经解包过 data 层。"""
    data, meta = base.load(NAME, max_age=max_age)
    return data or {}, meta or {}


def cached(codes, max_age: float = 6 * 3600) -> dict:
    """优先用当天缓存；缺的票补齐抓。返回 {code: 板块}。"""
    codes = [str(c).zfill(6) for c in codes]
    old, _meta = base.load(NAME)
    old = old or {}
    fresh = {c: old[c] for c in codes
             if isinstance(old.get(c), dict) and old[c].get("industries")}
    miss = [c for c in codes if c not in fresh]
    if not miss:
        return fresh
    try:
        fresh.update(fetch(miss))
    except Exception:                          # noqa: BLE001
        pass
    return fresh
