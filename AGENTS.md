# AGENTS.md —— 给编码代理的项目说明书

> 本文件由 dsh / 其他编码代理在会话开始自动加载（项目根 = 含 `.git` 的目录）。
> 目标：让代理**不必摸索就能按本项目的既有规范改动、验证、发版**。
> 规则优先级：本文件 > 你的习惯。与主人（yomo1024）的当场指令冲突时，以当场指令为准。

## 当前状态（新会话先读这段）

> 最后更新：2026-09-28（本节的「最近完成」按 git log 维护；「待办」由主人补充）

| 组件 | 当前版本 | 唯一来源 |
|---|---|---|
| 管理器 ModManager | **v2.33.4**（最新 tag = v2.33.2，v2.33.3/v2.33.4 属小改未打 tag） | `manager/app_version.py` |
| 游戏插件 ModBridge | v0.2.13 | `plugin/ModBridge/ModBridge.csproj` |
| 浏览器拓展 | 见文件 | `browser-extension/manifest.json` |

### 最近完成（倒序，来自 git log）

- **v2.33.4** 索引：改名/移动/重排序号时索引与云端目录一起跟着走；新增「索引体检 / 修复」（待办页）——`rename_mod` 不再留下重复行，扫描也会自动并入或清掉历史残留
- **v2.33.3** UI：任务条/下载条里会变的文字预留空间，不再挤压邻居
- **v2.33.2** UI：界面文案里的 markdown 现在会真的渲染
- **v2.33.1** UI：云端索引预览改成单开弹窗列出「要改什么」，并能直接确认写入
- **v2.33.0** 云盘：索引/元数据同步改为**增量**，新增「从云端索引恢复」
- **v2.32.1** 删除：本地没有文件夹的 Mod 删不掉 + 扫描会吃掉云端归档条目（均已修）
- **v2.32.0** 云盘：索引/元数据也存到网盘（本地同留一份）+ 云盘体检真下载
- **v2.31.0** 汇总表不参与索引 / 网盘发现+冲突选边 / 压缩包载荷也能装
- **v2.30.0** 登录态同步引导化：先体检再同步，被占用时给「关闭它并同步」
- **v2.29.0** 导入后自动装进游戏：入库完直接推给游戏内插件
- **v2.28.0** 待办聚合页：把散在各页的待处理事项收成一页
- **v2.27.0** 导入后自动归档：去掉最后一个人工步骤

### 待办 / 正在做

- 暂无（新会话接手时若主人没特别交代，先从「硬规则」与「高频坑」两节熟悉约束，再动手）
- 可选小尾巴：`202609\衣服` 里还留着几张历史同级预览图（`3.Trigun.jpg` 等，文件夹已改名或被删），只是视觉垃圾、不影响取图；云端也留着那 4 个已删 Mod 的目录（主人要求当备份）

### 接手姿势（给新会话）

读本节 + 第 3 节构建链 + 第 5 节自检即可开工；**不需要通读源码**（约 2.6 万行）。需要历史决策依据时用 `session_search` 检索旧会话，或直接 `git log`。

## 1. 项目是什么

FFXIV Mod 管理器「三件套」，服务于 XIVModArchive / Heliosphere 两个 Mod 站：

| 组件 | 位置 | 技术栈 |
|---|---|---|
| 管理器（桌面/Web） | `manager/` | Python 3.12 标准库 `http.server` + `sqlite3`；前端 Vue3 + Naive UI（Vite） |
| 游戏内插件 | `plugin/ModBridge/` | C#/.NET 10、Dalamud API 15，监听 127.0.0.1:42100，对接 Penumbra IPC |
| 浏览器拓展 | `browser-extension/` | Chrome MV3，无构建（content.js / sw.js / popup） |

- 业务逻辑：`manager/mod_manager.py`；REST 服务：`manager/mod_manager_web.py`（50+ `/api` 路由）
- 前端源码：`manager/web-src/`（Vite 构建 → 输出到 **已提交** 的 `manager/web/`）
- 版本号唯一来源：`manager/app_version.py`（`APP_VERSION` / `MIN_PLUGIN_VERSION`）

## 2. 本机环境（绝对路径，别猜）

| 用途 | 路径 |
|---|---|
| 仓库（开发主目录，权威） | `E:\Hermes\FFXIV_XMA_Manager` |
| 线上运行副本（**只在交付时覆盖程序文件**） | `G:\Games\FFXIV\Soft` |
| 真实 Mod 库 | `G:\Games\FFXIV\MOD\202609` |
| .NET 10 SDK（**不在 PATH**） | `C:\Users\qwe26\AppData\Local\Microsoft\dotnet\dotnet.exe` |
| Dalamud 引用库（编译插件必需） | `E:\Hermes\dalamud-dev` → 环境变量 `DALAMUD_HOME` |
| Node 22 / npm | `C:\Users\qwe26\.hermes-web-ui\desktop-runtime\hermes\0.21.3\win-x64\node` |
| Python 3.12（含 PyInstaller 6.22.3 + tkinter） | `C:\Users\qwe26\AppData\Local\Programs\Python\Python312\python.exe` |

- **git remote 必须走 SSH**（`git@github.com:yomo1024/FFXIV_XMA_Manager.git`）；HTTPS 到 github.com 在本机不通。
- 偶发 `ssh: Could not resolve hostname github.com`（代理抖动）→ 直接重试，不要改 remote。
- 网络请求用 Python `requests`/`urllib`；本机 `curl` 常失败（rc=255）。

## 3. 三条构建链（均已实测）

### 3.1 插件（C#）
```powershell
$env:DALAMUD_HOME = "E:\Hermes\dalamud-dev"
$env:PATH = "C:\Users\qwe26\AppData\Local\Microsoft\dotnet;" + $env:PATH
dotnet build -c Release            # 工作目录: plugin\ModBridge（必须指到含 .csproj 的目录）
dotnet run  -c Release             # 工作目录: plugin\tests\HttpTests（55+ 断言，不需要游戏）
```
改插件后**必须重打包**（Dalamud 自定义源从仓库里的 zip 更新）：
`python plugin/pack-release.py <bin/Release 目录> .` → 刷新 `plugin/release/ModBridge-<ver>.zip` + `pluginmaster.json` + `pluginmaster-cdn.json`（三者一起提交）。

### 3.2 前端（Vue）
```powershell
cd manager\web-src; npm install; npm run build      # 输出到 ..\web\
```
- **必须判退出码**：`npm run build` rc≠0 时立刻停，不要再打包 exe（曾用旧 web 出过假包）。
- 只有真改了前端才重建并提交 `manager/web/`；误跑后用 `git checkout -- manager/web` 还原并删除新哈希的未跟踪文件。

### 3.3 管理器服务 / exe / 交付包
```powershell
python mod_manager_web.py --port 8799 --no-browser --root <临时目录>   # 测试模式：配置/DB/汇总表全隔离
# 冒烟: GET /api/state（cats 是字符串列表） /api/mods /api/categories /api/tags /api/bridge /
C:\Users\qwe26\AppData\Local\Programs\Python\Python312\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name ModManagerWeb --icon app.ico --add-data "web;web" --exclude-module tkinter mod_manager_web.py
python manager\make_package.py     # → manager\dist\ModManagerWeb_部署包_v<版本>.zip
```

## 4. 版本号规则（三段式 vX.Y.Z）

| 组件 | 唯一来源 | 派生（自动同步，别手改） |
|---|---|---|
| 管理器 | `manager/app_version.py` : `APP_VERSION` | web 后端 `MANAGER_VERSION`、`make_package.VERSION`、`web-src/package.json`+lock、README/使用说明版本表 |
| 插件 | `plugin/ModBridge/ModBridge.csproj` : `<Version>` | Dalamud 清单与 `pluginmaster*.json` 的 `AssemblyVersion`（SDK 补成 x.y.z.0）、`/ping` 的 version |
| 拓展 | `browser-extension/manifest.json` : `version` | 两份安装说明 |

用脚本改版本，别手敲：`python scripts\check_versions.py [--bump patch|--bump-plugin patch]`。
**先升版本号，再编 exe**（顺序反了 exe 里嵌的还是旧号）。

## 5. 每次改动收尾必跑的四个自检

```powershell
python scripts\check_versions.py            # 版本一致性，退 0 才算过
python scripts\check_frontend_imports.py    # naive-ui 组件 / vue API 是否都 import（漏一个 = 白屏，vite 不报错）
python scripts\check_api_contract.py        # 拓展/前端 ↔ 后端 的路由与字段契约
# 动了前端：再跑 npm run build（判 rc）并用无头 Edge + CDP 真点一遍目标交互
```
改了任何 `.vue` 必须跑 `check_frontend_imports.py` 并看 **exit code**（脚本自身曾因目录写错而「假通过」）。

## 6. 定义完成（DoD）

1. 需求对应行为**实测通过**（不是「应该可以」）：UI 类用无头 Edge + CDP 点击/读值取证；接口类 curl/requests 实调；
   构建类给出命令与 rc。
2. 跑完第 5 节的四个自检，并附输出。
3. 变更清单：改了哪些文件、为什么、影响面（哪些接口/页面/组件受牵连）。
4. 若动了 `/api/*`：先搜这四处消费者 `browser-extension/content.js`、`browser-extension/sw.js`、
   `manager/web-src/src/api.js`、`manager/web-src/src/views/*.vue`。**新字段只增不删**。
5. 交付物：可直接覆盖的产物（exe / 发布包 zip / 插件 zip）+ 自测证据；要同步 `G:\Games\FFXIV\Soft`。
6. 收尾按项目发布策略：小改（文案/界面/小优化）只升版本号 + commit/push；**功能新增或重要修复才打 tag + Release**。
   打 tag 前先 GET `https://api.github.com/user` 用 `C:\Users\qwe26\github_token.txt` 验 token；Release 附件名必须纯 ASCII。

## 7. 硬规则（违反 = 返工）

- **运行数据一个都不许碰**：`mod_manager.json` / `mod_manager.db` / `mod_manager.log` / `backup/` /
  `browser_profile/`（150MB 登录态，删了要重新登录）/ `.thumb_cache/` / `cover_cache*/`。
  覆盖线上副本时只覆盖程序文件，清理只清可再生的 `build/ dist/ __pycache__/ web_proto/`。
- 不提交运行时产物：`*.exe *.zip`（例外：`plugin/release/*.zip`）、`.db`、`.log`、`node_modules/`、`shots/`（见 `.gitignore`）。
- 行尾统一 CRLF。改文件用字节级读写，读时把 `\r\n` 归一成 `\n` 再写回（**双转换会产生 `\r\r\n`**，
  会让 `.gitignore` 整片失效）。写完断言文件里没有 `\r\r`。
- 部署 `.py` 到线上目录后**必须删该目录的 `__pycache__`**，否则旧 `.pyc` 仍生效（「改了没反应」的经典根因）。
- 删除一律走回收站（`mm.send_to_recycle_bin`），不要直接 `unlink`；删非空目录要显式后果提示。
- 面向用户的文案里不出现真实客户/站点名；分发目录归用户所有，不许在其中删任何文件。

## 8. 高频坑（先读再改，能省几小时）

1. **PyInstaller 打包的 exe 内嵌 `web/`**，会盖过部署目录的 `web\` —— 改了前端只更新部署目录 = 看不到效果，
   必须重建 exe。快检：`GET /` 里 `assets/index-*.js` 的 hash 与部署目录 `web/assets` 是否一致。
2. 前端用 `n-space` 排按钮会出现长短不齐，主人明确否掉 → 用 `n-button block` + CSS grid 两列。
3. naive-ui 插槽必须作为 `h()` 第三个参数传，写成 props **静默渲染成空**。
4. naive-ui 组件每个 view 自己 import，模板写了 `<n-tabs>` 但没 import → 不渲染且不报错。
5. `n-radio-button` 渲染成 `<button class="n-button">`，选择器会选错元素；dialog 是 `.n-dialog` 不是 `.n-modal`。
6. `execute_code` 内核常驻：改了 `mod_manager.py` 要 `importlib.reload(mm)`；`terminal`/`read_file` 在本机看不到 E:/G: 盘
   → 文件与网络操作一律走 Python（`open()` / `subprocess` / `requests`，绝对 Windows 路径）。
7. 名字匹配一律用 **token 全覆盖**（`same_name_tokens`），不要用双向子串 —— 否则 `Botanica` 会把
   `Botanica Bodychain` 判成已安装。判「已安装」要传作者名做白名单，并写「已安装判定」日志。
8. 建文件夹名必须过 `mm.safe_name()` 清洗 Windows 非法字符（`|` 等，否则 WinError 123）。
9. 封面链路：**封面必须塞进包内**再交给 Penumbra（`InstallMod` 只收包文件，装完再写目录不可靠）；
   包内自带真 `cover.webp` 要保留，伪 WebP（非 `RIFF…WEBP`）必须替换。
10. `_bridge_find_package()` 没有可安装包时抛 `SystemExit`（不是返回 None）→ 必须 `try/except SystemExit`。
11. `launch_browser()` 在浏览器已运行时**不导航** → 读页面一律用 `mm.browser_goto()`。
12. JS 里 `slice()` 会把 emoji 代理对切半 → 传回 Python 令 `json.dumps` 抛 `UnicodeEncodeError` 让接口 500；
    两侧都要防护（JS 安全截断 + `mod_manager.fix_text()`）。
13. XMA 登录态 Cookie 是 `connect.sid`；只认 `session`/`xf_` 会误报未登录。NSFW 页面纯 HTTP 会 403，必须真浏览器兜底。
14. 窗口/栅格：展开态 `.right` 必须 `align-content: start`，否则窗口高时标题上方空一块。
15. `.wall` 图片墙要 `grid-auto-rows: max-content`，否则标题被裁。
16. 前端同一动作有两条调用路径（工具栏传文件夹字符串、详情传对象）→ 处理函数开头必须归一化，
    否则出现 `undefined` / `[object Object]`。
17. 会写数据的动作，弹窗里必须同时有「预览」和「写入」两个按钮，写入是主按钮。
18. 只读 sqlite 连接看不到 WAL 未提交数据 → 核验走 HTTP 接口或把 `db`+`-wal`+`-shm` 拷出来读。
19. 读取/校验版本号不要按「字符串出现次数」判（依赖包版本会撞车），要按 JSON 结构核对。
20. 打包/部署脚本里 `shutil.copy2` 会保留 mtime → 配合 `__pycache__` 清理，见第 7 节。

## 9. 沟通要求

- 汇报用中文，**结论前置 + 证据（命令、输出、文件行号）**；没跑过的不要说成跑过了。
- 拿不准的取舍先说明候选方案与影响，不要静默改公共行为。
- 长任务分阶段汇报：定位 → 改动 → 验证 → 交付。
