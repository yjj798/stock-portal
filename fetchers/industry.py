# -*- coding: utf-8 -*-
"""行业板块指数采集（东财行业板块行情）。

为什么要这一层
--------------
原来的分类只有「概念」：同花顺的 concept_all 给的是题材（羊字辈、脑机接口、
CPO…），全是**故事**。可一只票上涨有时是行业整体在动（光伏设备全线抬升），
有时才是纯题材联动。只有概念一维时，这两种情况在页面上长得一模一样，
评分也只能奖励"故事热"，看不出"行业也在加速"。

数据来源两个字段，都是东财公开接口：
    m:90+t:2  → 行业板块列表（申万二级＋三级共约 500 个），带
                f3 涨幅 / f62 主力净额 / f104 上涨家数 / f105 下跌家数 / f128 领涨股
    个股 f100 → 所属行业名（在 fetchers/spot.py 里随行情一次翻页带回）

两者行业名是同一套（实测抽样 100 只，39/40 精确命中，唯一未命中是 "-" 占位），
所以不需要自造映射表，也不需要按名字猜。

口径注意
--------
* 板块涨幅 f3 是**指数涨幅**（成分股市值加权），不是等权平均。行业里大盘股多，
  指数涨幅就会和"多数票在涨"背离（几只权重拉升、小票在跌）。页面上两个数都给，
  判断"行业是不是真在加速"要看上涨家数占比，不能只看指数涨幅。
* 主力净额 f62 单位为元，正负号是净流入/流出。板块级净额会被超大单主导，
  只作为辅助证据，不进主分。
* 板块是分页返回的（pz 上限 100），必须翻页；只取前 100 个会把「影视院线」
  这类靠后的行业整段丢掉。
"""
from __future__ import annotations

import bisect

from . import base

NAME = "industry"

BLK_URL = ("https://push2.eastmoney.com/api/qt/clist/get"
           "?pn=%d&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
           "&fltt=2&invt=2&fid=f3&fs=%s"
           "&fields=f3,f12,f14,f62,f104,f105,f128,f140")

MAX_PAGE = 8          # 约 500 个板块 / 100 = 5 页，留余量

# 行业板块与概念板块是**同一套接口**，只差 fs 参数：
#   m:90+t:2 → 行业（申万式，496 个）
#   m:90+t:3 → 概念（题材，531 个）
# 字段完全一致，所以打分可以用同一个函数——用户 2026-11-02 要求两页"格式一样"，
# 底层就该是同一份读数，而不是各写一套。
KINDS = {
    "industry": {"fs": "m:90+t:2", "name": "industry", "min": 50},
    "concept": {"fs": "m:90+t:3", "name": "concept_sector", "min": 100},
}


def _num(v):
    return v if isinstance(v, (int, float)) else None


def fetch(save: bool = True, kind: str = "industry") -> dict:
    """返回 {板块名: 板块读数}。行业名与个股 f100 同一套命名。

    kind="industry"（默认，保持旧调用不变）或 "concept"。
    """
    spec = KINDS.get(kind) or KINDS["industry"]
    name = spec["name"]
    out = {}
    total = None
    for pn in range(1, MAX_PAGE + 1):
        obj = base.pick_json([("eastmoney", BLK_URL % (pn, spec["fs"]), (False, True))],
                             timeout=25)[0]
        data = (obj or {}).get("data") or {}
        if total is None:
            total = data.get("total")
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        if not diff:
            break
        for r in diff:
            bname = str(r.get("f14") or "").strip()      # 别叫 name：会覆盖上面的保存名
            pct = _num(r.get("f3"))
            if not bname or pct is None:
                continue
            up, down = _num(r.get("f104")), _num(r.get("f105"))
            out[bname] = {
                "code": r.get("f12"),
                "pct": round(float(pct), 2),
                "net": _num(r.get("f62")),
                "up": int(up) if up is not None else None,
                "down": int(down) if down is not None else None,
                "leader": (r.get("f128") or "").strip() or None,
                "leader_code": (str(r.get("f140") or "").strip() or None),
            }
        if len(diff) < 100:
            break
    if len(out) < spec["min"]:
        raise base.FetchError("%s 板块条数异常：只有 %d 个（total=%s）"
                              % (kind, len(out), total))
    if save:
        base.save(name, out, {"n": len(out), "total": total, "kind": kind})
    return out


def load_kind(kind: str = "industry"):
    """按类型读盘。industry → data/live/industry.json；concept → concept_sector.json"""
    spec = KINDS.get(kind) or KINDS["industry"]
    return base.load(spec["name"])


def save(data: dict, meta: dict = None) -> str:
    return base.save(NAME, data, meta or {})


def load():
    return base.load(NAME)


def pct_rank(blocks: dict) -> dict:
    """行业名 → 涨幅分位（0~1，1 = 全市场行业里涨得最多）。

    分位而不是绝对值：某个交易日全市场普涨 3%，涨幅 3% 的行业只是中位数；
    另一天全场下跌，+0.5% 就已经是最强。用绝对涨幅会让评估随大盘漂移。
    """
    vals = sorted((v.get("pct") for v in (blocks or {}).values()
                   if v.get("pct") is not None))
    if not vals:
        return {}
    n = len(vals)
    out = {}
    for k, v in (blocks or {}).items():
        p = v.get("pct")
        if p is None:
            continue
        out[k] = round(bisect.bisect_left(vals, p) / max(n - 1, 1), 3)
    return out
