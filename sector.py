# -*- coding: utf-8 -*-
"""行业维度：把申万行业指数读数变成可评分的「行业热度」，并判定双轮共振。

为什么加这一维
--------------
原来的四维只看「概念」。可概念是同花顺按涨停原因归的**故事标签**（羊字辈、
脑机接口、CPO），它有个先天毛病：一只票只要挂上一个热门词，概念分就上去了——
哪怕整个行业都在跌、只有它一只在动。反过来，行业整体抬升（光伏设备全线涨价、
影视院线集体复苏）时，票即使没有题材词，也会被算成"没有逻辑"。

所以行业与概念是两个不同的问题：
    行业 = 这一片是不是整体在动（同涨同跌，由产业景气/政策/价格驱动）
    概念 = 有没有一个故事把若干票串起来（题材联动，由资金偏好驱动）
两者同时热 = 双重硬逻辑，比单一维度硬；只有一边热 = 单腿，容易一日游。

分怎么给
--------
个股行业分（0~14），三项都取**全市场行业排名**而不是绝对值，因为大盘普涨时
+3% 只是中位数、全场下跌时 +0.5% 就已经最强，绝对涨幅会随大盘漂：
    涨幅分位 7   —— 该行业指数涨幅在全部 400+ 个行业里的分位（0~1）
    上涨广度 4   —— 板块内上涨家数占比（up/(up+down)），防"几只权重拉指数"
    主力净额 3   —— 板块主力净额的分位（钱是不是真进来了，只作辅助）

共振加成（0~6）
    行业热（涨幅分位 ≥0.85 且 上涨家数过半）＋ 概念热（概念分 ≥ 12.5/25）
    同时成立 → +6，标记「双轮」；只热一边 → 0，按主导方标记「行业」或「概念」。
    单边不给分是刻意的：给了就等于给所有概念热票普涨一次分，通胀掉整个榜单。

总分口径
--------
原四维 100 分**一分没动**（`base100` 原样保留，历史可比），行业 0~14 与
共振 0~6 是加在后面的，满分 120。这样做的好处是老分数仍然能对得上旧结论，
新维度只是让"行业也在动"的票浮上来，而不是把整张榜推翻重排。
"""
from __future__ import annotations

import json
import os

import bisect

# 行业分三项权重（合计 14）
IND_W = {"pct": 7.0, "breadth": 4.0, "net": 3.0}
IND_FULL = 14.0

# 「行业热」判据：涨幅分位 + 上涨家数占比
HOT_PCT = 0.85          # 全市场行业涨幅分位
HOT_BREADTH = 0.50      # 板块内上涨家数占比
HOT_PCT_STRONG = 0.95   # 分位极高时可以放宽广度（普跌日里的绝对强者）

# 「概念热」判据：概念分（0~25）过半
CON_HOT = 12.5

RESO_PTS = 6.0          # 双轮共振加成

HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sector_hist.json")


def _pctile(vals, v) -> float:
    if not vals or v is None:
        return 0.0
    return bisect.bisect_left(vals, v) / max(len(vals) - 1, 1)


def _breadth(b) -> float | None:
    up, down = b.get("up"), b.get("down")
    if up is None or down is None:
        return None
    tot = up + down
    return round(up / tot, 3) if tot else None


SEED = 6.0      # 广度收缩强度：一个只有 1 只成分的行业 "1 涨 0 跌" 不该算 100% 广度


def _breadth_adj(br, b) -> float | None:
    """广度贝叶斯收缩。样本越小越往 0.5 拉——1 涨 0 跌是 100%，但那只是一个样本。

    普涨日几乎所有行业的广度都 >0.8，绝对占比几乎没有区分度，
    所以打分再用分位（下面按全行业广度分位给分），收缩只为让分位有意义。
    """
    if br is None:
        return None
    up, down = b.get("up") or 0, b.get("down") or 0
    n = up + down
    if n <= 0:
        return None
    return round((up + 0.5 * SEED) / (n + SEED), 3)


def blocks_of(data) -> dict:
    """从 bundle 取行业读数；bundle 没带（老数据/降级）时退回 data/live/industry.json。"""
    ind = (data or {}).get("industry") or {}
    blk = ind.get("blocks") or {}
    if blk:
        return blk
    try:
        from fetchers import industry as ind_f
        got, _meta = ind_f.load()
        return got or {}
    except Exception:            # noqa: BLE001
        return {}


def by_code_of(data) -> dict:
    ind = (data or {}).get("industry") or {}
    m = dict(ind.get("by_code") or {})
    if m:
        return m
    return {c: e["industry"] for c, e in ((data or {}).get("stocks") or {}).items()
            if e.get("industry")}


# ------------------------------------------------------------------ 历史（跨日加速）
def load_hist() -> dict:
    if not os.path.exists(HIST):
        return {}
    try:
        with open(HIST, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:            # noqa: BLE001
        return {}


def save_hist(date: str, blocks: dict, keep: int = 60) -> str:
    """按日留存行业涨幅，只为一件事：算"较昨日快了多少"（加速）。

    存的是每天收盘（或最近一次刷新）的行业涨幅快照，一天一条，覆盖写。
    没有历史时页面就只显示当日读数，不编造"加速"。
    """
    if not date or not blocks:
        return ""
    h = load_hist()
    h[date] = {k: round(float(v["pct"]), 2) for k, v in blocks.items()
               if v.get("pct") is not None}
    for old in sorted(h)[:-keep]:
        h.pop(old, None)
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    tmp = HIST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False)
    os.replace(tmp, HIST)
    return HIST


def delta(blocks: dict, name: str, qdate: str = "") -> float | None:
    """该行业涨幅相对上一有记录交易日的差（pp）。没有历史 → None。"""
    h = load_hist()
    days = [d for d in sorted(h) if d < (qdate or "9999-99-99")]
    if not days:
        return None
    prev = h[days[-1]].get(name)
    now = (blocks.get(name) or {}).get("pct")
    if prev is None or now is None:
        return None
    return round(float(now) - float(prev), 2)


# ------------------------------------------------------------------ 主计算
def build(data, base_by_code: dict) -> dict:
    """行业桶 + 个股行业分 + 双轮判定。

    base_by_code 是已算好的原四维明细（含 concept 分与概念名单），
    本函数只读它的 concept / concept_detail，不反向依赖 score。
    """
    blocks = blocks_of(data)
    codes_ind = by_code_of(data)
    stocks = (data or {}).get("stocks") or {}
    qdate = str((data or {}).get("quote_date") or "")

    # 全市场分位池：用全部行业（400+），不是池内命中那几个——
    # 池只有 170 只票、几十个行业，按池内排名会把"池子里没人"的强行业抹掉。
    pcts = sorted(v["pct"] for v in blocks.values() if v.get("pct") is not None)
    nets = sorted(v["net"] for v in blocks.values() if v.get("net") is not None)
    # 广度也分位化：普涨日几乎所有行业都"过半上涨"，绝对占比没有区分度
    brs = sorted(x for x in (_breadth_adj(_breadth(v), v) for v in blocks.values())
                 if x is not None)

    # ---- 行业桶（池内成员 + 板块读数），供 /industry 页与首页用
    bucket = {}
    for c, e in stocks.items():
        name = codes_ind.get(c) or e.get("industry")
        if not name or name not in blocks:
            continue
        b = bucket.setdefault(name, {"name": name, "members": [], "lu": 0, "pcts": []})
        b["members"].append(c)
        # board_tag 存在（"3天3板"）本身就是"今日封板"的意思，比 limit_up 字段更全：
        # 人气榜那批票没有 limit_up 标记，但有连板标签。
        if e.get("limit_up") or e.get("board_tag"):
            b["lu"] += 1
        if e.get("pct") is not None:
            b["pcts"].append(float(e["pct"]))

    rows = []
    for name, b in bucket.items():
        blk = blocks[name]
        pr = _pctile(pcts, blk.get("pct"))
        br = _breadth(blk)
        ba = _breadth_adj(br, blk)
        brp = _pctile(brs, ba) if ba is not None else 0.5
        avg = round(sum(b["pcts"]) / len(b["pcts"]), 2) if b["pcts"] else None
        # 行业热度分（100 制，只用于行业榜排序，不参与个股总分）
        f_pct = 45.0 * pr
        f_br = 25.0 * brp
        f_lu = 20.0 * min(b["lu"], 5) / 5.0
        f_rise = 10.0 * (max(0.0, min(1.0, (avg + 2) / 10.0)) if avg is not None else 0.5)
        rows.append({
            "name": name, "n": len(b["members"]), "codes": sorted(b["members"]),
            "pct": blk.get("pct"), "pct_rank": round(pr, 3),
            "up": blk.get("up"), "down": blk.get("down"), "breadth": br,
            "breadth_adj": ba, "breadth_rank": round(brp, 3),
            "net": blk.get("net"), "leader": blk.get("leader"),
            "leader_code": blk.get("leader_code"),
            "lu": b["lu"], "avgpct": avg,
            "delta": delta(blocks, name, qdate),
            "sub": {"pct": round(f_pct, 1), "br": round(f_br, 1),
                    "lu": round(f_lu, 1), "rise": round(f_rise, 1)},
            "total": round(f_pct + f_br + f_lu + f_rise, 1),
            # 行业本身算不算"热"：指数与广度都要过半市场同行（收缩后的广度）
            "hot": bool((pr >= HOT_PCT and (ba is None or ba >= HOT_BREADTH))
                        or (pr >= HOT_PCT_STRONG
                            and (blk.get("pct") or 0) > 0)),
        })
    rows.sort(key=lambda x: (-x["total"], -x["n"], x["name"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    hot_by_name = {r["name"]: r["hot"] for r in rows}
    rank_by_name = {r["name"]: r for r in rows}

    # ---- 个股行业分 + 双轮
    out = {}
    for c, base in (base_by_code or {}).items():
        name = codes_ind.get(c) or (stocks.get(c) or {}).get("industry")
        blk = blocks.get(name) or {}
        if not name or not blk:
            cp = base.get("concept") or 0
            out[c] = {"name": None, "pts": 0.0, "reso": 0.0,
                      "drive": "概念" if cp >= CON_HOT else "无",
                      "note": "无行业归属数据"}
            continue
        pr = _pctile(pcts, blk.get("pct"))
        br = _breadth(blk)
        ba = _breadth_adj(br, blk)
        brp = _pctile(brs, ba) if ba is not None else 0.5
        nr = _pctile(nets, blk.get("net"))
        f_pct = IND_W["pct"] * pr
        # 广度缺失给一半分：不是"广度为 0"，是没数据，不该罚
        f_br = IND_W["breadth"] * (brp if ba is not None else 0.5)
        f_net = IND_W["net"] * nr
        pts = round(f_pct + f_br + f_net, 1)

        ind_hot = bool(hot_by_name.get(name))
        cp = base.get("concept") or 0
        con_hot = cp >= CON_HOT
        reso = RESO_PTS if (ind_hot and con_hot) else 0.0
        if ind_hot and con_hot:
            drive = "双轮"
        elif ind_hot:
            drive = "行业"
        elif con_hot:
            drive = "概念"
        else:
            drive = "无"

        row = rank_by_name.get(name) or {}
        out[c] = {
            "name": name, "pts": pts, "reso": reso, "drive": drive,
            "pct": blk.get("pct"), "pct_rank": round(pr, 3),
            "breadth": br, "breadth_adj": ba, "breadth_rank": round(brp, 3),
            "net": blk.get("net"),
            "hot": ind_hot, "con_hot": con_hot,
            "rank": row.get("rank"), "n": row.get("n"),
            "leader": row.get("leader"), "delta": row.get("delta"),
            "sub": {"pct": round(f_pct, 1), "breadth": round(f_br, 1),
                    "net": round(f_net, 1)},
            "note": ("行业涨幅分位 %.0f%% · 板块涨跌 %s/%s · 主力 %s"
                     % (pr * 100, blk.get("up") if blk.get("up") is not None else "—",
                        blk.get("down") if blk.get("down") is not None else "—",
                        ("%.2f 亿" % (blk["net"] / 1e8)) if blk.get("net") is not None else "—")),
        }

    return {
        "by_code": out,
        "rows": rows,
        "meta": {
            "n_blocks": len(blocks), "n_rows": len(rows),
            "n_hot": sum(1 for r in rows if r["hot"]),
            "n_double": sum(1 for v in out.values() if v["drive"] == "双轮"),
            "n_ind_only": sum(1 for v in out.values() if v["drive"] == "行业"),
            "n_con_only": sum(1 for v in out.values() if v["drive"] == "概念"),
            "n_none": sum(1 for v in out.values() if v["drive"] == "无"),
            "n_missing": sum(1 for v in out.values() if not v.get("name")),
            "weights": dict(IND_W), "full": IND_FULL,
            "reso_full": RESO_PTS, "con_hot": CON_HOT,
            "hot_pct": HOT_PCT, "hot_breadth": HOT_BREADTH,
        },
    }
