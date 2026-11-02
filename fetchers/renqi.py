# -*- coding: utf-8 -*-
"""人气榜抓取（yjj798/renqibang）。

这份 data.json 是整站最重要的一个源：截图里那一行
「澳洋健康 ¥5.91 95.2 216.4万·日 第7名 +110.1% 脑机接口+医疗服务+国资控股+"羊"字辈 龙头 利多强」
每个字段都在这儿，不需要再去逆向同花顺 App。

字段对应（逐条对过原文）：
    price=5.91  score_final=95.2  ths_heat=2163992(→216.4万)  heat_rank=7
    heat_growth=110.1  concept_all='脑机接口+医疗服务+国资控股+“羊”字辈'
    is_leader=true  benefit_lv='强'

注意：**不能读 D:\\ai\\renqibang\\data.json 那份本地文件**——它停在 2026-10-30，
盘中不会更新，拿它当源会让整站"看起来有数据但其实是旧的"。只能走网络。
"""
from __future__ import annotations

from . import base

# 通道顺序 = 新鲜度优先。人气榜盘中每 30 分钟由 GH Actions 提交一次，
# 所以"缓存型 CDN"只能兜底：
#   1.legaga.top  自家域名，GH Pages 每次提交即重建 → 永远最新，且直连 0.4s
#   gh-proxy      第三方反代，实测拿到的是最新提交
#   jsdelivr      @main 最长缓存 12h，盘中会滞后 —— 只当安慰剂
#   raw           本机两条路都超时，放最后
CHANNELS = [
    ("1.legaga", "https://1.legaga.top/data.json", (False, True)),
    ("gh-proxy", "https://gh-proxy.com/https://raw.githubusercontent.com/yjj798/renqibang/main/data.json", (False, True)),
    ("jsdelivr", "https://cdn.jsdelivr.net/gh/yjj798/renqibang@main/data.json", (False, True)),
    ("gh-raw", "https://raw.githubusercontent.com/yjj798/renqibang/main/data.json", (True, False)),
]

NAME = "renqi"


def fetch(save: bool = True) -> dict:
    """拉取并（可选）落盘。返回原始 data.json 的 dict。"""
    obj, note = base.pick_json(CHANNELS, timeout=15)
    if not isinstance(obj, dict) or "leaderboard" not in obj:
        raise base.FetchError("人气榜返回结构异常：缺 leaderboard（拿到 %s）" % type(obj).__name__)
    if save:
        base.save(NAME, obj, {"channel": note,
                              "updated_at": obj.get("updated_at"),
                              "quote_date": obj.get("quote_date"),
                              "intraday": obj.get("intraday")})
    return obj


def load():
    return base.load(NAME)


def stock_map(renqi: dict) -> dict:
    """把 scores（148 只全字段）+ leaderboard（10 只）按 6 位代码合并成索引。

    两者字段基本相同；leaderboard 是综合分 TOP10、scores 是参与评分的全体。
    合并策略：scores 先铺底，leaderboard 覆盖（它是同口径的更高优先级切片）。
    """
    out = {}
    for key in ("scores", "leaderboard", "fallback"):
        for s in (renqi.get(key) or []):
            c = base.code6(s.get("code"))
            if not c:
                continue
            cur = out.setdefault(c, {})
            cur.update({k: v for k, v in s.items() if v is not None})
            cur["code"] = c
            cur.setdefault("name", s.get("name") or "")
    return out
