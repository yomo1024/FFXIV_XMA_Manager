# Mod Bridge —— 网页 ↔ 游戏内 ↔ Penumbra 的桥

mod 管理器点「安装到游戏」→ 插件在游戏内窗口列出来 → **你在游戏里确认** → 插件调 Penumbra 的 IPC 装进去 → 在集合里启用 → 触发重绘，立刻生效。

两种玩法（都支持）：

| 流程 | 接口 | 说明 |
|---|---|---|
| **两段式（默认，推荐）** | `POST /propose` → 游戏内确认 → `/decide` | 管理器只"送"过来，游戏里看到 mod 名/作者/封面/包路径，点「确认安装」才真的装 |
| 直接装（跳过确认） | `POST /install` | 给信任的自动化用 |

配套的管理器（本机的 Mod 管理网页）已经接好：Mod 列表里选中一条 → 右侧「安装到游戏」→ 游戏内窗口出现该 mod → 点「确认安装」。

配套的技术调研与 API 依据见上一级目录的 **[技术方案.md](../技术方案.md)**（含所有 Penumbra 签名的来源）。

---

## 1. 目录

```
ModBridge/
  ModBridge.csproj          Dalamud.NET.Sdk/15.0.0（当前脚手架）+ Penumbra.Api 5.19.2
  build.bat                 一键构建（ASCII，防 GBK 乱码）
  Plugin.cs                 IDalamudPlugin：接线、生命周期、/modbridge 命令
  Configuration.cs          IPluginConfiguration：端口、token、行为开关
  PenumbraBridge.cs         Penumbra IPC 封装（全部调用自动切 framework 线程）
  Http/
    HttpMiniServer.cs       手写的最小 HTTP/1.1 服务（TcpListener，仅 127.0.0.1）
    ApiRouter.cs            路由 + token 鉴权 + 域名白名单
    JobManager.cs           安装任务：下载→安装→启用→重绘，带进度/取消
    IModBridgeLog.cs        日志抽象（让 HTTP 层能脱离 Dalamud 单测）
    PluginLogAdapter.cs     把 Dalamud IPluginLog 适配成上面那个抽象
  Windows/MainWindow.cs     游戏内窗口：状态 / 端口 / token / 安装记录
tests/HttpTests/            HTTP 层的独立自测（不需要游戏、不需要 Dalamud）
```

## 2. 构建

需要 **.NET 10 SDK**（插件目标 `net10.0-windows`，来自 `Dalamud.NET.Sdk/15.0.0`）。

```bat
cd ModBridge
build.bat
:: 等价于：dotnet build -c Release
```

**如果这台机器没装 XIVLauncher/Dalamud**，编译器找不到 Dalamud 的引用库（默认路径
`%APPDATA%\XIVLauncher\addon\Hooks\dev\`）。两种解决办法：

```bat
:: a) 临时指定（推荐，不改项目文件）
dotnet build -c Release -p:DalamudLibPath="E:\dalamud-dev\"

:: b) 设环境变量
set DALAMUD_HOME=E:\dalamud-dev
```

`E:\dalamud-dev` 就是 Dalamud dev 发行包（`https://goatcorp.github.io/dalamud-distrib/latest.zip`，约 58 MB）解压后的目录，里面有 `Dalamud.dll`、`Dalamud.Bindings.ImGui.dll` 等。

产物：

| 文件 | 用途 |
|---|---|
| `bin\Release\ModBridge.dll` | 插件本体 |
| `bin\Release\ModBridge.json` | Dalamud 清单（`DalamudApiLevel: 15`，由 SDK 从 csproj 属性生成） |
| `bin\Release\ModBridge\latest.zip` | 打包好的发布包（DalamudPackager） |

## 3. 装进游戏

把整个 `bin\Release` 目录拷到：

```
%APPDATA%\XIVLauncher\devPlugins\ModBridge\
```

然后在游戏里 `/xlplugins` → Dev Plugins → 启用 **Mod Bridge**，用 `/modbridge` 打开窗口。

## 4. 用起来

1. `/modbridge` 打开窗口 → 看到 **端口** 和 **Token**（有按钮一键复制）。
2. 网页/工具按下面的接口调用（**除 `/ping` 外都要带 token**）。
3. 窗口里的「安装记录」会实时显示下载进度、Penumbra 返回值、失败原因。

### 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ping` | 插件是否在跑 + Penumbra 版本 + mod 目录 + mod 数（**不需要 token**） |
| GET | `/mods` | 已装 mod 列表（`{dir,name}`） |
| GET | `/collections` | 集合列表 + 你当前生效的集合 |
| POST | `/propose` | `{url \| localPath, name, author?, description?, coverPath?, dirName?, enable?, priority?, origin?}` → `{requestId}` **送到游戏里等确认** |
| GET | `/requests` | 待确认列表 + 最近处理记录（`{pendingCount, pending[], recent[]}`） |
| POST | `/decide` | `{requestId, approve}` → 批准则 `{state:"approved", jobId}` |
| POST | `/install` | `{url \| localPath, dirName?, enable?, priority?}` → `{jobId}`（**跳过确认**，直接装） |
| GET | `/status?jobId=` | 任务进度（`state/percent/steps/error`）；不带 jobId 返回最近 20 条 |
| POST | `/cancel` | `{jobId}` |
| POST | `/enable` | `{dir, name?, enabled?, collectionId?}` |
| POST | `/priority` | `{dir, name?, priority}` |
| POST | `/redraw` | 触发游戏重绘 |
| POST | `/reveal` | `{dir, name?}` 在 Penumbra 窗口里高亮这条 mod |
| POST | `/refresh` | 重新探测 Penumbra |

### 网页端最小示例

```js
const BASE = 'http://127.0.0.1:42100';
const TOKEN = localStorage.getItem('modbridge_token');   // 在插件窗口里复制一次

// 1) 探活（不需要 token，可用来判断插件有没有开 + 拿端口）
const ping = await (await fetch(BASE + '/ping')).json();

// 2) 安装
const { jobId } = await (await fetch(BASE + '/install', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-ModBridge-Token': TOKEN },
  body: JSON.stringify({ url: 'https://…/xxx.pmp', enable: true }),
})).json();

// 3) 轮询进度
for (;;) {
  const { job } = await (await fetch(`${BASE}/status?jobId=${jobId}`,
      { headers: { 'X-ModBridge-Token': TOKEN } })).json();
  console.log(job.state, job.percent, job.modName ?? '', job.error ?? '');
  if (['done', 'error', 'cancelled'].includes(job.state)) break;
  await new Promise(r => setTimeout(r, 500));
}
```

> 从 **https 网页**调用 `http://127.0.0.1` 是允许的（本地回环算安全上下文），但 Chrome 会先发
> **Private Network Access 预检**——本插件已经处理：`OPTIONS` 返回 204 并带
> `Access-Control-Allow-Private-Network: true` 和 CORS 头。

## 4.5 本地包（管理器最常用的方式）

管理器里的 Mod 是**本机文件夹**，里面就有 `.pmp`，所以管理器发的是 `localPath` 而不是下载链接：

```json
{ "localPath": "G:\\Games\\FFXIV\\MOD\\202609\\衣服\\SFW\\1.[Arte] Neolithe Bodystocking\\[Arte] Neolithe Bodystocking.pmp",
  "name": "Neolithe Bodystocking", "author": "Arte",
  "coverPath": "G:\\...\\1.[Arte] Neolithe Bodystocking.jpg",
  "dirName": "1.[Arte] Neolithe Bodystocking", "enable": true, "origin": "ModManagerWeb" }
```

- 插件**不会**复制、**更不会**删除你的原文件（卸载/装完只清它自己下载到临时目录的包）；
- `coverPath` 是本机封面图路径，游戏内窗口会显示缩略图；
- 如果某个文件夹里没有 `.pmp`（只有解开的文件），管理器会明确告诉你"要先打包成 .pmp"——那种情况需要另做"复制目录 + AddMod"模式。

## 4.6 预览图（Penumbra 里显示的那张图）

**结论（第三方汉化版实测 + 你的 mod 文件夹实证 + 官方源码三方对照）**：

| 谁 | 认的是什么 |
| --- | --- |
| 用户那个「Penumbra v1.7.2.2 中文界面」（第三方汉化增强版） | **`<mod文件夹>\cover.webp`**（固定文件名） |
| 官方 xivdev/Penumbra 1.7.2.x | **界面根本不画封面**：全仓库搜 `cover`（排除 `discover`）只命中 `recover`；`meta.json` 的 `Image` 字段只被存档读写与 `ModAdapter`(IPC) 使用 |

**决定性证据（用户 A/B 对照，2026-09-22）**：同一个 mod（`[HS] Trigun`）装了两遍，
内容/大小/结构**完全一样**（都 183714 B，124 文件），**唯一区别**是封面文件名：

| | 封面文件 | 结果显示 |
| --- | --- | --- |
| A | `cover.webp` | **有封面** ✓ |
| B | `cover.jpg`（同一份字节，只是名字不同） | **没封面** ✗ |

⇒ 认的就是**文件名 `cover.webp`**。而 `Trigun.pmp` 包根自带的是 `cover.jpg`（内容其实是 WebP），
所以「Penumbra 直接导入 .pmp」装出来的那条没有封面 ✗，而 Heliosphere 装的会写成 `cover.webp` ✓。

其它实证：
- 用户游戏里那两条"有封面"的 mod（`My Boyfriend's Shirt`、`This Old Thing`）都是 **Heliosphere 系**：
  文件夹里有 `heliosphere.json` + **`cover.webp`**（1920×1080 WebP）+ `meta.json`（**没有** `Image` 字段）；
- 描述里**没有**图片代码（纯 Markdown 文本）⇒ "描述带图" 的猜测已排除；
- 本机还发现有的 .pmp 把 WebP 内容命名成 `cover.jpg`（`[Lux Huria] Trigun.pmp`），
  说明 Heliosphere 的封面一律是 **WebP 内容**，文件名不一定规范。

**插件做的事**：安装成功后（或 `POST /fix-cover` 时）
1. 写 `<modDir>\cover.webp` —— 优先用管理器转好的真 WebP（`coverWebpPath`），没有就复制 `coverPath` 的字节；
2. 再写 `<modDir>\cover.<png|jpg>`（兼容"固定名+扩展名"的读法）；
3. 再写 `<modDir>\images\_MetaImage.<ext>`，并把 `meta.json` 的 `Image` 指过去（其它字段原样保留，顺手去掉 BOM）；
4. `ReloadMod` → 让 Penumbra 重新读。

**已经有 `cover.webp` 就跳过**（不动 Heliosphere/作者给的图）；`Image` 已经指向一张存在的图时不改写它，只补 `cover.webp`。

**兜底（管理器没给封面时）**：先在 `.pmp` 旁边找同名图片（`Xxx.pmp` ↔ `Xxx.jpg`）；
找不到就**打开 .pmp 本身**，抽出根目录的 `cover.webp`（Heliosphere 的包都自带）。

**手工给一条补**（把 `<dir>` 换成 Penumbra 里的目录名）：

```
POST /fix-cover   { "dir": "1.[Arte] Neolithe Bodystocking", "coverPath": "G:\\...\\xxx.jpg", "coverWebpPath": "G:\\...\\xxx.webp" }
```

**排查用**：`GET /cover-check?dir=<目录名>`

> **注意**：插件是 DLL，游戏运行中无法热替换 —— 更新插件后**必须重启游戏**才会生效。


## 4.7 自己画封面（不依赖 Heliosphere、不改目录名）

前面查清了：**Penumbra 本体不画封面，那张图是 Heliosphere 插件画的**，而且它只认
"目录名 = `hs-{名字}-{版本}-{Sqids(ShortVariantId)}` + 有 heliosphere.json" 的 mod。
所以只在装 Heliosphere 的包时（见 HelioNaming）才有它画的封面。

为了让**任何 mod** 都能在 Penumbra 面板里显示封面，本插件也挂上了 Penumbra 的绘制事件：

```csharp
Penumbra.Api.IpcSubscribers.PreSettingsTabBarDraw.Subscriber(pi, (directory, width, titleWidth) => …)
```

- 用了它就不必改 mod 目录名 ⇒ 管理器的"这条装没装"（按目录名匹配）不受影响；
- 只画 **png/jpg**（Dalamud 的贴图加载不认 WebP）；管理器会把封面额外转一份真 JPEG
  （`coverDrawPath`）写进 `images\_MetaImage.jpg`，就是给这里用的；
- `cover.webp` 那份仍照写，留给 Heliosphere 插件/别的工具；
- 配置项（配置文件里可直接改）：
  | 键 | 默认 | 说明 |
  | --- | --- | --- |
  | `DrawCovers` | true | 关掉就不自己画 |
  | `CoverSize` | 0.375 | 封面高度 = 面板宽度 × 这个比例 |
  | `SkipHeliosphereMods` | true | 目录名是 Heliosphere 规范的让给它的插件画，免得画两遍 |


## 5. 自测（不需要游戏）

```bat
cd tests\HttpTests
dotnet run -c Release
```

这是把手写 HTTP 层（`HttpMiniServer.cs`）直接编进来跑的**真测试**：24 项断言，覆盖路由分发、
CORS/PNA 预检、UTF-8 与 8 MB 大 body、未知路由 404、handler 抛异常转 500 且服务不崩、
畸形请求、30 并发、停止后拒绝连接。

## 6. 当前状态（诚实清单）

**已验证**
- 编译：**0 警告 0 错误**（.NET 10.0.401 + Dalamud.NET.Sdk 15.0.0 + Penumbra.Api 5.19.2）
- HTTP 层 + 待确认队列：**50/50 自测通过**（24 项 HTTP + 12 项待确认队列 + 14 项来源校验）
- 管理器 ↔ 插件协议：**端到端通过**（用假插件验证 propose/decide/install、错误提示、UI 点击链路）
- 清单：`ModBridge.json` 生成正确（`DalamudApiLevel: 15`）

**还没验证（这台开发机没装 XIVLauncher/Penumbra，无法进游戏）**
- 真实 IPC 调用（`InstallMod / TrySetMod / RedrawAll …`）—— 代码里所有签名都对着官方
  `Penumbra.Api 5.19.2` 的 XML 文档和真实调用方代码核过，但**需要你在游戏里跑一遍**
- 端到端（真实链路）：管理器点安装 → 游戏内确认 → Penumbra 里出现并生效
- `ModAdded` 事件的到达时机（代码里同时做了列表差集 + 目录 mtime 兜底，三条路任一命中即算成功）

**还没做（按需再加）**
- 批量/队列 UI、安装历史持久化
- HTTPS / 证书（本地回环用不上）
- 白名单域名在 UI 里可视化编辑（现在是一个开关 + 内置列表）
- Penumbra 更多能力：预设（ApplyPreset）、临时 mod（TemporaryApi）、设置项（TrySetModSettings）

## 7. 排错

| 现象 | 原因 / 处理 |
|---|---|
| `/ping` 通，其它接口 401 | token 没带或不对：加 `X-ModBridge-Token` 头，值在插件窗口复制 |
| 网页 fetch 报 CORS 错 | 确认请求 URL 是 `http://127.0.0.1:<端口>`（不是 `localhost`/`0.0.0.0`）；`OPTIONS` 应该返回 204 |
| `Penumbra 未连接` | 没装 Penumbra / 还没加载完（用窗口里的「重新探测」）/ Penumbra 版本太老（需要 API major ≥ 5… 实际以 `ApiVersion` 为准） |
| 下载 403 | 站点挡外链：在窗口里改「下载 Referer」，或先在浏览器里下好再用本地文件方式 |
| 装完 Penumbra 里没有 | 打开 Penumbra 看它自己的日志；可能是包格式不对（只认 `.pmp/.pcp/.ttmp/.ttmp2`）或包损坏 |
| 端口被占 | 窗口里改端口后点「启动」；插件会自动用后面 20 个端口里第一个可用的 |
| 同一路径 2 秒内重复安装没反应 | Penumbra 对同一路径 5 秒内重复提交会去重；本插件每次都用新的临时文件名，手动调 API 时注意这点 |
