# FFXIV XMA Manager

给 **XIV Mod Archive（XMA）** 用的本地 Mod 管理工具：**爬下来的 Mod 自动解析、自动入库、自动生成 Excel 汇总表**，
配一个**游戏内插件**可以直接装进 Penumbra 并即时生效，再配一个**浏览器拓展**在 Mod 页面上一键「下载并导入」。

一句话理解这三件套的分工：

> **浏览器**负责下载（用你自己已登录的身份 → NSFW 也能下）·**管理器**负责接住并入库（写 地址.txt / 自动编号 / 抓封面 / 打标签 / 生成 Excel）·**插件**负责把 Mod 装进游戏。

---

## 三件套

| 目录 | 是什么 | 技术栈 |
|---|---|---|
| `manager/` | **ModManager**：本地 Web 管理器（列表 / 编辑 / 分类 / 标签 / 查重 / 下载工作台 / Excel 汇总） | Python 3.12（标准库 http.server）+ Vue 3 / Naive UI（Vite 构建） |
| `plugin/` | **ModBridge**：游戏内插件，管理器点「安装到游戏」→ 游戏内确认 → 装进 Penumbra 并即时生效（含预览图绘制） | C# / .NET 10 / Dalamud API 15 / Penumbra.Api |
| `browser-extension/` | **浏览器拓展**：XMA 页面右下角小面板，选分类/子分类/标签 → 加入队列 → 自动下载 + 自动入库 | Chrome MV3（原生 JS，无构建） |

![拓展面板：队列与进度](docs/images/extension-panel.png)

![管理器：下载工作台](docs/images/workbench.png)

---

## 主要功能

**管理器**
- 扫描 Mod 目录 → SQLite 索引 → 一键生成 **Excel 汇总表**（内嵌预览图）
- 列表 / 图片墙两种视图；多选批量改分类、类型、子分类、标签
- 分类 & 子分类管理（目录即分类）；按分类自动分配序号
- 查重、安装检查（标记已装/未装）、检查报告
- 内置浏览器（CDP）抓页面信息：名称 / 作者 / 封面 / 画廊图 / **站点标签** / 下载直链
- 下载工作台：解析链接 → 下载 → 入库 → 抓封面 → 重扫 → 导 Excel，全流程带进度、可取消
- 打包备份 / 导入备份（冲突可跳过 / 覆盖进回收站 / 另存为）
- 与游戏内插件对接（自动配对、安装到游戏、补封面）

**游戏内插件（ModBridge）**
- 管理器点「安装到游戏」→ 游戏内弹确认窗 → 装入 Penumbra 并启用、触发重绘
- 支持 `.pmp` 直装；可选 Heliosphere 规范目录名（`hs-名称-版本-Sqids`）
- 预览图：写入 `cover.webp` / `images\_MetaImage.*`，并能自己用 `PreSettingsTabBarDraw` 绘制封面
- 端口默认 `127.0.0.1:42100`，token 鉴权；`/ping` 返回版本与能力，管理器会**硬拦旧版本插件**

**浏览器拓展**
- 在 Mod 页面右下角读：名称 / 作者 / 封面 / 画廊图 / **站点标签** / 下载直链
- 选 **分类 / 子分类 / 类型 / 标签**（站点标签自动填入，可改）→ **加入队列**
- **队列 + 逐条进度**（下载字节百分比 → 入库进度 → 完成显示入库路径），关页面/后台休眠都不丢
- 工具栏弹窗同样能看队列、移除、重试

---

## 快速开始

### 1) 管理器（必须）
```bash
cd manager
pip install -r requirements.txt      # 其实只用标准库 + Pillow/openpyxl
python mod_manager_web.py            # 或双击「启动Web版.bat」
# 浏览器打开 http://127.0.0.1:8765
```
Windows 也可以直接打包成单文件 exe：
```bash
build_web_exe.bat                    # 先 npm 构建前端，再 PyInstaller 打包
```

### 2) 浏览器拓展（推荐）
1. 打开 `chrome://extensions`（Edge 用 `edge://extensions`）
2. 打开右上角 **开发者模式** → **加载已解压的扩展程序** → 选 `browser-extension/`
3. 在 XMA 的 Mod 页面右下角就会出现小面板

### 3) 游戏内插件（想要「一键装进游戏」才需要）
```bash
# 需要 .NET 10 SDK + Dalamud 开发版引用库
dotnet build -c Release -p:DalamudLibPath=<你的 Dalamud dev 目录>/
```
把编译出的 DLL 放进 `%APPDATA%\XIVLauncherCN\devPlugins\ModBridge\`，重启游戏，
游戏内 `/xlplugins` → Dev Plugins → 启用 **Mod Bridge**。详见 `docs/手动部署-游戏插件.md`。

---

## 游戏插件：用 Dalamud 自定义插件源安装（推荐，可自动更新）

仓库里已经放好 **`pluginmaster.json`**，不用自己编译：

1. 游戏内 `/xlsettings` → **Experimental** → **Custom Plugin Repositories**
2. 把下面任意一个地址粘进去，点 `+` 添加（**国内一般选第二个更稳**）：
   ```
   https://raw.githubusercontent.com/yomo1024/FFXIV_XMA_Manager/main/pluginmaster.json
   https://cdn.jsdelivr.net/gh/yomo1024/FFXIV_XMA_Manager@main/pluginmaster-cdn.json
   ```
3. 保存 → `/xlplugins` → 找到 **Mod Bridge** → 安装 → 启用
4. 以后插件更新会自动出现在更新列表里（管理员点「安装到游戏」时会检查版本，插件太旧会明确拦住）

> 插件包在 `plugin/release/ModBridge-<版本>.zip`；改了插件代码后跑一次
> `python plugin/pack-release.py <编译输出目录> .` 就会重新打 zip 并刷新 pluginmaster.json。

---

## 目录结构

```
manager/                 ModManager 管理器
  mod_manager.py         业务逻辑（扫描/索引/导入/Excel/备份/内置浏览器）
  mod_manager_web.py     本地 Web 服务（REST + 静态资源 + 任务队列）
  web/                   前端构建产物（已提交，clone 后可直接跑）
  web-src/               前端源码（Vue3 + Vite）
  *.bat / make_package.py / ModManagerWeb.spec   打包脚本
plugin/                  ModBridge 游戏内插件
  ModBridge/             插件源码（Plugin / PenumbraBridge / Http / CoverWriter / HelioNaming…）
  tests/                 自测（不需要游戏，覆盖 HTTP 层 / 封面 / 命名等）
  release/               打包好的插件 zip（给 Dalamud 自定义源用）
  pack-release.py        重新打 zip + 生成 pluginmaster.json
  技术方案.md            设计文档（含 Penumbra 与 Heliosphere 预览图机制的逆向结论）
  参考资料/              Penumbra 反编译参考
browser-extension/       浏览器拓展（MV3）
docs/                    使用说明 / 手动部署插件 / 拓展安装说明
```

---

## 工作原理（为什么"用你自己的浏览器"下载）

XMA 的下载需要登录，而且 **NSFW 的 Mod 未登录根本看不到文件**；同时浏览器有硬性安全限制——
没有开启调试端口的浏览器实例，任何程序都读不了它的页面。所以本项目不试图"偷看"你的浏览器，而是：

1. **拓展**（或书签小工具）在**你自己的浏览器**里读页面信息，交给本地管理器（`127.0.0.1:8765`）；
2. 由**你自己的浏览器**带着登录态下载文件；
3. 管理器在文件落地的**确切路径**上接住它 → 入库 → 打标签 → 重扫 → 导 Excel。

管理器本身还内置一个可选的 Chromium 实例（独立配置目录 + CDP），用于「解析链接」等自动化场景；
它不登录也能用，但 NSFW 场景请用拓展那条路。

全部通信只发生在 `127.0.0.1`，不上传任何数据。

---

## 版本

| 组件 | 版本 |
|---|---|
| 管理器 ModManager | v2.2 |
| 游戏插件 ModBridge | v0.2.7（管理器要求 ≥ v0.2.6） |
| 浏览器拓展 | v1.0.0 |

---

## 常见问题

见 `docs/使用说明.md`（含：拓展连不上管理器、NSFW 看不到下载链接、预览图不显示、插件没生效…）。

## 说明

- 这是**个人自用**的工具，非 Square Enix / XIV Mod Archive 官方项目；使用前请阅读对应站点的规则。
- 仓库未附带 License；如需转载/复用请先联系作者。
- 仓库内不包含任何 Mod 文件本身，也不包含账号 / token / 本地配置。
