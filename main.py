# -*- coding: utf-8 -*-
"""云端托管入口。

平台的默认启动方式是 `python main.py`（本项目原先把逻辑全放在 serve.py，导致
发布时报 `/workspace/main.py: No such file or directory`）。这里只做一件事：
把托管环境注入的 PORT 交给 serve，并强制绑 0.0.0.0（平台要求对外可达）。

本地照旧跑 `python serve.py 127.0.0.1 888`，两者共用同一套渲染与刷新线程。
"""
from __future__ import annotations

import os

import serve

if __name__ == "__main__":
    os.environ.setdefault("HOST", "0.0.0.0")
    serve.main()
