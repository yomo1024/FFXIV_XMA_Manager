# -*- coding: utf-8 -*-
"""版本号的唯一来源。

管理器（tkinter 版 mod_manager.py / Web 版 mod_manager_web.py）、部署包
（make_package.py）、界面显示都从这里读，免得几处各写一份、时间久了互相对不上。
以后改版本号，只改这一个文件。
"""

APP_VERSION = "2.2"            # 管理器版本：界面/接口有改动就 +1
MIN_PLUGIN_VERSION = "0.2.6"   # 游戏内插件最低要求版本（低于它就没有封面/目录命名这些新功能）
