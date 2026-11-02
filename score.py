# -*- coding: utf-8 -*-
"""个股综合评分 v3 —— 五维加权：排名趋势 35 + 概念趋势 25 + 上榜原因 20 + 资金 20
＋ 行业热度 14，另加双轮共振 6（满分 120）。

v3 相对 v2 只做加法
------------------
v2 四维（100 分）**一分未改**，原样留在 `base100` 里，历史结论仍可对得上。
新增两笔加在总分后面：
    行业热度 0~14 —— 它这一片是不是整体在动（详见 sector.py）
    双轮共振 0~6  —— 行业在加速 **且** 概念也在热，双重硬逻辑才给
单边热（只有行业、或只有概念）不加共振分：给了就等于给所有概念热票普涨一次，
榜单会整体通胀，反而看不出"双轮"的稀缺。

为什么要区分行业与概念
----------------------
概念是同花顺按涨停原因归的故事标签（羊字辈、脑机接口、CPO）。一只票挂上热门词
概念分就上去了，哪怕整个行业在跌、只有它一只在动；反过来行业整体抬升（影视院线
集体复苏）时，票就算没有题材词也会被算成"没逻辑"。两个维度问的是不同问题：
    行业＝这一片是不是整体在动（同涨同跌，产业景气驱动）
    概念＝有没有一个故事把若干票串起来（题材联动，资金偏好驱动）
两者同时成立，才是"双重硬逻辑"；只有一边，多半是一日游。

v2 原文（口径未变）
------------------
旧「综合分」直接用上游人气榜的 `score_final`，本质是**静态截面打分**：热度多高、
资金多少、几个板。它抓不到最重要的一件事——**这只票的名次正在以多快的速度往上冲**。

实测反例（2026-10-30 行情，002088 鲁阳节能）：
    tdx 名次  1572 → 1937 → 652 → 227 → 127 → 29
    5 个交易日从千名外冲到第 29，且 5 步中 4 步在降（只有一步小幅回撤）。
    这种票在旧口径里连榜都上不了（它不在人气榜那 148 只里），而它恰恰是当周最强的一类形态。
新的第一维就是这件事，占 35 分——权重最高，因为"趋势"是本模型存在的理由。

四维构成
--------
① 排名趋势 35 = 速度 14 + 稳定 11 + 位置 10
   速度＝日均对数改善（log 名次差 / 步数）。用对数而不是差值，是因为
   1900→600（+1300 名）和 60→20（+40 名）在信息量上不可比，对数尺度才公平。
   稳定＝下降步数占比。连涨 5 步得满分，来回震荡只得一半——"很快很稳"要两样都占。
   位置＝当前名次分档，越靠前越高（前 10 满分）。

② 概念趋势 25 = Σ(标签强度)，再按全池 p95 归一
   标签池由三个源合并去重后重建：人气榜 concept_all + tdx limit_up_reason + 热榜 concept_tag。
   单个标签的强度 = min(成分数, 10) × 上升成分占比。
   **成分少于 3 个的标签不参与打分**——2 只票的概念，一只涨停就 100% "上升"，
   那是噪声不是趋势（实测降门槛到 2 只会让评分更乱）。
   泛标签（业绩增长/高股息/三季报…）不参与，它们不指向产业逻辑。

③ 上榜原因 20 = 按硬逻辑关键词数分档
   硬逻辑＝产能/订单/中标/供货/净利/研报/涨价/签约…（可验证的经营事实）
   纯情绪（生肖/传闻/炒作）且无任何硬逻辑 → 3 分。
   只有当日异动记录才计分；几天前的旧异动记 0（见 page_stock 的分档展示规则）。

④ 资金 20 = 成交额池内分位 12 + 涨幅 6 + 换手率 2
   **坑：`turnover` 在人气榜是换手率(%)、在 tdx 是成交额(元)，量纲差 7 个数量级。**
   两者必须分开建池，混池会让所有 tdx 票的资金分恒为满分（实测踩过，见 06-坑库）。

无排名历史的票
--------------
只有 tdx 榜上的票才有 30 天名次序列。其余票用热度日环比做**代理趋势**，
且最高只给 21 分（35 × 0.6）——单点环比证明不了"连续上升"，必须打折，
否则没有趋势数据的票会盖过真有趋势的。
"""
from __future__ import annotations

import bisect
import collections
import math
import re

import news as news_mod
import pinyin_map
import sector
import theme as theme_mod

# 泛标签：不指向具体产业逻辑，不参与概念打分（仍会在页面上原样展示）
#
# 「三季报扭亏 / 减亏」不在泛标签里，这是 2026-11-02 按用户判断改的口径：
#   扭亏是**事件**（从亏到盈的拐点），不是「业绩好」这种普遍现象。
#   业绩增长/三季报大增这类标签池里有 20 只，天然全员上涨，算进趋势等于给大盘加分；
#   而扭亏只有 4 只，是明确的困境反转信号。混在一起会把真信号稀释成噪声。
WIDE = {
    "业绩增长", "大消费", "其他", "ST股", "次新股", "预盈预增", "超跌反弹", "低价股", "破净股",
    "高送转", "参股金融", "融资融券", "机构重仓", "基金重仓", "QFII重仓", "社保重仓",
    "深股通", "沪股通", "MSCI中国", "标准普尔", "富时罗素", "股权转让", "举牌", "壳资源",
    "此前涨幅较大", "高股息精选", "证金持股", "同花顺中特估100", "三季报增长", "三季报大增",
    "三季报", "超级品牌", "昨日涨停", "大盘蓝筹", "中字头股票",
    # 2026-11-02 加：全池 140 只里 33 只挂"人工智能"、47 只挂"央国企改革"，
    # 这两条不是概念而是底色——挂它的票概念分凭空 +10，等于给普涨日再加一次普涨。
    # 用户原话："AI 软件里边包含太多，太笼统"。剔除后它们仍作为标签展示，只是不计分。
    "人工智能", "央国企改革", "国企改革",
    "连续亏损", "预亏预减", "摘帽", "退市风险",
}

HARD = re.compile("产能|订单|中标|供货|营收|净利|业绩|研报|涨价|投产|量产|签约|合作|获批|"
                  "扩产|增持|回购|专利|新签|同比|增长|出货|装机|收购|重组")
SOFT = re.compile("生肖|羊年|情绪|传闻|预期|炒作|概念")

TAG_MIN = 3          # 标签至少几个成分才算"概念"
HIST_POINTS = 6      # 趋势取最近几个名次点（6 个点 = 5 步）
SPEED_CAP = 1.0      # 日均对数改善到 1.0 即满速


def norm_tag(t) -> str:
    """'“羊”字辈' / '"羊"字辈' / '羊字辈' 归一成同一个标签。

    不做这步，同一个概念会被拆成三份成分，谁都凑不够 3 只，
    结果就是"羊字辈"明明 25 只票在涨却判定为"不算概念"。
    """
    t = str(t or "").strip()
    for ch in "“”\"'「」『』 　":
        t = t.replace(ch, "")
    return t


def tags_of(e) -> list:
    """一只票的全部标签：三个源合并去重，顺序保持（前面的更具体）。"""
    out = []
    for src in ((e.get("concept_all") or ""),
                ((e.get("tdx") or {}).get("limit_up_reason") or "")):
        if src:
            out += [norm_tag(x) for x in re.split(r"[+＋、,，]", src) if x.strip()]
    out += [norm_tag(x) for x in ((e.get("hot") or {}).get("concept_tag") or [])]
    return [t for t in dict.fromkeys(out) if t]


# ------------------------------------------------------------------ ① 趋势
def rank_trend(e):
    """近 5 步名次序列 → 速度/稳定/当前位置。没有足够历史返回 None。

    起算点＝窗口内名次最差的那一天，不是窗口第一天。
    差别很大：002088 的窗口是 [1572, 1937, 652, 227, 127, 29]——
    1572→1937 是启动前的一次回撤（洗盘），若把它算进斜率，这只票会被系统性低估。
    按"最差点起算"就是 1937→29，4 步全降，这才对得上"从五天前 1937 到今天 29"。

    最差点落在最后一天（＝一路在退）时退回整窗，让斜率为负。
    """
    h = (e.get("tdx") or {}).get("hist") or []
    rs = [x["rank"] for x in h if x.get("rank")]
    if len(rs) < 3:
        return None
    rs = rs[-HIST_POINTS:]
    i0 = rs.index(max(rs))
    if i0 >= len(rs) - 1:          # 最差点就是最后一天 → 全程退潮，整窗计算
        i0 = 0
    seg = rs[i0:]
    steps = len(seg) - 1
    now, old = seg[-1], seg[0]
    slope = (math.log(old) - math.log(max(now, 1))) / steps if steps else 0.0
    mono = (sum(1 for a, b in zip(seg, seg[1:]) if b < a) / steps) if steps else 0.0
    return {"now": now, "old": old, "slope": round(slope, 3),
            "mono": round(mono, 2), "seq": rs, "seg": seg, "steps": steps}


def trend_pts(t):
    if not t:
        return None
    speed = min(max(t["slope"], 0) / SPEED_CAP, 1.0) * 14
    stab = t["mono"] * 11
    r = t["now"]
    pos = (10 if r <= 10 else 8 if r <= 30 else 6.5 if r <= 50
           else 5 if r <= 100 else 3 if r <= 200 else 1)
    return {"speed": round(speed, 1), "stab": round(stab, 1), "pos": pos,
            "pts": round(speed + stab + pos, 1), "proxy": False}


def proxy_trend(e):
    """无排名历史 → 用热度日环比代理，最高 21 分（35×0.6）。"""
    g = e.get("heat_growth")
    if g is None:
        return {"pts": 0.0, "proxy": False, "note": "无排名历史、无热度环比"}
    g = max(min(float(g), 150.0), -50.0)
    return {"pts": round(min(max(g, 0) / 100.0, 1.0) * 0.6 * 35, 1),
            "proxy": True, "heat_growth": round(g, 1)}


# ------------------------------------------------------------------ ② 概念
def build_tags(stocks, trend, ntags=None):
    """标签池 → {tag: {n, up, strength}}。只保留成分 ≥ TAG_MIN 且非泛标签的。

    ntags（归并后标签）存在时用它：同一主线只计一个合成标签（"AI 视频"），
    不再让 AI短剧 / AI漫剧 / AI视频 / 短剧游戏 四个细支把一只票的概念分累加四遍。
    这样"概念集中度"才落在一条线上，而不是散在细支里互相稀释。
    """
    mem = collections.defaultdict(list)
    for c, e in stocks.items():
        for t in ((ntags or {}).get(c) or tags_of(e)):
            mem[t].append(c)

    tags = {}
    for t, codes in mem.items():
        if t in WIDE or len(codes) < TAG_MIN:
            continue
        slopes = [trend[c]["slope"] for c in codes if trend.get(c)]
        # 涨幅缺失（很多人气榜票只有名次没有涨跌幅）不能当 0 参与均值，
        # 否则概念均涨幅会被系统性拉低（实测 CPO 14 只里只有 2 只有涨幅，
        # 旧写法算出 0.71%，实际这两只是 +4.05% 和 +5.89%）。
        pcts = [stocks[c]["pct"] for c in codes if stocks[c].get("pct") is not None]
        if slopes:
            up = sum(1 for s in slopes if s > 0.15) / len(slopes)
        else:
            up = sum(1 for p in pcts if p > 0) / len(pcts) if pcts else 0
        tags[t] = {"n": len(codes), "up": round(up, 2),
                   "strength": min(len(codes), 10) * up,
                   "avgpct": round(sum(pcts) / len(pcts), 2) if pcts else None,
                   "n_pct": len(pcts),
                   "rising": up >= 0.5}
    return tags


def concept_raw(e, tags, tlist=None):
    tot, detail = 0.0, []
    for t in (tlist if tlist is not None else tags_of(e)):
        g = tags.get(t)
        if not g:
            continue
        tot += g["strength"]
        if g["rising"]:
            detail.append({"tag": t, "n": g["n"], "up": g["up"]})
    return tot, detail


# ------------------------------------------------------- 概念总榜（多因子）
# 为什么不能只用「成分数 × 上升占比」排概念总榜
# ------------------------------------------------
# 旧口径 strength = min(成分数, 10) × 上升占比。两个毛病叠在一起：
#   ① min(n,10) 把 14 只和 25 只截成同一个数，样本量的差别被抹平，
#      于是"谁 100% 在升"变成唯一判据；
#   ② 100% 在升只要池子够小就能拿到——14 只全升和 25 只里 23 只升，
#      前者在信息量上并不更硬，反而更脆。
# 实测（2026-10-30）：共封装光学(CPO) 14 只 14 升、涨停 0 只，靠 10.00 压过
# 羊字辈 25 只 23 升、涨停 10 只、最高 3 板、成员均涨 7.9% 的 9.33。
# 涨停是资金用真金白银投的票，不该输给一个只统计"名次方向"的指标。
#
# 新口径：概念热度分 = 涨停 30 + 上升广度 25 + 人气总量 20 + 赚钱效应 15 + 龙头高度 10
#   涨停 30 = 22 × min(涨停只数,10)/10 + 高度分（≥3 板 8 / 2 板 5 / 1 板 2）
#            涨停只数取「全市场涨停梯队按概念归属计数」与「人气榜 concept_stats」的较大值
#   上升广度 25 = 贝叶斯收缩后的上升占比： (up×n + 0.5×K) / (n + K)，K=8
#            收缩把"3 只全升=100%"压回 0.6 附近，样本越大越接近真实占比
#   人气总量 20 = Σ 1/√(成员人气名次)，再按全榜最大值归一并×20
#            √ 是为了既不放弃"多成员"的总量意义，也不让成员数线性膨胀
#   赚钱效应 15 = 成员均涨幅映射到 0~15（-2% 以下 0 分，+8% 以上满分）
#            只统计有涨幅数据的成员；样本 <3 只则给中性半分并标"样本不足"
#   龙头高度 10 = 概念内最好人气名次（第 1 名满分，200 名开外 0 分）
CON_W = {"lu": 30.0, "up": 25.0, "heat": 20.0, "rise": 15.0, "lead": 10.0}
CON_SEED = 8.0        # 上升占比的先验收缩强度
CON_MIN_PCT = 3       # 均涨幅至少几只样本才算数
THEME_HOT = 80.0      # 「强主线」门槛：分数过 80 且涨停 ≥10（普涨日过半分等于全热）

# 这些不是概念，是「今天这只票因为什么异动」的行情描述（同花顺异动 tag 里混进来的）。
# 拿它当概念会造出"CPO板块下跌"和"共封装光学(CPO)"两个榜位，成员还大面积重合。
NON_CONCEPT = re.compile("板块(上涨|下跌|走弱|走强)|^(涨幅|跌幅|盘中|异动|临停)")


def concept_board(stocks, snap=None, stats=None) -> list:
    """概念总榜：每个概念一行，含五项分项分与总分。

    members 优先取人气榜 concept_stats 的成分（它是按当日 148 只人气榜聚合的，
    比标签池全），没有再退回标签池；两者都缺的概念不参与排名。
    """
    stocks = stocks or {}
    stats = {x.get("concept"): x for x in (stats or []) if x.get("concept")}
    boards = {}
    for lv in ((snap or {}).get("ladder") or []):
        b = int(lv.get("board") or 1)
        for s in (lv.get("stocks") or []):
            c = s.get("code")
            if c:
                boards[c] = max(boards.get(c, 1), b)

    trend = {c: rank_trend(e) for c, e in stocks.items()}
    pool = build_tags(stocks, trend)

    rows = []
    # 排序后遍历：set 的迭代顺序随 PYTHONHASHSEED 变，会让同分概念的名次在每次
    # 构建间漂移（榜单/概念页不可复现，静态发布也就无法判断"真变更"）。
    for name in sorted(set(pool) | set(stats)):
        if name in WIDE or NON_CONCEPT.search(name or ""):
            continue
        st = stats.get(name) or {}
        if st.get("members"):
            codes = [m[2] for m in st["members"] if len(m) > 2 and m[2] in stocks]
        else:
            codes = [c for c, e in stocks.items() if name in tags_of(e)]
        if len(codes) < TAG_MIN:
            continue

        # 「X字辈」是**读音梗**，不是字面梗：源只按关键词收录，名字里同音的票会漏。
        # 实测「羊字辈」源给 24 只，池内读 yang 的其实 27 只——太平洋、扬子新材、
        # 鲁阳节能被漏掉，而用户一眼就看出「泉阳泉也是羊」（名字里是"阳"）。
        # 这里按名称同音补齐，并单独记下补了谁，页面上如实标注来源。
        hp, hp_sound = [], ""
        if name.endswith("字辈"):
            base = name[:-2].strip("“”\"'「」『』 　")
            pys = pinyin_map.readings(base[:1]) if base else ()
            if pys:
                hp_sound = pys[0]
                hp = [c for c, e in stocks.items()
                      if c not in codes
                      and pinyin_map.same_sound(e.get("name") or "", hp_sound)]
                codes = codes + hp

        lu = sum(1 for c in codes if c in boards)
        lu = max(lu, int(st.get("limit_up") or 0))
        mb = max([boards.get(c, 1) for c in codes if c in boards] or [1])
        best = min([stocks[c].get("heat_rank") or 999 for c in codes] or [999])
        best_name = ""
        for c in codes:
            if (stocks[c].get("heat_rank") or 999) == best:
                best_name = stocks[c].get("name") or ""
                break
        heat = sum(1.0 / math.sqrt(max(stocks[c].get("heat_rank") or 999, 1))
                   for c in codes)

        slopes = [trend[c]["slope"] for c in codes
                  if trend.get(c) and trend[c].get("slope") is not None]
        if slopes:
            up = sum(1 for s in slopes if s > 0.15) / len(slopes)
        else:
            pcts = [stocks[c]["pct"] for c in codes if stocks[c].get("pct") is not None]
            up = (sum(1 for p in pcts if p > 0) / len(pcts)) if pcts else 0.0

        pcts = [stocks[c]["pct"] for c in codes if stocks[c].get("pct") is not None]
        avgpct = (sum(pcts) / len(pcts)) if len(pcts) >= CON_MIN_PCT else None

        rows.append({
            "concept": name, "n": len(codes), "codes": codes,
            "limit_up": lu, "max_board": mb, "best_rank": best if best < 999 else None,
            "best_name": best_name, "heat": round(heat, 2),
            "up": round(up, 2), "avgpct": round(avgpct, 2) if avgpct is not None else None,
            "n_pct": len(pcts), "leader": st.get("leader") or best_name,
            "strong": st.get("strong"), "weak": st.get("weak"), "net": st.get("net"),
            "stat_heat": st.get("heat"), "hchg": st.get("hchg"),
            "in_stats": bool(st),
            "homophone": hp, "hp_sound": hp_sound,
            # 归入哪条消息面主线：细支不消失（它是证据），但要知道它被并到哪去了。
            "theme_id": theme_mod.classify(name),
            "theme_name": (theme_mod.BY_ID[theme_mod.classify(name)]["name"]
                           if theme_mod.classify(name) else None),
        })

    if not rows:
        return rows

    mx_heat = max(r["heat"] for r in rows) or 1.0
    for r in rows:
        n = r["n"]
        up_adj = (r["up"] * n + 0.5 * CON_SEED) / (n + CON_SEED)
        f_lu = (22.0 * min(r["limit_up"], 10) / 10.0
                + (8.0 if r["max_board"] >= 3 else 5.0 if r["max_board"] == 2
                   else 2.0 if r["limit_up"] else 0.0))
        f_up = CON_W["up"] * up_adj
        f_heat = CON_W["heat"] * (r["heat"] / mx_heat)
        if r["avgpct"] is None:
            f_rise = CON_W["rise"] * 0.5          # 样本不足 → 中性，不奖不罚
        else:
            f_rise = CON_W["rise"] * max(0.0, min(1.0, (r["avgpct"] + 2) / 10.0))
        f_lead = CON_W["lead"] * max(0.0, (200 - (r["best_rank"] or 200)) / 199.0)
        r["up_adj"] = round(up_adj, 3)
        r["sub"] = {"lu": round(f_lu, 1), "up": round(f_up, 1), "heat": round(f_heat, 1),
                    "rise": round(f_rise, 1), "lead": round(f_lead, 1)}
        r["total"] = round(f_lu + f_up + f_heat + f_rise + f_lead, 1)

    rows.sort(key=lambda x: (-x["total"], -x["n"], x.get("concept") or ""))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# ---------------------------------------------------------------- 主线（消息面）
def _board_of(e) -> int:
    """封板高度：'3天3板'→3、'首板'→1、只有 limit_up 标记→1。"""
    tag = str((e or {}).get("board_tag") or "")
    m = re.search(r"(\d+)\s*板", tag)
    if m:
        return int(m.group(1))
    return 1 if (e or {}).get("limit_up") else 0


def score_themes(rows, stocks, trend) -> list:
    """主线热度分：涨停 30 + 上升广度 25 + 人气 20 + 赚钱效应 15 + 龙头 10。

    和概念总榜同一套权重，好处是两张榜可以横向比：主线的分不是另一套玄学，
    只是把成分从"一个细支"换成"同一条消息的并集"。
    """
    for r in rows:
        allc = [c for c in r["codes"] if c in stocks]
        # 计分只用**核心成员**（主归属在本线，或产业链归到本线）。
        # 理由：东方财富把 "AI应用/AIGC" 这类宽板块挂在几十只票上，
        # 若把关联成员也算进热度，宽主线靠"谁都能挂"就能刷到第一——
        # 那正是用户说的"AI 软件太笼统"。核心不足 3 只时才退回全体并标 core_fallback。
        core = [c for c in (r.get("core_codes") or []) if c in stocks]
        fallback = len(core) < 3
        codes = allc if fallback else core
        heights = [_board_of(stocks.get(c)) for c in codes]
        lu = sum(1 for b in heights if b)
        mb = max(heights or [0]) or 0
        best = min([(stocks[c].get("heat_rank") or 999) for c in codes] or [999])
        # 龙头取「板数最高，其次人气最高」：人气榜第一名会同时挂在十几条主线里，
        # 拿它当每条线的龙头等于五条线写同一个名字，看不出这条线强在哪。
        lead_c = max(codes, key=lambda c: (_board_of(stocks.get(c)),
                                          -(stocks[c].get("heat_rank") or 999)),
                     default=None)
        best_name = (stocks.get(lead_c) or {}).get("name") or "" if lead_c else ""
        heat = sum(1.0 / math.sqrt(max(stocks[c].get("heat_rank") or 999, 1)) for c in codes)
        slopes = [trend[c]["slope"] for c in codes
                  if trend.get(c) and trend[c].get("slope") is not None]
        if slopes:
            up = sum(1 for x in slopes if x > 0.15) / len(slopes)
        else:
            ps = [stocks[c]["pct"] for c in codes if stocks[c].get("pct") is not None]
            up = (sum(1 for p in ps if p > 0) / len(ps)) if ps else 0.0
        pcts = [stocks[c]["pct"] for c in codes if stocks[c].get("pct") is not None]
        avgpct = (sum(pcts) / len(pcts)) if len(pcts) >= CON_MIN_PCT else None

        n = max(len(codes), 1)
        up_adj = (up * n + 0.5 * CON_SEED) / (n + CON_SEED)
        f_lu = (22.0 * min(lu, 10) / 10.0
                + (8.0 if mb >= 3 else 5.0 if mb == 2 else 2.0 if lu else 0.0))
        f_up = CON_W["up"] * up_adj
        f_rise = (CON_W["rise"] * 0.5 if avgpct is None
                  else CON_W["rise"] * max(0.0, min(1.0, (avgpct + 2) / 10.0)))
        f_lead = CON_W["lead"] * max(0.0, (200 - (best if best < 999 else 200)) / 199.0)
        r.update({"n": len(allc), "n_scored": len(codes), "core_fallback": fallback,
                  "n_core": len(core),
                  "lu": lu, "max_board": mb,
                  "best_rank": best if best < 999 else None, "best_name": best_name,
                  "heat": round(heat, 2), "up": round(up, 2), "up_adj": round(up_adj, 3),
                  "avgpct": round(avgpct, 2) if avgpct is not None else None,
                  "n_pct": len(pcts),
                  "sub": {"lu": round(f_lu, 1), "up": round(f_up, 1),
                          "rise": round(f_rise, 1), "lead": round(f_lead, 1)}})
        # 人气项按全榜最大值归一，得等所有行算完
        r["_f_heat"] = heat
        r["_total0"] = f_lu + f_up + f_rise + f_lead

    mx = max([r["_f_heat"] for r in rows] or [1.0]) or 1.0
    for r in rows:
        f_heat = CON_W["heat"] * (r["_f_heat"] / mx)
        r["sub"]["heat"] = round(f_heat, 1)
        r["total"] = round(r["_total0"] + f_heat, 1)
        r.pop("_f_heat", None)
        r.pop("_total0", None)
        # 主线热：分数过半（50/100）。这条线只用于页面标注"今日主线"，
        # 不进个股总分——个股的使用点在双轮共振，两者口径不能混。
        r["hot"] = bool(r["total"] >= THEME_HOT and r["lu"] >= 10)
        r["tier"] = ("强" if r["hot"] else "中" if r["total"] >= 65 else "弱")
    rows.sort(key=lambda x: (-x["total"], -x["n"], x["name"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# ------------------------------------------------------------------ ③ 原因
def reason_pts(code, abnormal, qdate):
    ab = (abnormal or {}).get(code)
    if not ab or not ab.get("reason"):
        return 0, {"note": "无异动记录"}
    if str(ab.get("date")) != str(qdate):
        return 0, {"note": "最近异动 %s，非当日" % ab.get("date")}
    txt = ab["reason"]
    hard = len(set(HARD.findall(txt)))
    soft = len(set(SOFT.findall(txt)))
    pts = 6 if hard == 0 else 10 if hard <= 2 else 14 if hard <= 4 else 18 if hard <= 6 else 20
    if hard == 0 and soft:
        pts = 3
    return pts, {"hard": hard, "soft": soft, "tag": ab.get("tag_name"),
                 "date": ab.get("date")}


# ------------------------------------------------------------------ ④ 资金
def money_pts(e, amt_pool):
    amt = (e.get("tdx") or {}).get("turnover") or 0        # 元
    if not amt_pool or not amt:
        return 0.0, {"note": "无成交额数据"}
    p = bisect.bisect_left(amt_pool, amt) / len(amt_pool)
    pct = e.get("pct") or 0
    b = 6 if pct >= 9.5 else (pct / 9.5) * 5 if pct > 0 else 0
    rate = e.get("turnover")                                # % —— 与上面不是同一字段语义
    c = 2 if (rate and rate >= 15) else 1 if (rate and rate >= 8) else 0
    return round(p * 12 + b + c, 1), {"amt_pct": round(p, 3),
                                      "amt_yi": round(amt / 1e8, 2), "rate": rate}


# ------------------------------------------------------------------ 汇总
def build(data) -> dict:
    """对整份 bundle 算分。返回 {by_code, ranked, tags, meta}。"""
    stocks = data.get("stocks") or {}
    abnormal = data.get("abnormal") or {}
    qdate = data.get("quote_date")

    trend = {c: rank_trend(e) for c, e in stocks.items()}

    # 消息面主线归并：行业/概念之上那一层。把 AI短剧/AI漫剧/AI视频/出版传媒 这些
    # 同一条消息的细支并成一条主线，否则集中度全散在细支里，看不出今天到底在炒什么。
    # 池外涨停股：只有东财涨停池的行情 + 异动解析的关键词，没有热度/分时。
    # 把它们并进主线，主线热度才是"全市场涨停"口径——实测人气池 141 只里
    # 只有 43 只涨停，不并的话 AI 视频这条线会被少算 20 多只涨停。
    zt_extra, zt_stats = {}, {}
    for x in (data.get("zt_pool") or []):
        c = str(x.get("code") or "").zfill(6)
        if not c or c in stocks:
            continue
        kws = ((data.get("abnormal") or {}).get(c) or {}).get("keywords") or []
        zt_extra[c] = {"tags": [str(k) for k in kws if k], "industry": x.get("industry")}
        zt_stats[c] = {"name": x.get("name"), "pct": x.get("pct"), "limit_up": True,
                       "board_tag": ("%d板" % x["board"]) if (x.get("board") or 1) >= 2 else "",
                       "heat_rank": None, "industry": x.get("industry")}
    _abn = data.get("abnormal") or {}
    _kwmap = {c: [str(k) for k in ((_abn.get(c) or {}).get("keywords") or [])
                  if k and not news_mod.is_noise(k)] for c in stocks}
    for c in zt_extra:
        _kwmap[c] = list(zt_extra[c]["tags"])
    th = theme_mod.build(stocks, data.get("f10") or {}, tags_of,
                         (data.get("concept_sector") or {}).get("blocks") or {},
                         extra=zt_extra, kwmap=_kwmap)
    ntags = th.get("ntags") or {}
    tags = build_tags(stocks, trend, ntags)

    raws = {c: concept_raw(e, tags, ntags.get(c))[0] for c, e in stocks.items()}
    pos = sorted(v for v in raws.values() if v > 0)
    p95 = pos[int(len(pos) * 0.95)] if pos else 1.0

    amt_pool = sorted(x for x in ((e.get("tdx") or {}).get("turnover")
                                  for e in stocks.values()) if x)

    by_code = {}
    for c, e in stocks.items():
        tr = trend.get(c)
        t = trend_pts(tr) or proxy_trend(e)
        cp = round(min(raws[c] / p95, 1.0) * 25, 1) if p95 else 0.0
        rp, rd = reason_pts(c, abnormal, qdate)
        mp, md = money_pts(e, amt_pool)
        by_code[c] = {
            "code": c, "name": e.get("name"),
            "total": round(t["pts"] + cp + rp + mp, 1),
            "trend": t, "concept": cp, "reason": rp, "money": mp,
            "trend_detail": tr, "concept_detail": concept_raw(e, tags, ntags.get(c))[1],
            "reason_detail": rd, "money_detail": md,
            "tags": tags_of(e),                 # 原始细支（证据链，页面全列）
            "theme_tags": ntags.get(c) or [],   # 归并后的标签（概念分用的就是它）
            "theme": (th["by_code"].get(c) or {}),
        }

    # 行业维＋双轮共振：加在原四维之后，base100 原样保住（历史可比）。
    sec = sector.build(data, by_code)
    for c, r in by_code.items():
        s = (sec.get("by_code") or {}).get(c) or {}
        r["base100"] = r["total"]
        r["industry"] = s
        r["ind"] = round(float(s.get("pts") or 0.0), 1)
        r["reso"] = round(float(s.get("reso") or 0.0), 1)
        r["drive"] = s.get("drive") or "无"
        r["total"] = round(r["base100"] + r["ind"] + r["reso"], 1)

    # 计分用的统计字典要把池外涨停合进来，否则它们有成员没行情 → KeyError
    trows = score_themes(th.get("rows") or [], {**stocks, **zt_stats}, trend)
    theme_mod.link_tags(trows, tags)
    # 把主线名与热度挂回个股，页面不用再查一次表（行业页驱动列、个股页归因卡都要）
    _nm = {r["id"]: r for r in trows}
    for c, r in by_code.items():
        t = r.get("theme") or {}
        hit = _nm.get(t.get("main")) or {}
        t["main_name"] = hit.get("name")
        t["main_total"] = hit.get("total")
        t["main_rank"] = hit.get("rank")

    # 同分时按趋势分高者优先：两套模型给出一样的总分时，
    # 「名次在冲」比「概念热」更值得排在前面，因为前者有时间窗口。
    ranked = sorted(by_code.values(),
                    key=lambda x: (-x["total"], -x["trend"]["pts"], -x["concept"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    smeta = sec.get("meta") or {}
    return {
        "by_code": by_code,
        "ranked": ranked,
        "tags": tags,
        "sector": sec,
        "theme": {"rows": trows,
                  "main_of": {c: (v.get("main") or "")
                              for c, v in (th.get("by_code") or {}).items()},
                  "meta": {"n": len(trows),
                           "n_hot": sum(1 for r in trows if r.get("hot")),
                           "full": 100.0, "hot_gate": THEME_HOT}},
        "meta": {
            "n": len(by_code),
            "n_with_hist": sum(1 for t in trend.values() if t),
            "n_tags": len(tags),
            "p95_concept_raw": round(p95, 1),
            "n_capped_reason": sum(1 for r in by_code.values() if r["reason"] >= 20),
            "full": 120,
            "base_full": 100,
            "ind_full": smeta.get("full", 14.0),
            "reso_full": smeta.get("reso_full", 6.0),
            "n_double": smeta.get("n_double", 0),
            "n_ind_only": smeta.get("n_ind_only", 0),
            "n_con_only": smeta.get("n_con_only", 0),
            "n_none": smeta.get("n_none", 0),
            "n_missing_ind": smeta.get("n_missing", 0),
            "n_hot_ind": smeta.get("n_hot", 0),
            "n_blocks": smeta.get("n_blocks", 0),
            "n_theme": len(trows),
            "n_theme_hot": sum(1 for r in trows if r.get("hot")),
        },
    }


def one(data, code) -> dict:
    """单只票的评分（给个股页用）。"""
    return build(data)["by_code"].get(str(code).zfill(6)[:6])
