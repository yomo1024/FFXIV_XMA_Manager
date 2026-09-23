# -*- coding: utf-8 -*-
"""版本号的唯一来源（管理器 / 部署包 / 界面显示都读这里）。

版本规则  vX.Y.Z
    X  不兼容的大改（数据格式/目录结构变、旧配置不再适用）
    Y  功能新增（新页面、新接口、新能力）
    Z  修复 / 优化 / 文案（不改行为的小修）
    只要发出去给别人用，就必须动这个文件；改完跑 `python scripts/check_versions.py` 验一遍。

其它组件的版本不在这里：
    游戏插件 ModBridge  在 plugin/ModBridge/ModBridge.csproj 的 <Version>（同规则三段式）
    浏览器拓展          在 browser-extension/manifest.json 的 "version"
"""

APP_VERSION = "2.23.5"          # 管理器版本（tkinter 版 / Web 版共用）
MIN_PLUGIN_VERSION = "0.2.6"   # 游戏内插件最低要求版本（低于它就没有封面/目录命名这些新功能）
