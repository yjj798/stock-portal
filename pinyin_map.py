# -*- coding: utf-8 -*-
"""汉字 → 无声调拼音，供"谐音梗"概念做名称同音扩展。

为什么需要它：概念名带「字辈」的（“羊”字辈这类）本质是**读音梗**，不是字面梗。
名字里写「羊」的只有一只，但读 yang 的一大把——泉阳泉、太平洋、扬子新材、沈阳机床、
九阳股份、阳光电源、东方海洋……按字面匹配只能认出三只，这正是用户当场指出的错。

为什么不装 pypinyin：本机与云端沙箱 PyPI 都不可达；官方字典 pinyin-data 的
pinyin.txt 是纯文本（985KB，41k 行），解析一次 ~60ms，比装包稳。

口径限制（写进页面，别让读者以为万能）：
  · 多音字取**全部**读音参与匹配（长 cháng/zhǎng 都算），宁可宽一点
  · 不做声调区分：yang / yáng / yǎng 一律算同音
  · 只对名称做匹配，不看主营业务——这是名字梗，不是基本面归类
"""
from __future__ import annotations

import os
import unicodedata

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "data", "pinyin", "pinyin.txt")
_cache: dict[str, tuple] = {}
_loaded = False


def _toneless(py: str) -> str:
    s = unicodedata.normalize("NFD", py)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("ü", "v").replace("u:", "v").lower().strip()


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    if not os.path.exists(_SRC):
        return
    with open(_SRC, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            head, _, _tail = line.partition("#")
            code, _, pys = head.partition(":")
            try:
                ch = chr(int(code.strip().replace("U+", ""), 16))
            except ValueError:
                continue
            got = tuple(_toneless(p) for p in pys.split(",") if p.strip())
            if got:
                _cache[ch] = got


def readings(ch: str) -> tuple:
    """某字的全部无声调读音；查不到返回空元组。"""
    _load()
    return _cache.get(ch, ())


def sound_of(text: str) -> list:
    """一个词每个字的首读音，如 羊字辈 → ['yang', 'zi', 'bei']。"""
    return [readings(c)[0] if readings(c) else "" for c in str(text or "")]


def sounds(text: str) -> set:
    """一个词所有字的全部读音集合（多音字全收）。"""
    out = set()
    for c in str(text or ""):
        out |= set(readings(c))
    return out


def same_sound(name: str, target: str) -> bool:
    """name 里有没有**任何一个字**的某个读音等于 target。"""
    if not name or not target:
        return False
    return any(target in readings(c) for c in name)


def chars_with_sound(target: str) -> list:
    """反查：读 target 音的字（调试与页面说明用，会扫全表）。"""
    _load()
    return sorted(c for c, ps in _cache.items() if target in ps)
