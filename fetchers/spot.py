# -*- coding: utf-8 -*-
"""实时行情叠加（东财全市场快照，新浪批量兜底）。

为什么要有这一层：
    人气榜（yjj798/renqibang）是**收盘后**才更新的源，盘中 updated_at 还停在上
    一个交易日。整站个股的 price / pct / turnover 都来自它，于是午盘看榜单页会
    看到"行情日 = 前天"，价格是旧的——数据本身没错，但**时点错了**。
    这一层只做一件事：用盘中实时行情覆盖 price/pct/amount/turnover 四个字段，
    其余（热度、综合分、概念、排名历史）仍归人气榜，那是它独有的，别去动。

口径：
    price/pct 为不复权盘中价；amount 单位元；turnover 单位 %。
    停牌（price 为空或 0）不覆盖——宁可留旧值，也不要写个 0 进去。
"""
from __future__ import annotations

import time
import urllib.request

from . import base

NAME = "spot"

EM_URL = ("https://push2.eastmoney.com/api/qt/clist/get"
          "?pn=1&pz=6000&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
          "&fltt=2&invt=2&fid=f3"
          "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
          # f100 = 所属行业（申万二级名，如「软件开发」「光伏设备」）。
          # 这一个字段就是全市场行业归属的真值——比按名字/概念猜准得多，
          # 而且和行业板块指数（m:90+t:2）用同一套行业名，能直接对上。
          "&fields=f2,f3,f5,f6,f8,f12,f14,f18,f100")

SINA_URL = "https://hq.sinajs.cn/list="
SINA_HDRS = {"Referer": "https://finance.sina.com.cn",
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _em() -> dict:
    """东财全市场快照。pz 上限 100（实测给了 6000 也只回 100），必须翻页。"""
    out = {}
    pn = 1
    total = None
    while pn <= 60:
        url = EM_URL.replace("pn=1", "pn=%d" % pn)
        obj = base.pick_json([("eastmoney", url, (False, True))], timeout=20)[0]
        data = (obj or {}).get("data") or {}
        if total is None:
            total = data.get("total") or 0
        diff = data.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        if not diff:
            break
        for r in diff:
            code = str(r.get("f12") or "")
            price = r.get("f2")
            if len(code) != 6 or not isinstance(price, (int, float)) or price <= 0:
                continue                  # 停牌 / 无价：跳过，别用 0 覆盖
            ind = str(r.get("f100") or "").strip()
            out[code] = {"price": float(price),
                         "pct": r.get("f3") if isinstance(r.get("f3"), (int, float)) else None,
                         "amount": r.get("f6") if isinstance(r.get("f6"), (int, float)) else None,
                         "turnover": r.get("f8") if isinstance(r.get("f8"), (int, float)) else None,
                         "prev_close": r.get("f18") if isinstance(r.get("f18"), (int, float)) else None,
                         # "-" 是东财给"无行业"（新股/停牌/纯 B 股）的占位，不能当行业名用
                         "industry": ind if ind and ind != "-" else None}
        if len(diff) < 100:            # 最后一页不满 100 只 = 到头了
            break
        pn += 1
    if len(out) < 3000:
        raise base.FetchError("东财行情条数异常：只有 %d 只（total=%s）" % (len(out), total))
    return out


def _sina_get(lst: str) -> str:
    """新浪行情是 GBK 编码、且校验 Referer，base.get 的固定头不适用，这里自己发。"""
    req = urllib.request.Request(SINA_URL + lst, headers=SINA_HDRS)
    last = None
    for use_proxy in (False, True):
        try:
            handler = (urllib.request.ProxyHandler({}) if not use_proxy
                       else urllib.request.ProxyHandler())
            with urllib.request.build_opener(handler).open(req, timeout=15) as r:
                return r.read().decode("gbk", "replace")
        except Exception as e:            # noqa: BLE001
            last = e
    raise base.FetchError("新浪行情失败：%s" % last)


def _sina(codes) -> dict:
    """新浪批量兜底，一次 200 只。字段顺序：名称,开,昨收,现价,高,低,...,成交量,成交额。"""
    out = {}
    codes = list(codes)
    for i in range(0, len(codes), 200):
        batch = codes[i:i + 200]
        lst = ",".join(("sh" if c[0] in "6" else "sz") + c for c in batch)
        txt = _sina_get(lst)
        for line in (txt or "").splitlines():
            if "=" not in line or '"' not in line:
                continue
            code = line.split("=")[0].split("_")[-1][2:]
            parts = line.split('"')[1].split(",")
            if len(parts) < 32:
                continue
            try:
                price = float(parts[3])
                prev = float(parts[2])
            except ValueError:
                continue
            if price <= 0 or prev <= 0:
                continue
            out[code] = {"price": price,
                         "pct": round((price / prev - 1) * 100, 2),
                         "amount": float(parts[9] or 0),
                         "turnover": None,
                         "prev_close": prev}
        time.sleep(0.2)
    if not out:
        raise base.FetchError("新浪行情也没拿到")
    return out


def fetch(codes=None, save: bool = True) -> dict:
    """返回 {code: {...}}。codes 给了就只留这些（新浪兜底时按需请求）。"""
    src = "eastmoney"
    try:
        data = _em()
    except Exception:                      # noqa: BLE001
        data = _sina(codes or [])
        src = "sina"
    if codes:
        data = {c: v for c, v in data.items() if c in set(codes)}
    if not data:
        raise base.FetchError("实时行情为空")
    if save:
        base.save(NAME, data, {"src": src, "n": len(data),
                               "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    return data


def save(data: dict, meta: dict = None) -> str:
    return base.save(NAME, data, meta or {})


def load():
    return base.load(NAME)


def overlay(stocks: dict, spot: dict) -> int:
    """把行情覆盖进个股索引，返回覆盖条数。

    只动行情字段与「所属行业」：价格/涨幅/成交额/换手来自实时快照，
    行业归属（f100）也从这里顺手带进来——全市场一次翻页就有，
    不必再去单独发一轮 5400 只的请求。
    """
    n = 0
    for code, e in stocks.items():
        s = spot.get(code)
        if not s or not s.get("price"):
            continue
        e["price"] = s["price"]
        if s.get("pct") is not None:
            e["pct"] = s["pct"]
        if s.get("amount"):
            e["amount"] = s["amount"]
        if s.get("turnover"):
            e["turnover"] = s["turnover"]
        if s.get("industry"):
            e["industry"] = s["industry"]
        e["quote_at"] = "spot"
        n += 1
    return n
