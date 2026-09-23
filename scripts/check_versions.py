#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版本一致性校验 + 一键递增（把「版本落点」全仓库对一遍）。

用法（在仓库根目录执行）：
    python scripts/check_versions.py                     # 只校验，全一致退出码 0
    python scripts/check_versions.py --bump patch        # 管理器 Z+1，并同步所有落点
    python scripts/check_versions.py --bump-plugin patch # 插件 Z+1（改 csproj + README + 使用说明）

版本规则 vX.Y.Z
    X  不兼容的大改（数据格式/目录结构变、旧配置不再适用）
    Y  功能新增（新页面、新接口、新能力）
    Z  修复 / 优化 / 文案（不改行为的小修）

唯一来源 → 派生处
    管理器   manager/app_version.py : APP_VERSION
             ↳ manager/mod_manager_web.py 的 MANAGER_VERSION / MIN_PLUGIN_VERSION
             ↳ manager/make_package.py 的 VERSION（部署包名）
             ↳ manager/web-src/package.json 与 package-lock.json
             ↳ README.md、docs/使用说明.md 的版本表
    插件     plugin/ModBridge/ModBridge.csproj : <Version>
             ↳ Dalamud 清单与 pluginmaster*.json 的 AssemblyVersion（SDK 自动补 .0，勿手改）
             ↳ plugin/release/ModBridge-<x.y.z>.zip（pack-release.py 生成）
    拓展     browser-extension/manifest.json : "version"

只带了管理器源码的目录（比如部署目录）里跑也安全：缺的部分会跳过、不算失败。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MP = "manager/" if (ROOT / "manager").is_dir() else ""      # 部署目录里源码直接摆在根下
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
ok_list, fail_list, skip_list = [], [], []


def check(name, got, expect, note=""):
    (ok_list if got == expect else fail_list).append((name, got, expect, note))


def skip(name, why):
    skip_list.append((name, why))


def rd(rel):
    p = ROOT / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None


def grab(rel, pattern):
    t = rd(rel)
    if t is None:
        return None
    m = re.search(pattern, t, re.M)
    return m.group(1).strip() if m else ""


def check_text(rel, pattern, expect, name, note=""):
    """文件在就比对，文件不在就跳过（部署目录里没有 README 之类）。"""
    if rd(rel) is None:
        skip(name, "没有 %s" % rel)
        return
    check(name, grab(rel, pattern), expect, note)


def check_in(rel, needle, name, note=""):
    if rd(rel) is None:
        skip(name, "没有 %s" % rel)
        return
    check(name, needle in (rd(rel) or ""), True, note)


def bump(v, part):
    a = [int(x) for x in v.split(".")]
    if part == "major":
        a = [a[0] + 1, 0, 0]
    elif part == "minor":
        a = [a[0], a[1] + 1, 0]
    elif part == "patch":
        a = [a[0], a[1], a[2] + 1]
    else:
        sys.exit("只接受 major / minor / patch，收到：%r" % part)
    return ".".join(str(x) for x in a)


def rewrite(rel, pairs, times=1):
    """old→new；times=None 表示替换全部（锁文件里根版本本来就有两处）。"""
    p2 = ROOT / rel
    body = p2.read_bytes().decode("utf-8")
    for old, new in pairs:
        n = body.count(old)
        assert (n >= 1) if times is None else (n == times), \
            "[%s] 期望匹配 %s 次，实际 %d 次：%r" % (rel, times, n, old[:70])
        body = body.replace(old, new)
    p2.write_bytes(body.encode("utf-8"))


def do_bump(part):
    old = grab(MP + "app_version.py", r'^APP_VERSION\s*=\s*"([^"]+)"')
    new = bump(old, part)
    rewrite(MP + "app_version.py", [('APP_VERSION = "%s"' % old, 'APP_VERSION = "%s"' % new)])
    rewrite(MP + "web-src/package.json", [('"version": "%s"' % old, '"version": "%s"' % new)])
    rewrite(MP + "web-src/package-lock.json", [('"version": "%s"' % old, '"version": "%s"' % new)], times=2)
    if rd("README.md"):
        rewrite("README.md", [("| 管理器 ModManager | v%s |" % old, "| 管理器 ModManager | v%s |" % new)])
    if rd("docs/使用说明.md"):
        rewrite("docs/使用说明.md", [("管理器 ModManager **v%s**" % old, "管理器 ModManager **v%s**" % new),
                                     ("侧栏页脚 `v%s" % old, "侧栏页脚 `v%s" % new)])
    print("管理器版本：%s → %s（已同步 app_version.py / package.json / package-lock.json / README / 使用说明）\n" % (old, new))


def do_bump_plugin(part):
    old = grab("plugin/ModBridge/ModBridge.csproj", r"<Version>([^<]+)</Version>")
    if old is None:
        sys.exit("找不到 plugin/ModBridge/ModBridge.csproj")
    new = bump(old, part)
    rewrite("plugin/ModBridge/ModBridge.csproj", [("<Version>%s</Version>" % old, "<Version>%s</Version>" % new)])
    if rd("README.md"):
        rewrite("README.md", [("| 游戏插件 ModBridge | v%s" % old, "| 游戏插件 ModBridge | v%s" % new)])
    if rd("docs/使用说明.md"):
        rewrite("docs/使用说明.md", [("游戏插件 ModBridge **v%s**" % old, "游戏插件 ModBridge **v%s**" % new)])
    print("插件版本：%s → %s（已同步 csproj / README / 使用说明）" % (old, new))
    print("  还差两步：dotnet build -c Release  →  python plugin/pack-release.py <bin/Release> .\n")


# ---------------- 可选参数 ----------------
args = sys.argv[1:]
for flag, fn in (("--bump", do_bump), ("--bump-plugin", do_bump_plugin)):
    if flag in args:
        i = args.index(flag)
        fn(args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("-") else "patch")

# ---------------- 唯一来源 ----------------
mgr = grab(MP + "app_version.py", r'^APP_VERSION\s*=\s*"([^"]+)"') or ""
minp = grab(MP + "app_version.py", r'^MIN_PLUGIN_VERSION\s*=\s*"([^"]+)"') or ""
plug = grab("plugin/ModBridge/ModBridge.csproj", r"<Version>([^<]+)</Version>")
ext = None
try:
    t = rd("browser-extension/manifest.json")
    ext = json.loads(t).get("version", "") if t else None
except Exception:
    ext = ""

print("唯一来源   管理器 %s ｜ 插件 %s ｜ 拓展 %s ｜ 插件最低要求 %s"
      % (mgr, plug or "（本目录没有）", ext or "（本目录没有）", minp))
print("-" * 92)

for label, v in [("管理器版本格式", mgr), ("插件最低要求格式", minp)]:
    check(label, "x.y.z" if SEMVER.match(v) else "%s ← 不是三段式" % v, "x.y.z")
if plug is None:
    skip("插件版本格式", "没有 plugin/ModBridge/ModBridge.csproj")
elif not SEMVER.match(plug):
    fail_list.append(("插件版本格式", "%s ← 不是三段式" % plug, "x.y.z", ""))
else:
    ok_list.append(("插件版本格式", "x.y.z", "x.y.z", ""))
if ext is None:
    skip("拓展版本格式", "没有 browser-extension/manifest.json")
elif not SEMVER.match(ext or ""):
    fail_list.append(("拓展版本格式", "%s ← 不是三段式" % ext, "x.y.z", ""))
else:
    ok_list.append(("拓展版本格式", "x.y.z", "x.y.z", ""))

# ---------------- 管理器派生处 ----------------
check_in(MP + "mod_manager_web.py", "MANAGER_VERSION = app_version.APP_VERSION", "mod_manager_web 取来源", "不能写死版本号")
check_in(MP + "mod_manager_web.py", "MIN_PLUGIN_VERSION = app_version.MIN_PLUGIN_VERSION", "mod_manager_web 最低要求")
check_in(MP + "make_package.py", "VERSION = APP_VERSION", "make_package 取来源", "部署包名/部署说明")
check("web-src/package.json", grab(MP + "web-src/package.json", r'"version":\s*"([^"]+)"'), mgr)
lock = rd(MP + "web-src/package-lock.json") or ""
check("package-lock.json 两处根版本", lock.count('"version": "%s"' % mgr), 2)
check_text("README.md", r"\| 管理器 ModManager \| v?([0-9.]+) \|", mgr, "README 版本表（管理器）")
check_text("docs/使用说明.md", r"管理器 ModManager \*\*v?([0-9.]+)\*\*", mgr, "使用说明（管理器）")
check_text("docs/使用说明.md", r"侧栏页脚 `v?([0-9.]+)", mgr, "使用说明页脚示例")

# ---------------- 插件派生处 ----------------
if plug is None:
    skip("插件派生处全部检查", "本目录没有 plugin/")
else:
    check_text("README.md", r"\| 游戏插件 ModBridge \| v?([0-9.]+)", plug, "README 版本表（插件）")
    check_text("docs/使用说明.md", r"游戏插件 ModBridge \*\*v?([0-9.]+)\*\*", plug, "使用说明（插件）")
    check_in("plugin/ModBridge/Plugin.cs", "Version?.ToString(3)", "Plugin.cs 只报三段", "/ping 的 version 字段")
    for rel in ["pluginmaster.json", "pluginmaster-cdn.json"]:
        if rd(rel) is None:
            skip("%s 检查" % rel, "文件不存在")
            continue
        try:
            e = json.loads(rd(rel))[0]
        except Exception:
            fail_list.append((rel, "读不出来", "", ""))
            continue
        check("%s AssemblyVersion" % rel, e.get("AssemblyVersion"), plug + ".0", "SDK 自动补 .0，别手改")
        check("%s 下载链接" % rel, str(e.get("DownloadLinkInstall", "")).rsplit("/", 1)[-1], "ModBridge-%s.zip" % plug)
    check("插件发布包存在", (ROOT / ("plugin/release/ModBridge-%s.zip" % plug)).is_file(), True,
          "改完插件跑 plugin/pack-release.py")
    check("插件最低要求 ≤ 当前插件",
          tuple(int(x) for x in re.findall(r"\d+", minp)) <= tuple(int(x) for x in re.findall(r"\d+", plug)), True)

# ---------------- 拓展（独立判断，插件段跳过了它也照查） ----------------
if ext is None:
    skip("拓展检查", "没有 browser-extension/manifest.json")
else:
    for rel in ["docs/浏览器拓展-安装说明.md", "browser-extension/安装说明.md"]:
        check_in(rel, "管理器助手 %s" % ext, "%s 版本提及" % rel)

# ---------------- 输出 ----------------
for name, got, expect, note in ok_list:
    print("  OK   %-32s %s" % (name, got))
for name, why in skip_list:
    print("  --   %-32s 跳过（%s）" % (name, why))
if fail_list:
    print()
    for name, got, expect, note in fail_list:
        print("  ✗    %-32s 实际=%-16s 期望=%-14s %s" % (name, got, expect, note))
    print("\n不一致 %d 处（上面 ✗），修完再跑一次" % len(fail_list))
    sys.exit(1)
print("\n全部一致 ✔   管理器 v%s%s%s" % (mgr, " ｜ 插件 v%s" % plug if plug else "", " ｜ 拓展 v%s" % ext if ext else ""))
