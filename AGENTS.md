# AGENTS.md —— 给编码代理的项目说明书

> 本文件由 dsh / 其他编码代理在会话开始自动加载（项目根 = 含 `.git` 的目录）。
> 目标：让代理**不必摸索就能按本项目的既有规范改动、验证、发版**。
> 规则优先级：本文件 > 你的习惯。与主人（yomo1024）的当场指令冲突时，以当场指令为准。

## 当前状态（新会话先读这段）

> 最后更新：2026-09-30（本节的「最近完成」按 git log 维护；「待办」由主人补充）

| 组件 | 当前版本 | 唯一来源 |
|---|---|---|
| 管理器 ModManager | **v2.35.4**（最新 tag = **v2.35.2**）｜拓展 **v1.2.8** | `manager/app_version.py` |
| 游戏插件 ModBridge | v0.2.13 | `plugin/ModBridge/ModBridge.csproj` |
| 浏览器拓展 | 见文件 | `browser-extension/manifest.json` |

### 最近完成（倒序，来自 git log）

- **v2.35.4 修「从云盘取回也没有取回」的真根因：夸克 `__puus` 过期 → 下载被 412/403**（主人 2026-09-30 报）：
  夸克的**下载直链是用 Cookie 里的 `__puus` 校验的，24 小时过期**；过期之后
  **API 一切正常（列目录 / 上传 / 归档都成功），但 CDN 下载必被拒** ——
  实测：索引文件 **HTTP 412**、载荷文件 **HTTP 403**，而且是 Tengine 的空壳正文，光看报错查不出原因
  （v2.35.3 的自愈就是死在这一步：`cloud_index_restore_core` 下载云端索引 412 → 没有条目 → 取回空手而归）。
  每次 API 响应其实都用 `Set-Cookie` 下发**新的 `__puus`**，而驱动把它丢了。
  **修法**：`quark_drive._merge_set_cookie()` 把响应里的 Set-Cookie 合并进 `drv.cookie`（`_call` 里落）；
  `_cloud_download` 被 403/412 拒时 `drv.refresh_cookie()` 后重签直链重试一次；
  下成功后 `_persist_cloud_cookie()` 把刷新过的登录态**写回配置**（否则重启又拿旧的）。
  **实测（真云盘）**：同一 URL 旧 cookie → 412，换新 `__puus` → 200；
  修好后索引恢复一次成功（56 条）、对账重建清单、取回真下到 `[D] Soft Tummy Tights.pmp`（2,200,023 字节，
  与云端一致）；空库 + **配置里故意放过期 cookie** 走「从云盘取回」→ 自愈按「先索引恢复 → 再对账」跑通；
  线上「测试连接」从报“下载被拒”变成 `download_ok: true（实下 49041 字节 OK）`。
  ⚠ 以后凡是「API 好、下载坏」的云盘故障，先看 Cookie 里的 __puus 有没有被 Set-Cookie 刷新。
- **v2.35.3 修「新电脑上点从云盘取回 → 没有已归档的 Mod」**（新电脑报的）：见下（自愈 + 换机恢复入口）

- **v2.35.3 修「新电脑上点从云盘取回 → 没有已归档的 Mod」**（主人 2026-09-30 在新电脑报的）：
  **归档状态只存在本地索引里**（`cloud_state` + `payload_files` 云端载荷清单），新机器索引是空的
  → 取回必然找不到东西。而且界面的判定还只看 `archived_files`（载荷清单条数），
  那个字段**只有归档/对账才会填**，索引恢复不填 —— 所以就算先恢复了索引，取回照样说「没有已归档」
  （这就是主人看到那句的真正出处：`ModsView.restoreCloud()` 的前端提示，不是后端）。
  修法三件：
  ① **取回自愈** `_heal_archive_state()`：一条归档记录都没有 → 先「从云端索引恢复」，
     再对这些条目「与网盘对账」重建载荷清单（全程只读云端 + 写本地索引，不下载载荷、不动云端）；
     `api_cloud_restore` 在没归档记录时不再直接报错，而是返回 `{heal: True}` 让任务先自愈；
     真没得取时按 `cloud_probe()` 的结果给准确原因（没填 Cookie / 云端根读不到 / 云端没索引文件）。
  ② **装进游戏也自愈**：`_ensure_payload_for_install` 遇到「有条目但载荷清单空」先对账这一条再装。
  ③ 界面：新增 **`GET /api/cloud/ready`**（只读自检：本地条数/已归档/有载荷清单/云端根/云端索引）
     + 「换机恢复…」按钮与弹窗（①只恢复索引 ②只对账 ③只取回 + 「自动按顺序做完」）；
     `restoreCloud`/`verifyCloud` 的判定改成 `hasCloud()`（cloud_state=archived 或 archived_files 或 cloud_size）。
     `cloud_reconcile` 拆出 `cloud_reconcile_core(cfg, write, folders, job=None)` 好让自愈只对几条复用。
  **实测**：空库 + 桩云端 → `_heal_archive_state` 依次调用索引恢复(1 次)与对账(只对这 2 条)，
  载荷清单真的建出来、第二轮幂等；`_job_cloud_restore({heal:True})` 全桩跑通 1 个文件、状态转 local；
  无头 Edge 实测：工具栏「换机恢复…」与「取回碰壁」都弹自检弹窗（含建议、云存储没配好时动作按钮禁用），
  旧那句「选中的里面没有已归档的 Mod」不再出现。**只读自检实测（主人这台旧机）**：
  本地 56 条 / 已归档 55 条 / 有载荷清单 55 条 / 云端根读到 / **云端索引文件有** → 新电脑走「换机恢复」即可。

- **v2.35.2 发版：把拓展 1.2.8 打进部署包**（主人 2026-09-30 要「带 1.2.8 的部署包 + 新 tag/Release」）。
  管理器代码**没有任何改动**，纯粹是**版本落点**跟着走一版（否则同一个 v2.35.1 的附件换内容会说不清）；
  按规矩**先升版本号再编 exe**，所以 exe / 桌面版都重打了一遍（自报 2.35.2 已实测）。
  包内已核对：`browser-extension/manifest.json` = **1.2.8**、`sw.js` 是新版（tabs.sendMessage 修法）、
  exe sha256 与仓库一致、zip 完整。

- **拓展 v1.2.8 修「后台控制台刷 Uncaught (in promise) Could not establish connection」**（主人 2026-09-30 报）：
  队列一变就广播 `queueChanged`，写的是从 **SW** 发 `chrome.runtime.sendMessage` —— 而 MV3 里
  **「后台 → content script」这条广播根本到不了**（无头 Edge + CDP 同时连 SW 与页面里的面板世界实测：
  面板世界的 `onMessage.hasListeners() === true`，从 SW 发出去依旧 reject），
  于是它既没刷新过面板、又每次都在后台留一条未捕获异常（还会被标错误角标）。
  改法：`notifyQueueChanged()` 改用 `chrome.tabs.query({url:'https://www.xivmodarchive.com/*'})`
  + 逐个 `chrome.tabs.sendMessage(tabId, …)`（**不需要加 tabs 权限**，host_permissions 已覆盖），
  每个 tab 单独 catch「那个页面没在听」；`content.js` / `popup.js` 的 send 回调里补读
  `chrome.runtime.lastError`（否则页面控制台会留 `Unchecked runtime.lastError` 警告）。
  实测：无 XMA 页面时 `setQ([])` **0 未捕获异常**（旧版 1 条）；开着 XMA 页面时面板世界**真的收到**
  `queueChanged`；队列写入/读取/patch/清空回归全过。
  ⚠ 教训：**别用 SW 的 `runtime.sendMessage` 去叫 content script**（不会到），要按 tab 用 `tabs.sendMessage`；
  另外「不带 callback 的 sendMessage 返回 Promise」，同步 try/catch 抓不到它的 rejection。

- **v2.35.1 已发版**（tag + Release + 附件 `XMA-Manager-v2.35.1.zip`，纯 ASCII 名）：
  Release 正文把 v2.35.0 的实时刷新一起写了（两版合并发布）。
- **v2.35.1 修「拓展下载入库后序号是错的」**（主人 2026-09-30 报）：序号的不变量是
  **每个分类各自 1..N**（`renumber_plan` 按分类连续排、`cmd_check` 按「(分类, 序号)」判重复、
  库里现有数据也是这个口径 —— 衣服 1..12 里 3 号住在子分类 Katami ☆），
  可新入库用的是 `next_seq(目标目录)`（**只在本目录里取最大 + 1**）→ 往子分类或另一个 zone 里入库就
  **撞号**（皮肤/SFW/纹身 里最大是 1 → 给新号 2，而 2 早被 皮肤/NSFW/纹身 拿走了）。
  改法：新增 `next_seq_in_category(cfg, category, exclude=None)`（整棵分类子树取最大 + 1，
  忽略重排临时号区 `RENUMBER_TMP_BASE=900000`），`import_mod` 与桌面 GUI 两处建议值都改用它；
  旧的 `next_seq` 改名 `next_seq_in_dir` 并把「别拿它给新 Mod 编号」写进 docstring（防回归）。
  **实测**（隔离库按真实结构搭）：拓展推送入库 → 皮肤新号 **15**（旧口径是 2）、
  手加 Mod 到 子分类 → 衣服 **13**（旧口径 4 冲突）、到同分类另一 zone → **14**、显式序号照旧尊重、
  同地址再推认成更新不换号、重排后每分类 1..N 无冲突。
  顺带修：`_job_selfdownload` / `_job_import_file` 的 `got` 只在「要处理封面」分支里赋值 →
  payload 带 `cover:false` 时 `UnboundLocalError`，**Mod 已入库但任务报 error**（界面上什么都看不到）。
- **v2.35.0 界面实时跟随内容变化**（同上一条的上一版，见下方「界面实时刷新」一节）

- **v2.35.0 界面实时跟随内容变化**（主人 2026-09-30 报：下载/导入/归档之后界面**不跟着动**）：
  真因是前端只在「**自己**发起的任务结束时」才 `refreshAll()` —— 任务跑着的时候一律不刷新（归档一条大包
  要几分钟，列表一直停在旧样子），而拓展 / 插件 / 另一个窗口发起的改动（任务由后端直接起）页面**完全不知道**。
  做法：新增 **`GET /api/watch?since=<指纹>`**（`data_signature()`）一次回答两件事 —— ①索引库/待导入目录/
  游戏 mod 目录/配置**变了没**；②现在有没有任务在跑（**别处起的一样看得见**）。前端 `AppShell` 用自适应轮询
  （空闲 2s / 任务在跑 600ms，页面在后台不轮询、切回来补一次），指纹变了就 `refreshAll()` + 当前页 `bus.refresh()`。
  **库这一侧只用 `PRAGMA data_version` + `COUNT(*)`**（不读整表），磁盘只 stat/浅扫目录 —— 这条通道每 2 秒跑一次，
  必须保持很轻。实测：别处写库 **1.32s** 出现在界面；别处起的 `scan` 任务 2s 内出现任务条、结束只弹一次提示、
  8 秒内无重复；开着详情面板时改名也自动跟着变（ModsView 本来就有 `watch(() => props.mods)` 重挂 `cur`）；
  空闲轮询**不会**点亮全局「处理中」加载条。
  ⚠ 坑：探测连接要 `check_same_thread=False` + 自己加锁 —— `ThreadingHTTPServer` 每请求一线程，而这条连接必须
  **常驻**（`data_version` 是连接私有的计数器）；忘掉这个参数会从第 2 次调用起退化成 `db:err`，
  表现是「没改却报有变化 / 改了却不报」两头假信号（当时真被绕了一圈）。另：只读连接用
  `file:...?mode=ro` URI，**绝不能把不存在的库凭空建出来**。

- **v2.34.2 消灭「弹命令窗口」**（主人要求：别让用户看到命令窗口）：`--windowed` 的 exe 没有控制台，
  启动控制台子进程（7-Zip / wmic / taskkill / netstat）时 Windows 会给它**新建一个可见的控制台窗口**
  —— 下一个 heliosphere mod 要调 7-Zip 十几次（主人真下的一条有 **88 个文件 = 88 次**），满屏黑框闪。
  修法：`mod_manager.CREATE_NO_WINDOW` / `no_window()` 助手，9 处控制台调用全部加上；
  `启动Mod管理工具.bat` 改 `pythonw` 无控制台启动。
  证据：① 受控对照（pythonw 模拟 windowed exe）不带 flag → 可见窗口 0→1（新增的是 ping.exe 的窗口），
  带 flag → 0→0；② 端到端真下载（13 文件 / 13 次 7-Zip）409 次采样可见窗口 min=max=0。
  ⚠ 新增任何 `subprocess` 调用控制台程序时，**必须**带上 `creationflags=` / `**no_window()`**。
  **上线默认静默、调试可开**：`--show-console`（或环境变量 `MODMANAGER_CONSOLE=1`）会把
  `mm.CONSOLE_DEBUG` 打开 → 子进程**不再**加 CREATE_NO_WINDOW（能看见 7-Zip 窗口，方便排查）；
  两个都不设 = 线上行为（一个黑框都不弹）。两模式都实测过：默认下载 13 文件全程可见窗口 0 个，
  `--show-console` 下同一个下载能看到 8 个 7z.exe 窗口。
- **v2.34.1 修「工作台对 heliosphere 误报没有读到下载链接」**（主人当天就撞上了）：
  `doFetch()` 用 `page.dl` 判「能不能下载」，而 heliosphere **没有页面直链**这个字段
  （下载是管理器读 GraphQL 清单后本地打包），后端早已返回 `has_download: true` ——
  于是解析成功、按钮却是灰的、点了就报「这个页面没找到下载链接」。
  修法：新增 `canDownload = dl || helio`，「下载并入库」按钮与 `doFetch()` 都改用它；
  heliosphere 时隐藏「用我自己的浏览器下载」（那条路只对 XMA 有意义）；
  「下载链接」一行改显示「heliosphere：管理器直接下载（不用页面直链）」。
  取证：无头 Edge 真点一遍工作台（解析 → 按钮可点、无警告 → 下载入库 78 秒完成、封面已抓，带截图）。
  ⚠ 教训：**加新站点支持时要连前端判据一起扫** —— 凡是拿 `page.dl` 当下载前置条件的入口都要过一遍。
- **v2.34.0 heliosphere.app 正式并入：从该站下载 mod + 取封面**（主人 2026-09-30 要求）：
  侦查结论（别再猜）——① 页面是 SvelteKit，**SSR 里内嵌了 `/api/graphql` 的响应，匿名就能读到**
  名称/作者/标签/Affects/版本/更新时间/下载大小/`versionId`/封面图 id（没有 Cloudflare、不用登录）；
  ② 官方那个「Download as PMP」是**浏览器里 SharedWorker 客户端打包**
  （`_app/immutable/workers/pmpDownloader.worker-*.js`）：`GraphQL getVersion(id)` → `neededFiles{baseUri,files}`
  → 逐个下 `https://data.heliosphere.app/files/<key>`（**内容是 zstd**）→ 重压 → 打 zip；
  ③ 封面直链 `https://heliosphere.app/api/web/package/<包id>/image/<图id>`（WebP，实测 2560×1440 / 268 KB）。
  **实现**：新模块 `manager/heliosphere.py`（纯标准库）按同一规则复刻打包 —— 7-Zip 解 zstd
  （`unzstd()`，7z 路径可用配置项的 `sevenzip` 覆盖）+ `zipfile` 打包（含 `heliosphere.json` / `meta.json`
  的 `Groups` 数组、`>32` 选项的 Multi 拆 `Part N`、`ui/` 重名改名、`HS_*` 与 null 白名单键剔除等官方细节）。
  **正确性证据**：用无头 Edge 跑官方 worker 生成对照 pmp → 16 个条目名一致、13 个文件内容 sha256 全同、
  `meta.json` 深度相等（只有 zip 内条目顺序不同）。
  接入：`_site_info`/`_site_download`/`_job_fetch`/`mod_fix_cover` 的 heliosphere 分支全部**纯 HTTP**
  （不再弹内置浏览器），入库顺带写站点简介（`_put_site_desc`，本地已填不覆盖）。实测译文见提交说明。
- **v2.33.31 / 拓展 v1.2.7 修「上传后封面还是缩略图」**（主人 2026-09-30 报的）：定位到真根因 ——
  `static.xivmodarchive.com/mod-images/<uuid>.jpg` 在 Cloudflare 后面，**拓展 service worker 里的 fetch
  拿到的是 CF 挑战页**（HTTP 403 / 「Just a moment...」，实测 len≈5.9KB），而 **`chrome.downloads.download()`
  走浏览器下载通道能完整拿到 1920×1080 / 1.2 MB**。所以拓展改成「先下载封面 → 把本地文件路径推给管理器」，
  入库完删临时文件；管理器新增 `write_cover_path()` 直接读本地文件。配套修 `write_cover_bytes`：
  以前只写同级大图、`ensure_cover_inside` 见「文件夹里已有图」就返回 → 文件夹内那张 355×200 永远留着，
  新增 `upgrade_inside_cover()` 在「新图更大」时一起替换（包内封面 Penumbra 用的是文件夹内那份）。
- **v2.33.29 / v2.33.30**（另一会话）：`site_time_missing` 改名漏改两处 return 键 → 上传 100% 后 NameError；
  以及补封面不再静默（记录「没带封面字节/拓展报错/全尺寸失败原因」）。

- **v2.33.28 / 拓展 v1.2.6 修「封面取成缩略图」**（主人报的）：封面**改从页面头图轮播取** ——
  `<img class="d-block w-100 mod-carousel-image">` 里的 `mod-images/<uuid>.jpg` 才是本体（实测 1920×1080）；
  `mod-thumbnails/<uuid>.jpg`（355×200）是缩略图，页面下方「相关 Mod」卡片用的就是它，以前有被当成封面的风险。
  更关键的是取图手段：**urllib 直连 / 带浏览器 Cookie 的 urllib 抓 static.xivmodarchive.com 都是 403**
  （cf_clearance 绑浏览器指纹），页面里跨域 `fetch` 又被 CORS 挡 —— 新 `browser_fetch_bytes()` 改用
  **开后台标签页停在图片网址上再 `fetch(location.href)`（同源）**，实测拿回 1920×1080 / 1.2 MB。
  另外：只有缩略图地址时先用**同 UUID**换 `mod-thumbnails → mod-images`；低清兜底落盘前比大小，
  **已有更大的封面就不许顶掉**（`_bigger_cover_kept()`）。

- **v2.33.26 / 拓展 v1.2.5 修「下载 mod 没传更新时间」**（主人报的第二次）：`content.js` 取时间的
  那段用了 forEach 里的局部变量 `t`（外层不存在）→ 异常被自己 catch 吞掉 → `updated` 恒为空。
  改成在已有的 `.mod-meta-block` 遍历里取（另加全文兜底）；管理器侧 `site_time_iso()` 也会剥掉
  末尾时区括号（`(GMT+8)`）了。验证：Node 拿 git HEAD 与工作区两份代码跑同一段页面文本对比。
- **v2.33.24 日志按分类分文件 + 拓展只留 F 盘**（主人要求）：日志统一进 `Logs\`——`全部.log`（带 `[分类]` 前缀）
  + `云盘.log`/`导入.log`/`更新.log`/`扫描.log`/`插件.log`/`浏览器.log`/`备份.log`/`检查.log`（任务按 kind、
  接口按路径设分类上下文，其余按关键词兜底，240 处老 log() 一行没改）；日志页加分类切换条 + 每行彩色分类标签 +
  分类计数。浏览器拓展只在 `F:\REPO\FFXIV_XMA_M\browser-extension`（旧路径那份已删，主人手动在 Chrome 重新加载）
- **v2.33.22~23 NSFW 封面改「悬停看清、移开自动模糊」**（主人报的）：原来只能点一下才解除。
  用 **CSS `:hover`**（不用 JS 记悬停状态：naive-ui 表格会在悬停约 1.5 秒后重渲染，JS 状态会丢）；
  表格缩略图的模糊在内联样式里 → 加 `nsfw-blur-cell` 标记 + `:hover{filter:none!important}`。
  排查中发现的「假 bug」：顶部「处理中」条消失让整页上移 39px，鼠标底下换了元素 —— 不是 hover 失效；
  验证 hover 类效果要**等页面静置**再测，并用 `elementFromPoint` 判断鼠标底下还是不是它。
- **v2.33.21 修「编辑 Mod 改子分类不生效」**（主人报的）：网页发 `subcat`、后端 `mod_edit`/`mod_add` 只读
  `subdir` → 字段被静默丢掉（接口还回 ok=true，看着像成功）。现在统一走 `_sub_of(b)`（两种叫法都认），
  并给 `check_api_contract.py` 加了护栏：写接口里直接读 `subcat`/`subdir` 就报错
- **v2.33.18~20 「运行日志」页面 + 弹窗自己的进度条**（主人报的）：侧栏新增「运行日志」（自动刷新 /
  关键字全库查找 / 报错警告高亮计数 / 复制 / 打开日志目录）；`withDialogProgress()` + `TaskProgress.vue`
  浮层 —— 弹窗类按钮点下去，**弹窗上直接压一层进度卡**（任务=真百分比+可取消，同步接口=动画条+秒数），
  已接入 12 处动作（索引恢复/扫描网盘/认领/同步索引/归档/取回/对账/校验/更新/云盘体检/接管/索引修复）
- **v2.33.16~17 「所有加载都有反馈」**：① 全局加载条（任何接口在飞 >300ms 就显示中文动作名 + 动画条 + 已用秒数）；
  ② 慢接口**任务化**（`runJob()`）：从云端索引恢复 **33.4s → 1.9s**（原来每次递归遍历整个网盘找索引文件，
  现在先看云端根目录）+ 真进度 + 可取消；③ `check_api_contract.py` 修掉「映射表键被当成调用」的误报
- **v2.33.15 归档不再「点了没反应」**：准备阶段（把封面插进包 = 重压整包）逐步上报 + 可取消；
  带图包可复用（`.part` 原子写）；归档后清掉工作副本（实测清过 1496 MB）
- **v2.33.12 已发版**（tag + Release）：索引一致性（v2.33.4）、检查报告逐条处置（v2.33.5）、NSFW 显示开关（v2.33.6）、入库封面/浏览器链路与拓展 1.2.4（v2.33.7~v2.33.12）
- **v2.33.7** 入库：封面抓不到全尺寸时**退到公开缩略图兜底**（不再静默留空封面）；入库不再为「标签/影响/更新时间」弹内置浏览器（拓展推来的信息够用就不弹）
- **v2.33.6** 显示开关：NSFW 总开关（默认关，关着时列表/统计/待办/检查/查重/安装都不显示 NSFW，列表上有「已隐藏 N 条 + 现在显示」提示条）+ NSFW 封面模糊（默认开，点一下看那张）
- **v2.33.5** 检查报告：每条问题都能就地处置（地址提到文件夹根 / 生成同级封面 / 清理记录 / 去列表处理）+ 一键规范；补预览图等写入链路同时落「同级同名」规范位
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
- v2.34.3 已发版（tag + Release + 附件 `XMA-Manager-v2.34.3.zip`）；
  **主人明确不做**：浏览器拓展的 heliosphere 页面支持（公开内容管理器直连即可，拓展没有功能必要性）
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
| 线上运行副本（**只在交付时覆盖程序文件**） | `F:\REPO\FFXIV_XMA_M`（2026-09-29 从 G:\Games\FFXIV\Soft 迁来） |
| 真实 Mod 库 | `G:\Games\FFXIV\MOD\202609`（**没动过**，管理器换地方不影响它） |
| 浏览器拓展（Chrome「已解压」加载路径） | `G:\Games\FFXIV\Soft\browser-extension` —— **故意留在旧路径**：已解压拓展的 ID 由路径算出来，一挪 ID 就变；所以旧路径并不是残留，更新拓展时**这里和 F 盘那份都要放**（或让主人从 F 盘重新加载拓展后再删） |
| .NET 10 SDK（**不在 PATH**） | `C:\Users\qwe26\AppData\Local\Microsoft\dotnet\dotnet.exe` |
| Dalamud 引用库（编译插件必需） | `E:\Hermes\dalamud-dev` → 环境变量 `DALAMUD_HOME` |
| Node 22 / npm | `C:\Users\qwe26\.hermes-web-ui\desktop-runtime\hermes\0.21.3\win-x64\node` |
| Python 3.12（含 PyInstaller 6.22.3 + tkinter） | `C:\Users\qwe26\AppData\Local\Programs\Python\Python312\python.exe` |
| 7-Zip（**heliosphere 下载必需**：它的文件是 zstd） | `C:\Program Files\7-Zip\7z.exe`（`heliosphere.zstd_exe()` 会自动找；可用配置项 `sevenzip` 覆盖） |

- **G 盘不是 NTFS**（`fsutil`/`Get-Volume` 显示 Unknown，实际 exFAT 类）：**不能建 junction / 符号链接**（`mklink /J` 报「需要本地 NTFS 卷」），而且 G↔F 之间复制很慢（实测约 17 MB/分钟，1.1 GB 花了 5 分半）—— 大批量搬运要后台跑 + 进度核对。
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
5. 交付物：可直接覆盖的产物（exe / 发布包 zip / 插件 zip）+ 自测证据；要同步 `F:\REPO\FFXIV_XMA_M`。
6. 收尾按项目发布策略：小改（文案/界面/小优化）只升版本号 + commit/push；**功能新增或重要修复才打 tag + Release**。
   打 tag 前先 GET `https://api.github.com/user` 用 `C:\Users\qwe26\github_token.txt` 验 token；Release 附件名必须纯 ASCII。

## 7. 硬规则（违反 = 返工）

- **运行数据一个都不许碰**：`mod_manager.json` / `mod_manager.db` / `Logs/`（日志，按分类分文件）/
  `backup/` / `browser_profile/`（150MB 登录态，删了要重新登录）/ `.thumb_cache/` / `cover_cache*/`。
  老的单文件 `mod_manager.log` 已不用：程序启动后第一次写日志时会自动搬进 `Logs\全部.log`。
  覆盖线上副本时只覆盖程序文件，清理只清可再生的 `build/ dist/ __pycache__/ web_proto/`。
- 不提交运行时产物：`*.exe *.zip`（例外：`plugin/release/*.zip`）、`.db`、`.log`、`node_modules/`、`shots/`（见 `.gitignore`）。
- 行尾统一 CRLF。改文件用字节级读写，读时把 `\r\n` 归一成 `\n` 再写回（**双转换会产生 `\r\r\n`**，
  会让 `.gitignore` 整片失效）。写完断言文件里没有 `\r\r`。
- 部署 `.py` 到线上目录后**必须删该目录的 `__pycache__`**，否则旧 `.pyc` 仍生效（「改了没反应」的经典根因）。
- 删除一律走回收站（`mm.send_to_recycle_bin`），不要直接 `unlink`；删非空目录要显式后果提示。
- 面向用户的文案里不出现真实客户/站点名；分发目录归用户所有，不许在其中删任何文件。

## 8. 高频坑（先读再改，能省几小时）

0. **停实例只能按「完整路径精确匹配」定位进程**（2026-09-30 踩过）：查占用时用名字子串匹配
   （`"ModManagerWeb" in exe`）会把 **F 盘线下副本里主人正开着的那个**一起杀掉 ——
   要 `os.path.normcase(exe) == os.path.normcase(目标 exe)` 这样比，并且**杀掉之前先把 PID + 路径打出来**。
   另外 PyInstaller onefile 的实例是**两个进程**（父+子），两个都要按路径认。
0b. **heliosphere 下载链路**（v2.34.0）：页面 SSR 里有 GraphQL 响应（匿名可读）→ `manager/heliosphere.py`
   用 `getVersion` 拿文件清单 → `data.heliosphere.app/files/<key>` 是 **zstd**（用 7-Zip 解）→ 本地打 zip 成 `.pmp`。
   **纯 HTTP，别开内置浏览器**；下载必须核对 `Content-Length`（网络抖动会"读到一半 EOF"且不抛异常，
   症状是 7z 报 `Unexpected end of data`）。新增模块记得加进 `manager/make_package.py` 的 `SRC_FILES` 与 `out` 列表。

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
