#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
接口契约检查：**后端改了字段/路由，前端(网页)、浏览器拓展有没有被改坏。**
=====================================================================
为什么需要它：
    v2.18.0 改分类接口时把 `disk_subcats` 删掉了，而 `browser-extension/content.js`
    和 `ModsView.vue` 都在读这个字段 —— 静态检查没人跑，就一直没发现。
    这个脚本把「消费者用到的 /api 路径」和「后端真实注册的路由」对起来，
    再把几个关键响应的字段名核对一遍，任何一边对不上就 exit 1。

检查范围：
    1. 路由：browser-extension/*.js、manager/web-src/src/api.js 里出现的 /api 路径
       必须能在后端 do_GET / do_POST 里找到（区分 GET / POST）
    2. 字段：下面 FIELDS 里列的关键响应字段必须在后端源码里出现
       （字段被删/改名 → 这里会红）

用法：python scripts/check_api_contract.py           只看结果
      python scripts/check_api_contract.py -v        打印全部命中明细
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKEND = os.path.join(ROOT, "manager", "mod_manager_web.py")
CONSUMERS = [
    (os.path.join(ROOT, "browser-extension"), (".js",)),
    (os.path.join(ROOT, "manager", "web-src", "src"), (".js", ".vue")),
]
# 关键响应字段：删掉/改名就会打到消费者
FIELDS = {
    "/api/categories": ["cats", "name", "subcats", "disk_subcats", "count", "on_disk"],
    "/api/state": ["root", "total"],
    "/api/job": ["state", "kind", "pct", "text"],
    "/api/backups": ["items", "snaps", "stats"],
    "/api/mods": ["mods"],
}
VERBOSE = "-v" in sys.argv


def read(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "replace").replace("\r\n", "\n")


def backend_routes():
    """从 do_GET / do_POST 里抠出所有 /api 路径 → {"GET": {...}, "POST": {...}}"""
    src = read(BACKEND)
    lines = src.split("\n")
    out = {"GET": set(), "POST": set()}
    cur = None
    for ln in lines:
        m = re.match(r"^    def (do_GET|do_POST)\b", ln)
        if m:
            cur = m.group(1).split("_")[1]
            continue
        if re.match(r"^    def ", ln) or re.match(r"^class ", ln):
            cur = None
        if cur is None:
            continue
        for p in re.findall(r'"(/api/[A-Za-z0-9_/\-]*)"', ln):
            out[cur].add(p)
    return out


def consumer_calls():
    """找消费者调用的 /api 路径 → [(来源, 路径, 动词)]"""
    found = []
    for base, exts in CONSUMERS:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", "dist", "build")]
            for fn in filenames:
                if not fn.endswith(exts):
                    continue
                p = os.path.join(dirpath, fn)
                rel = os.path.relpath(p, ROOT)
                lines = read(p).split("\n")
                joined = "\n".join(lines)
                for i, ln in enumerate(lines):
                    for m in re.finditer(r"['\"](/api/[A-Za-z0-9_/\-]*)", ln):
                        path = m.group(1)
                        # 动词判定：① 前面的调用名（jpost/post 等）② 同一次调用里的 method:'POST'
                        # 窗口到「下一个 /api 出现」为止，避免窜到下一行调用上去
                        at = len("\n".join(lines[:i])) + m.start() + (1 if i else 0)
                        before = joined[max(0, at - 60):at]
                        tail = joined[at:at + 400]
                        nxt = re.search(r"['\"]/api/", tail[1:])
                        seg = tail[:nxt.start() + 1] if nxt else tail
                        verb = "GET"
                        if re.search(r"\b(jpost|postJSON|post)\s*\(\s*$", before) or \
                           re.search(r"method:\s*['\"]POST", seg):
                            verb = "POST"
                        found.append((rel, i + 1, path, verb))
    return found


def main():
    routes = backend_routes()
    if not routes["GET"] and not routes["POST"]:
        print("!! 一个后端路由都没解析出来：%s 结构可能变了" % BACKEND)
        return 2
    calls = consumer_calls()
    problems = []

    for rel, line, path, verb in calls:
        if path in routes[verb]:
            if VERBOSE:
                print("  ok   %-38s %-4s %s:%d" % (path, verb, rel, line))
            continue
        other = "POST" if verb == "GET" else "GET"
        if path in routes[other]:
            problems.append("%s:%d 用 %s 调 %s，但后端只注册在 %s"
                            % (rel, line, verb, path, other))
        else:
            problems.append("%s:%d 调用 %s，后端根本没有这个路由" % (rel, line, path))

    src = read(BACKEND)
    for path, keys in FIELDS.items():
        for k in keys:
            if not re.search(r"['\"]%s['\"]" % re.escape(k), src):
                problems.append("后端源码里找不到 %s 的字段 %r（消费者在读它）" % (path, k))

    if problems:
        print("接口契约有问题：")
        for p in problems:
            print("  ✗", p)
        return 1
    print("接口契约一致 ✓  路由 %d 个消费者调用点 / %d 个关键字段都对得上"
          % (len(calls), sum(len(v) for v in FIELDS.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
