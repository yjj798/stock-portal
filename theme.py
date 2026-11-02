# -*- coding: utf-8 -*-
"""消息面主线归并（theme）—— 行业/概念之上的那一层。

为什么要有这一层
----------------
痛点（用户 2026-11-02 原话）："AI 短剧、AI 漫剧、出版传媒……其实都是 AI 视频，
你把它分成 AI 短剧、AI 漫剧，概念就分散了，集中度在细支里体现不出来。"

实测当天池内 140 只票、401 个标签，其中同一个消息面被拆成了 17 个名字：

    短剧游戏(8) · AI视频(7) · AI漫剧(4) · AI短剧(4) · 微短剧(3)
    文化传媒概念(4) · AI语料(4) · AI影视(2) · 漫剧(2) · 短剧出海(1)
    影视版权(1) · AI出版(1) · 出版发行(1) · 数字出版(1) · 影视内容(1)
    影视制作(1) · 长视频平台(1) · 山东IPTV(1) · 人工智能影视(1)

每个细支都不满 5 只，谁都撑不起一条主线；而并集是 20 只、涨停 7 只——
这才是"今天的主线"。同理"机床=机器人"：东财没有"机器人行业"指数
（机器人是概念板块 BK0800），机床/工控/减速器是它的上游，行业链里看不出来。

三层结构（自上而下）
--------------------
    ① 消息面主线 theme  ← 本模块：把同一条消息带动的细支归并（AI 视频 / 机器人 / 算力…）
    ② 概念 concept      ← 细分标签与东财概念板块，作为主线的**证据链**
    ③ 行业 industry     ← 申万式行业链（F10 一/二/三级）

归并规则必须可解释，所以这里只做两件事，不做"猜"：
    · 每个标签按关键词归到一条主线，取**最长匹配**（"短剧互动游戏"命中"短剧"而非"游戏"）
    · 未命中任何主线的标签原样保留，不硬塞

打分上的两个后果（都写进页面口径）：
    1. 一只票同一主线只计一次（原来挂 5 个 AI 视频细支会被累加 5 次，虚高且不稳）
    2. 主线成分是并集，样本变大 → 上升广度收缩后更接近真实，不容易被 3 只小样本骗

⚠️ `catalyst` 字段是**人工整理的题材逻辑**，不是抓来的新闻原文。页面必须标清，
   否则就成了编造消息面。真实新闻源本项目没有接入，不假装有。
"""
from __future__ import annotations

import collections
import re

# "XX板块下跌/上涨"是行情描述不是题材，作证据要剔掉（成员判定不受影响）
_QUOTE_TAG = re.compile("板块(上涨|下跌|走弱|走强)|^(涨幅|跌幅)")

# 主线定义。order 越小越"具体"，同长度关键词冲突时优先。
# kw 用**子串**匹配中文标签；avoid 里的词命中则拒绝（防止"游戏"吞掉"短剧游戏"这类误判）。
THEMES = [
    {
        "id": "ai_video", "name": "AI 视频", "order": 1,
        "short": "AI 短剧 / 漫剧 / 影视 / 出版传媒",
        "catalyst": "AI 短剧与 AI 漫剧集中上线、平台分账与 AI 内容扶持落地，"
                    "把短剧、漫剧、影视、出版传媒、IP 版权串成一条线——"
                    "内容生产端降本，最先反映在有版权和产能的传媒出版股上。",
        "kw": ["短剧", "漫剧", "微短剧", "AI视频", "AI影视", "人工智能影视", "超清视频",
               "影视", "院线", "传媒", "出版", "IPTV", "长视频", "影视版权",
               "影视内容", "影视制作", "文化传媒", "AI语料", "数字阅读", "IP经济",
               "知识产权", "版权"],
        "avoid": [],
    },
    {
        "id": "robot", "name": "机器人", "order": 1,
        "short": "人形机器人 / 关节 / 减速器 / 工业母机",
        "catalyst": "特斯拉 Optimus 量产节点与国内人形机器人订单落地，"
                    "带动减速器、丝杠、灵巧手、伺服、机床（工业母机）这条硬件链——"
                    "整机在海外，关节和加工设备在国内，所以机床股会被当成机器人上游炒。",
        "kw": ["机器人", "人形", "减速器", "灵巧手", "丝杠", "伺服", "执行器", "谐波",
               "工业母机", "机床", "PEEK", "丝杠", "滚柱", "空心杯", "无框力矩",
               "机器视觉", "自动化设备"],
        "avoid": [],
    },
    {
        "id": "semi", "name": "算力硬件", "order": 2,
        "short": "CPO / 光模块 / PCB / 存储 / 先进封装",
        "catalyst": "海外大厂资本开支上修 + 国产算力招标，"
                    "从光模块（CPO）、PCB、存储、先进封装一路传导，是今年的老主线，"
                    "涨的是订单能见度而不是题材想象。",
        "kw": ["CPO", "共封装", "光模块", "光通信", "光纤", "铜缆", "PCB", "覆铜板",
               "存储", "先进封装", "封装", "算力", "液冷", "服务器", "交换机",
               "铜连接", "光芯片", "硅光"],
        "avoid": [],
    },
    {
        "id": "ai_app", "name": "AI 应用", "order": 3,
        "short": "智能体 / 多模态 / AIGC / AI 眼镜",
        "catalyst": "大模型迭代与智能体（Agent）落地，落到办公、教育、营销等应用侧；"
                    "这条线最宽也最杂，所以只收应用侧，不吞视频/内容侧。",
        "kw": ["AI应用", "AI智能体", "智能体", "多模态", "AIGC", "智谱", "大模型",
               "AI眼镜", "AIPC", "AI手机", "AI教育", "AI办公", "AI营销", "AI安全",
               "AI工业", "AI医疗"],
        "avoid": [],
    },
    {
        "id": "space", "name": "商业航天", "order": 2,
        "short": "火箭 / 卫星 / 低轨星座",
        "catalyst": "低轨星座组网与商业火箭发射窗口，"
                    "带的是卫星制造、火箭配套、地面站这条链。",
        "kw": ["商业航天", "卫星", "航天", "低轨", "火箭", "北斗", "星链"],
        "avoid": [],
    },
    {
        "id": "zodiac", "name": "生肖谐音", "order": 2, "additive": True,
        "short": "羊字辈这类名字梗（过羊年）",
        "catalyst": "跨年/生肖题材的名字谐音炒作，跟基本面无关，"
                    "纯粹是资金找一个能一起买的由头——"
                    "所以它靠读音扩散（阳/洋/扬 都算羊），不能按字面数。",
        "kw": ["字辈", "生肖"],
        "avoid": [],
    },
    {
        "id": "consumer", "name": "消费", "order": 3,
        "short": "白酒 / 乳业 / 食品 / 餐饮",
        "catalyst": "促消费政策与春节备货预期，白酒、乳业、食品是防御+复苏双属性。",
        "kw": ["白酒", "乳业", "食品", "啤酒", "调味品", "预制菜", "餐饮", "免税",
               "商业百货", "旅游", "酒店"],
        "avoid": [],
    },
    {
        "id": "finance", "name": "金融", "order": 3,
        "short": "券商 / 金融科技 / 互联网金融",
        "catalyst": "成交额放大与并购预期，券商与金融科技（IT 供应商）同涨，"
                    "后者弹性更大但更依赖情绪。",
        "kw": ["券商", "证券", "金融科技", "互联网金融", "期货", "银行", "保险",
               "参股金融", "多元金融"],
        "avoid": [],
    },
    {
        "id": "pharma", "name": "医药", "order": 3,
        "short": "创新药 / CXO / 减肥药 / 器械",
        "catalyst": "创新药出海授权（BD）与医保谈判，"
                    "带的是有管线的创新药和有产能的 CXO。",
        "kw": ["创新药", "医药", "CXO", "减肥药", "医疗器械", "生物医药", "中药",
               "疫苗", "医疗服务"],
        "avoid": [],
    },
    {
        "id": "energy", "name": "新能源", "order": 3,
        "short": "固态电池 / 锂电 / 光伏 / 储能",
        "catalyst": "固态电池中试线与储能招标，"
                    "老赛道靠技术迭代（固态）和政策（储能）找第二波。",
        "kw": ["固态电池", "锂电", "锂电池", "光伏", "储能", "钠电", "风电", "氢能",
               "电池", "逆变器"],
        "avoid": [],
    },
    {
        "id": "restruct", "name": "并购重组", "order": 3,
        "short": "重组 / 国改 / 资产注入",
        "catalyst": "并购六条与国资整合，"
                    "这条线不看行业看事件，个股独立行情居多。",
        "kw": ["并购重组", "重组", "资产注入", "借壳", "举牌"],
        "avoid": [],
    },
    {
        "id": "auto", "name": "汽车链", "order": 4,
        "short": "汽车零部件 / 智能驾驶 / 整车",
        "catalyst": "新车周期与智驾法规推进，零部件跟着整车排产走。",
        "kw": ["汽车零部件", "汽车电子", "整车", "智能驾驶", "车路云", "汽车芯片",
               "轮胎", "汽配"],
        "avoid": [],
    },
]

BY_ID = {t["id"]: t for t in THEMES}

# (kw, theme_id, len(kw)) —— 长的优先，冲突时取更长；同长取 order 小的
_KW = []
for _t in THEMES:
    for _k in _t["kw"]:
        _KW.append((_k, _t["id"], len(_k)))
_KW.sort(key=lambda x: (-x[2], BY_ID[x[1]]["order"]))


def classify(tag: str):
    """标签 → 主线 id。未命中返回 None（不硬塞，留给概念层）。"""
    t = str(tag or "").strip()
    if not t:
        return None
    for kw, tid, _ in _KW:
        if kw in t:
            th = BY_ID[tid]
            if any(a in t for a in th["avoid"]):
                continue
            return tid
    return None


def theme_of_tags(tags):
    """一串标签 → 命中的主线 id 列表（去重、保持定义顺序）。"""
    hit = {classify(t) for t in (tags or [])}
    hit.discard(None)
    return [t["id"] for t in THEMES if t["id"] in hit]


# --------------------------------------------------------- 产业链归属（人工映射）
# 用户 2026-11-02："机床他们不是通用设备了，他们应该是机器人行业。机器人有这个行业吗？"
# 事实：东财**没有**叫「机器人」的行业板块（行业 496 个里没有），
#       机器人是概念板块 BK0800；机床/工控/减速器是它的上游。
# 所以不改 F10 原始口径（那是事实），而是在上面加一层**产业链归属**，
# 明确标"人工映射"，页面同时显示原始行业链，两个都看得到。
CHAIN = {
    "robot": {
        "name": "机器人产业链",
        "industries": ["机床工具", "自动化设备", "通用设备", "专用设备", "电机Ⅱ",
                       "工控设备", "机器人", "仪器仪表", "机械基础件"],
        "concepts": ["机器人", "人形机器人", "减速器", "工业母机", "灵巧手", "伺服",
                     "机器人执行器", "丝杠", "PEEK材料", "机器视觉"],
        "note": "东财无「机器人」行业指数，机床/工控/减速器按产业链归到机器人上游",
    }
}


def chain_of(ind_name: str, concepts) -> list:
    """行业链最细一级 + 概念板块 → 命中的产业链（人工映射）。

    双条件（行业 ∈ industries 且 概念含机器人相关）才算——
    只按行业会把全市场 212 只通用设备都算成机器人，那就成了普涨标签。
    """
    cs = [str((x or {}).get("name") if isinstance(x, dict) else x) for x in (concepts or [])]
    hit = []
    for cid, spec in CHAIN.items():
        if (ind_name or "") not in spec["industries"]:
            continue
        if not any(k in c for k in spec["concepts"] for c in cs):
            continue
        hit.append(cid)
    return hit


def build(stocks, f10, tags_of, cblocks=None) -> dict:
    """归并出主线 + 每票归属。

    返回
    ----
    {
      "rows": [ {id, name, short, catalyst, codes, n, lu, max_board, heat, best_name,
                 avgpct, up, tags:[{tag,n}], blocks:[{name,pct,pct_rank}], chain_codes} ],
      "by_code": {code: {ids:[...], main:id, ev:{id:[标签...]}, chain:[...]}},
      "ntags": {code: [归并后的标签]}     # 供 score 复用：同一主线只留一个合成标签
    }
    """
    cblocks = cblocks or {}
    stocks = stocks or {}
    f10 = f10 or {}

    # 每票的原始标签 = 同花顺原因/标签 + F10 所属概念板块（后者更规范，覆盖更全）
    raw = {}
    for c, e in stocks.items():
        ts = list(tags_of(e) or [])
        for x in ((f10.get(c) or {}).get("concepts") or []):
            nm = str((x or {}).get("name") or "").strip()
            if nm:
                ts.append(nm)
        raw[c] = list(dict.fromkeys(ts))

    # 先算产业链归属（人工映射），再决定主归属——机床这类票要先认到机器人链上
    chain_ids = {}
    for c in raw:
        ind = ((f10.get(c) or {}).get("industries") or [])
        finest = ind[-1]["name"] if ind else ((stocks.get(c) or {}).get("industry"))
        chain_ids[c] = chain_of(finest, (f10.get(c) or {}).get("concepts"))

    by_code, ev = {}, {}
    for c, ts in raw.items():
        ids = theme_of_tags(ts)
        main = None
        if ids:
            # 主归属优先级：① 产业链命中（人工映射的机器人链这类硬归属）
            #               ② 命中的主线里证据标签最多的（并列取 order 小的）
            cnt = collections.Counter(classify(t) for t in ts if classify(t))
            chain = [i for i in (chain_ids.get(c) or []) if i in ids]
            pool = chain or ids
            main = max(pool, key=lambda i: (cnt.get(i, 0), -BY_ID[i]["order"]))
        ind = ((f10.get(c) or {}).get("industries") or [])
        finest = ind[-1]["name"] if ind else ((stocks.get(c) or {}).get("industry"))
        by_code[c] = {"ids": ids, "main": main, "chain": chain_ids[c], "finest": finest,
                      "ev": {i: [t for t in ts if classify(t) == i
                                 and not _QUOTE_TAG.search(t)] for i in ids}}
        ev[c] = by_code[c]["ev"]

    # 归并后的标签序列：主线合成标签（一个主线一个） + 未归类的原始标签
    ntags = {}
    for c, ts in raw.items():
        out, seen = [], set()
        for t in ts:
            tid = classify(t)
            if tid:
                if tid in seen:
                    continue
                seen.add(tid)
                out.append(BY_ID[tid]["name"])
            else:
                out.append(t)
        ntags[c] = list(dict.fromkeys(out))

    # 主线聚合
    rows = []
    for th in THEMES:
        tid = th["id"]
        codes = [c for c, v in by_code.items() if tid in v["ids"]]
        if not codes:
            continue
        tagcnt = collections.Counter()
        for c in codes:
            for t in by_code[c]["ev"].get(tid) or []:
                tagcnt[t] += 1
        # 关联的东财概念板块：同一个关键词规则套在板块名上
        blocks = []
        for nm, v in cblocks.items():
            if classify(nm) == tid:
                blocks.append({"name": nm, "pct": v.get("pct"), "up": v.get("up"),
                               "down": v.get("down"), "leader": v.get("leader"),
                               "net": v.get("net")})
        blocks.sort(key=lambda x: -(x.get("pct") or -99))
        indcnt = collections.Counter(by_code[c]["finest"] for c in codes
                                     if by_code[c].get("finest"))
        rows.append({
            "id": tid, "name": th["name"], "short": th["short"],
            "industries": [{"name": k, "n": v} for k, v in indcnt.most_common(6)],
            "catalyst": th["catalyst"], "codes": sorted(codes), "n": len(codes),
            # 核心成员＝这只票的主归属就是本主线（或产业链归到这条线）。
            # 光洋股份挂「AI应用」是被东财宽板块带进来的，主归属其实是机器人，
            # 所以它算 AI 应用的关联成员而不是核心——否则龙头会选到不相干的票。
            "core_codes": sorted(c for c in codes
                                 if th.get("additive")
                                 or by_code[c]["main"] == tid
                                 or tid in (by_code[c]["chain"] or [])),
            "tags": [{"tag": k, "n": v} for k, v in tagcnt.most_common()],
            "n_tags": len(tagcnt), "blocks": blocks[:8], "n_blocks": len(blocks),
            "chain_codes": [c for c in codes if th["id"] in (by_code[c]["chain"] or [])],
        })

    return {"rows": rows, "by_code": by_code, "ntags": ntags, "raw": raw,
            "meta": {"n_theme": len(rows), "n_tag": len(_KW),
                     "n_merged": sum(1 for c, ts in raw.items()
                                     for t in ts if classify(t))}}


def link_tags(rows, tags_pool) -> None:
    """把标签池里的 n / up 挂到主线证据上，页面直接显示"AI短剧(4只)"。"""
    for r in rows:
        for t in r["tags"]:
            g = (tags_pool or {}).get(t["tag"]) or {}
            t["up"] = g.get("up")
            t["rising"] = g.get("rising")
