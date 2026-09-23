# -*- coding: utf-8 -*-
"""前端导入自检：**这个坑会让整个页面白掉，而 vite build 依然是绿的**。

每个 .vue 是各自按需 import 的（没有全局注册），所以：
  · 模板里写了 <n-tabs> 但没 import NTabs → 页签完全不渲染
  · script 里写了 computed(...) 但只 import 了 ref → setup 抛错 → **整页白**
两者 build 都不报错。改完 .vue 一定要跑这个脚本。
"""
import os
import re
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "manager", "web-src", "src")
# 编译器宏，不需要 import
MACROS = {"defineEmits", "defineProps", "defineExpose", "defineOptions", "defineSlots",
          "withDefaults", "defineModel"}
VUE_API = ["ref", "computed", "watch", "watchEffect", "reactive", "onMounted", "onUnmounted",
           "onBeforeUnmount", "nextTick", "h", "inject", "provide", "toRefs", "toRef", "markRaw"]


def camel(tag: str) -> str:
    return "N" + "".join(p.capitalize() for p in tag[2:].split("-"))


def check(root=SRC):
    bad = []
    for dp, dn, fn in os.walk(root):
        if "node_modules" in dp:
            continue
        for f in fn:
            if not f.endswith(".vue"):
                continue
            p = os.path.join(dp, f)
            t = open(p, encoding="utf-8", errors="replace").read()
            i, j = t.find("<script setup>"), t.find("</script>")
            sc = t[i:j] if i >= 0 and j > i else ""
            have_ui = set()
            m = re.search(r"import\s*\{([^}]*)\}\s*from\s*'naive-ui'", sc, re.S)
            if m:
                have_ui = {x.strip() for x in m.group(1).split(",") if x.strip()}
            miss_ui = sorted({u for u in re.findall(r"<(n-[a-z-]+)", t) if camel(u) not in have_ui})
            vue_import = ""
            mv = re.search(r"import\s*\{([^}]*)\}\s*from\s*'vue'", sc, re.S)
            if mv:
                vue_import = mv.group(1)
            body = re.sub(r"^\s*import[^\n]*\n", "", sc, flags=re.M)
            miss_api = sorted({a for a in VUE_API
                               if a not in MACROS and re.search(r"(?<![\w.])" + a + r"\s*\(", body)
                               and not re.search(r"\b" + a + r"\b", vue_import)})
            if miss_ui or miss_api:
                bad.append((os.path.relpath(p, root), miss_ui, miss_api))
    return bad


if __name__ == "__main__":
    if not os.path.isdir(SRC):
        print("✗ 找不到前端源码目录：%s（脚本路径写错了？）" % SRC)
        sys.exit(2)                     # 绝不能静默通过 —— 曾经因为路径写错扫了空目录、假报「全部干净」
    bad = check()
    for rel, ui, api in bad:
        print("✗ %s  缺组件=%s  缺 vue API=%s" % (rel, ui or "-", api or "-"))
    print("全部干净 ✓" if not bad else "有 %d 个文件有问题 ✗" % len(bad))
    sys.exit(1 if bad else 0)
