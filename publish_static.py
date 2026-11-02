# -*- coding: utf-8 -*-
"""把 dist/ 推成 gh-pages 分支——GitHub Pages 那份"数据冻住"的解法。

为什么需要它：serve.py 有进程内 daemon 定时刷新，但 GitHub Pages 只是静态托管，
没有后端也没有 cron，构建一次就永远停在那一刻。本脚本做三件事：
  1. 跑 build_static.py 重新静态化（读 data/live 最新数据）
  2. 用独立 index 把 dist/ 整棵树写进 git 对象库（不碰主工作区、不建临时克隆）
  3. 以 origin/gh-pages 为父提交，直接 push 一个 commit 到 gh-pages

为什么不用 worktree / 临时 clone：本机 shutil.rmtree 与 rm -rf 会被 WorkBuddy shim
拦（fail-closed 进回收站），清目录那步容易炸；write-tree 方案根本不需要删东西，
且天然处理"删文件"（git add -A 会记录删除）。

用法：
    python publish_static.py            # 构建 + 推送
    python publish_static.py --no-build # 只推送现有 dist
    python publish_static.py --dry-run  # 只构建并报告会推什么
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
BRANCH = "gh-pages"
# 本机直连 GitHub 常被 9928 代理挡（CONNECT 502），7890 是 mihomo 的可用口。
# 顺序上先走 7890：直连失败要等 21s 超时才换，白等一轮。
PROXY_FALLBACK = "http://127.0.0.1:7890"


def _env(extra=None):
    e = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        e.pop(k, None)
    e["GIT_TERMINAL_PROMPT"] = "0"   # 后台线程里绝不能停在凭据提示上
    if extra:
        e.update(extra)
    return e


def _via():
    """(标签, env) 序列：先代理，再直连兜底。"""
    return (("代理 7890", _env({"http_proxy": PROXY_FALLBACK, "https_proxy": PROXY_FALLBACK})),
            ("直连", _env()))


def git(args, cwd=ROOT, env=None, check=True):
    return subprocess.run(["git"] + args, cwd=cwd, env=env or _env(),
                          capture_output=True, text=True, check=check)


def run(cmd, **kw):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)
    tail = (r.stdout or "").strip().splitlines()[-3:]
    print("  $ %s  exit=%s  %s" % (" ".join(cmd[1:]) or cmd[0], r.returncode, " | ".join(tail)))
    return r


def build() -> bool:
    print("[1/4] 静态化 dist/")
    r = run([sys.executable, "build_static.py"])
    if r.returncode != 0:
        print((r.stderr or "")[-800:])
        return False
    n = sum(1 for _, _, fs in os.walk(DIST) for f in fs if f.endswith(".html"))
    print("     产出 %d 个 html" % n)
    return True


def fetch_branch() -> str | None:
    """取远端 gh-pages 头；直连失败时换 7890 代理重试一次。"""
    for label, env in _via():
        r = git(["fetch", "origin", BRANCH, "-q"], env=env, check=False)
        if r.returncode == 0:
            print("[2/4] 取远端 %s（%s）" % (BRANCH, label))
            return git(["rev-parse", "FETCH_HEAD"]).stdout.strip()
        print("     取 %s 失败（%s）：%s" % (BRANCH, label, (r.stderr or "").strip()[:120]))
    return None


def make_tree(idx: str) -> str:
    env = _env({"GIT_INDEX_FILE": idx, "GIT_WORK_TREE": DIST})
    git(["add", "-A", "-f", "."], env=env)
    return git(["write-tree"], env=env).stdout.strip()


def main(argv: list[str]) -> int:
    if "--no-build" not in argv and not build():
        return 1
    if not os.path.isdir(DIST):
        print("dist/ 不存在，先跑 build_static.py")
        return 1

    parent = fetch_branch()
    if parent is None:
        print("[!] 拿不到远端分支，改用本地已有 %s 作父（首次发布可忽略）" % BRANCH)
        r = git(["rev-parse", BRANCH], check=False)
        parent = r.stdout.strip() if r.returncode == 0 else ""

    fd, idx = tempfile.mkstemp(suffix=".idx")
    os.close(fd)
    os.unlink(idx)
    try:
        tree = make_tree(idx)
    finally:
        if os.path.exists(idx):
            os.unlink(idx)

    if parent:
        ptree = git(["rev-parse", parent + "^{tree}"]).stdout.strip()
        if ptree == tree:
            print("[3/4] dist 与远端 %s 完全一致，无需推送" % BRANCH)
            print("[4/4] 跳过 push")
            return 0

    if "--dry-run" in argv:
        print("[3/4] dry-run：tree=%s parent=%s，不提交" % (tree[:10], (parent or "无")[:10]))
        return 0

    msg = "static build %s" % __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")
    cmd = ["commit-tree", tree, "-m", msg] + (["-p", parent] if parent else [])
    commit = git(cmd).stdout.strip()
    print("[3/4] commit %s  (%s)" % (commit[:10], msg))

    for label, env in _via():
        r = git(["push", "origin", "%s:refs/heads/%s" % (commit, BRANCH), "-q"],
                env=env, check=False)
        if r.returncode == 0:
            print("[4/4] 已推送 gh-pages（%s）" % label)
            return 0
        print("     push 失败（%s）：%s" % (label, (r.stderr or "").strip()[:160]))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
