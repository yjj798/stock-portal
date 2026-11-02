# -*- coding: utf-8 -*-
"""涨停/炸板池抓取（东财 push2ex），产出归因页要的离线快照。

为什么单独一源、不并进 bundle：
    涨停池是按「交易日」取的全市场池子（47 只涨停 + 31 只炸板），和本站人气池
    （约 167 只有人气数据的票）是两个不同的集合。硬塞进 stocks 会把两套口径
    搅在一起——人气榜只有 49 只涨停里的少数几只。

口径事实（实测，写在这里免得后人再猜）：
    · 涨停池接口**忽略 date 参数**、恒返回最新交易日，并在 data.qdate 自报数据日
      ⇒ 标题日必须取 qdate，不能取 today（凌晨取会错一天）
    · 「昨日」= 上一个**交易日**，用「涨停池非空」向前回溯定位，不是日历减一天
      （周一会落到周日 → 全 0）
    · zttj = {days, ct}：区间口径（16 天 8 板），lbc = 连板高度。分组用 lbc，
      zttj 只作灰色补充——两者不等时以 lbc 为准

题材分发服务器（49.235.48.7 的 4427/4421/4450）2026-11-02 实测全日期 404，
所以本模块不依赖它：概念/驱动词改用本站 reasons_core 抓的同花顺 keywordList
（详见 render/page_attr.py 的口径说明）。
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urllib.request  # noqa: E402

UT = "7eea3edcaed734bea9cbfc24409ed989"
ZT_URL = ("https://push2ex.eastmoney.com/getTopicZTPool?ut={ut}&dpt=wz.ztzt"
          "&Pageindex=0&pagesize=600&sort=fbt%3Aasc&date={date}")
ZB_URL = ("https://push2ex.eastmoney.com/getTopicZBPool?ut={ut}&dpt=wz.ztzt"
          "&Pageindex=0&pagesize=600&sort=fbt%3Aasc&date={date}")
SINA_KLINE = ("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
              "?symbol={sym}&scale=240&ma=no&datalen=11")
EM_KLINE = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
            "&klt=101&fqt=1&fields1=f1,f2,f3&fields2=f51,f53&beg=0&end=20500101")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/ztb/",
}
DATE_RE = re.compile(r"^\d{8}$")


def _get_json(url: str, timeout: float = 20.0):
    """直连取 JSON（绕开环境代理）+ 自带 Referer。

    base.get_json 把 Referer 硬编码成同花顺，东财这边必须换；而且这两个域名
    实测**直连比走代理快**，所以不套 base 的双通道重试。
    """
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers=HEADERS)
    with op.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _pool(url: str, date8: str) -> tuple[str, list]:
    """拿一个池子，返回 (接口自报数据日, 归一后的行)。"""
    raw = _get_json(url.format(ut=UT, date=date8), timeout=20)
    data = raw.get("data") or {}
    qdate = str(data.get("qdate") or "")
    out = []
    for x in data.get("pool") or []:
        code = str(x.get("c") or "").zfill(6)
        if not re.fullmatch(r"\d{6}", code):
            continue
        zttj = x.get("zttj") or {}
        out.append({
            "code": code,
            "name": x.get("n") or "",
            "price": round((x.get("p") or 0) / 1000.0, 2),
            "pct": _f(x.get("zdp")),
            "amount": _f(x.get("amount")),
            "turnover": _f(x.get("hs")),
            "ltsz": _f(x.get("ltsz")),
            "board": int(x.get("lbc") or 0) or int(zttj.get("ct") or 1),
            "days": int(zttj.get("days") or 0),
            "ct": int(zttj.get("ct") or 0),
            "fbt": int(x.get("fbt") or 0),          # 首次封板 HHMMSS
            "lbt": int(x.get("lbt") or 0),          # 最后封板
            "zbc": int(x.get("zbc") or 0),          # 炸板次数
            "fund": _f(x.get("fund")),              # 封单金额（元）
            "industry": x.get("hybk") or "",
            "zbc_time": int(x.get("zbcTime") or 0) if x.get("zbcTime") else 0,
        })
    return qdate, out


def _f(v):
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None


def _sina_sym(code: str) -> str:
    if code.startswith(("6", "9")):
        return "sh" + code
    if code.startswith(("4", "8")):
        return "bj" + code
    return "sz" + code


def _kline_one(code: str):
    """取一只票的 11 根日K，返回 (10日涨幅, 失败原因)。主通道新浪，兜底东财。

    踩坑记录（2026-11-02）：东财 push2his 并发 12 × 77 只当场触发风控，
    之后连**单发**都 RemoteDisconnected（按 IP 拉黑，备用数字节点同样），冷却未知；
    腾讯 ifzq 并发 16 跑到一半整池回 501，且不带任何可重试语义。
    所以主通道换成新浪（未复权，10 日窗口内除权的票会有小幅偏差，口径说明里注明），
    并发压到 8、每票之间 sleep，宁可慢也别把数据源打挂——挂了没人给你解封。
    """
    try:
        d = _get_json(SINA_KLINE.format(sym=_sina_sym(code)), timeout=10)
        rows = d if isinstance(d, list) else []
        if len(rows) >= 11:
            old, new = float(rows[0]["close"]), float(rows[-1]["close"])
            if old > 0:
                return round((new / old - 1) * 100, 1), None
        return None, "sina rows<11"
    except Exception as e:  # noqa: BLE001
        first = "%s:%s" % ("sina", type(e).__name__)
    try:
        d = _get_json(EM_KLINE.format(secid=_secid(code)), timeout=10)
        rows = ((d.get("data") or {}).get("klines")) or []
        if len(rows) >= 11:
            old, new = float(rows[-11].split(",")[1]), float(rows[-1].split(",")[1])
            if old > 0:
                return round((new / old - 1) * 100, 1), None
        return None, "em rows<11"
    except Exception as e:  # noqa: BLE001
        return None, "%s/%s:%s" % (first, "em", type(e).__name__)


def range_gains(codes: list, workers: int = 8, pause: float = 0.08) -> dict:
    """涨停池 10 日涨幅：倒数第 11 根收盘 → 最新收盘，主通道新浪。"""
    import time as _t
    ok, fail = {}, []
    codes = list(codes)

    def run_batch(batch, out_ok, out_fail):
        for c in batch:
            g, err = _kline_one(c)
            if g is not None:
                out_ok[c] = g
            else:
                out_fail.append("%s:%s" % (c, err))
            _t.sleep(pause)

    # 单一共享列表带锁太啰嗦，直接按分片各写各的桶，最后合并
    shards = [codes[i::workers] for i in range(workers)]
    from concurrent.futures import ThreadPoolExecutor
    buckets = [({}, []) for _ in shards]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_batch, sh, buckets[i][0], buckets[i][1])
                for i, sh in enumerate(shards) if sh]
        for f in futs:
            f.result()
    for ok_b, fail_b in buckets:
        ok.update(ok_b)
        fail += fail_b
    if fail and len(fail) >= len(codes):
        raise RuntimeError("区间涨幅全军覆没（示例 %s）" % ", ".join(fail[:3]))
    range_gains.last_failures = fail[:5]
    return ok


def prev_trade_day(date8: str, lookback: int = 12) -> str:
    """上一个交易日：拿涨停池有没有数据当判据，向前回溯自然日。"""
    import datetime as dt
    d = dt.datetime.strptime(date8, "%Y%m%d")
    for i in range(1, lookback + 1):
        t = (d - dt.timedelta(days=i)).strftime("%Y%m%d")
        try:
            _, pool = _pool(ZT_URL, t)
            if pool:
                return t
        except Exception:  # noqa: BLE001
            continue
    return ""


def fetch(date8: str | None = None) -> dict:
    """抓今日 + 上一交易日的涨停池/炸板池，附涨停池 10 日涨幅。"""
    import datetime as dt

    req = date8 if (date8 and DATE_RE.fullmatch(date8)) else dt.date.today().strftime("%Y%m%d")
    errors = []

    qdate, zt = _pool(ZT_URL, req)
    if not qdate:
        qdate = req
    # 接口忽略 date，自报的数据日才是真的；显式回看时仍以请求日为准
    data_day = req if date8 else qdate

    zb = []
    try:
        zb = _pool(ZB_URL, data_day)[1]
    except Exception as e:  # noqa: BLE001
        errors.append("炸板池: %s" % e)

    y8 = prev_trade_day(data_day)
    zt_y, zb_y = [], []
    if y8:
        try:
            zt_y = _pool(ZT_URL, y8)[1]
            zb_y = _pool(ZB_URL, y8)[1]
        except Exception as e:  # noqa: BLE001
            errors.append("昨日池: %s" % e)

    gains = {}
    try:
        gains = range_gains(sorted({x["code"] for x in zt + zt_y}))
        lf = getattr(range_gains, "last_failures", [])
        if lf:
            errors.append("区间涨幅部分失败: %s" % ", ".join(lf))
    except Exception as e:  # noqa: BLE001
        errors.append("区间涨幅: %s" % e)

    return {
        "qdate": data_day,
        "prev_date": y8,
        "fetched_at": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "today": {"zt": zt, "zb": zb},
        "prev": {"zt": zt_y, "zb": zb_y},
        "gains": gains,
        "errors": errors,
    }


def save(obj: dict) -> str:
    from store import LIVE_DIR
    os.makedirs(LIVE_DIR, exist_ok=True)
    p = os.path.join(LIVE_DIR, "attr.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return p


if __name__ == "__main__":
    r = fetch(sys.argv[1] if len(sys.argv) > 1 else None)
    p = save(r)
    print("数据日 %s　上一交易日 %s" % (r["qdate"], r["prev_date"]))
    print("  今日涨停 %d　炸板 %d　昨日涨停 %d　昨日炸板 %d　区间涨幅 %d 只"
          % (len(r["today"]["zt"]), len(r["today"]["zb"]), len(r["prev"]["zt"]),
             len(r["prev"]["zb"]), len(r["gains"])))
    if r["errors"]:
        print("  降级：", r["errors"])
    print("写入", p)
