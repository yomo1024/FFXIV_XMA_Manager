using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using Dalamud.Plugin.Services;
using ModBridge.Requests;

namespace ModBridge.Http;

/// <summary>
/// 路由。除 /ping 外都需要 X-ModBridge-Token（或 ?token=）。
/// 网页(https) → 127.0.0.1 会走 CORS + Private Network Access 预检，CORS 头在 HttpMiniServer 里统一加，
/// OPTIONS 预检也在那一层直接 204。
/// </summary>
public sealed class ApiRouter
{
    private readonly PenumbraBridge _bridge;
    private readonly JobManager _jobs;
    private readonly RequestStore _requests;
    private readonly Configuration _config;
    private readonly HttpMiniServer _server;
    private readonly IPluginLog _log;
    private readonly string _version;

    /// <summary>收到新的"待确认安装"时触发（插件用它弹提示 + 自动开窗）。</summary>
    public event Action<InstallRequest>? NewRequest;

    public ApiRouter(PenumbraBridge bridge, JobManager jobs, RequestStore requests, Configuration config,
                     HttpMiniServer server, IPluginLog log, string version)
    {
        _bridge = bridge;
        _jobs = jobs;
        _requests = requests;
        _config = config;
        _server = server;
        _log = log;
        _version = version;
    }

    public HttpResponse Handle(HttpRequest req)
    {
        var path = req.Path.TrimEnd('/');
        if (path.Length == 0)
            path = "/";

        // /ping 不需要 token（管理器用它做"插件是否在跑"的探测），也不泄露敏感信息
        if (path == "/ping" && req.Method == "GET")
            return Ping();

        if (!TokenOk(req))
            return Err(401, "token 不对或没带（请在插件窗口里复制 token）");

        try
        {
            return (req.Method, path) switch
            {
                ("GET", "/ping") => Ping(),
                ("GET", "/mods") => Mods(),
                ("GET", "/collections") => Collections(),
                ("GET", "/status") => Status(req),
                ("GET", "/requests") => Requests(),
                ("GET", "/help") => Help(),
                ("GET", "/cover-check") => CoverCheck(req),

                ("POST", "/propose") => Propose(req),
                ("POST", "/decide") => Decide(req),
                ("POST", "/install") => Install(req),
                ("POST", "/cancel") => Cancel(req),
                ("POST", "/enable") => Enable(req),
                ("POST", "/priority") => Priority(req),
                ("POST", "/redraw") => Redraw(),
                ("POST", "/reveal") => Reveal(req),
                ("POST", "/fix-cover") => FixCover(req),
                ("POST", "/refresh") => Refresh(),

                _ => Err(404, "没有这个接口"),
            };
        }
        catch (JsonException e)
        {
            return Err(400, "JSON 解析失败：" + e.Message);
        }
        catch (Exception e)
        {
            _log.Warning($"[ModBridge] {req.Method} {req.Path} 出错: {e}");
            return Err(500, e.Message);
        }
    }

    /// <summary>统一的错误返回：走 JSON 序列化，避免手拼字符串踩转义坑。</summary>
    private static HttpResponse Err(int status, string message)
        => HttpResponse.Json(JsonSerializer.Serialize(new { ok = false, error = message }), status);

    private bool TokenOk(HttpRequest req)
    {
        var given = req.Header("X-ModBridge-Token")
                    ?? (req.Query.TryGetValue("token", out var t) ? t : null);
        if (string.IsNullOrEmpty(_config.Token))
            return false;
        return string.Equals(given, _config.Token, StringComparison.Ordinal);
    }

    // ---------------------------------------------------------------- 状态

    private HttpResponse Ping()
    {
        var mods = _bridge.Available ? _bridge.Mods().Count : 0;
        return HttpResponse.Json(JsonSerializer.Serialize(new
        {
            ok = true,
            plugin = "ModBridge",
            version = _version,
            features = Plugin.Features,
            httpPort = _server.Port,
            needsToken = true,
            penumbra = new
            {
                available = _bridge.Available,
                apiMajor = _bridge.ApiMajor,
                apiMinor = _bridge.ApiMinor,
                modDirectory = _bridge.ModDirectory,
                modCount = mods,
            },
        }));
    }

    private HttpResponse Mods()
    {
        var mods = _bridge.Mods().Select(kv => new { dir = kv.Key, name = kv.Value }).ToArray();
        return HttpResponse.Json(JsonSerializer.Serialize(new { ok = true, count = mods.Length, mods }));
    }

    private HttpResponse Collections()
    {
        var cols = _bridge.Collections().Select(c => new { id = c.Id.ToString(), name = c.Name }).ToArray();
        var yours = _bridge.YourCollection();
        return HttpResponse.Json(JsonSerializer.Serialize(new
        {
            ok = true,
            collections = cols,
            yours = yours is null ? null : new { id = yours.Value.Id.ToString(), name = yours.Value.Name },
        }));
    }

    private HttpResponse Status(HttpRequest req)
    {
        if (req.Query.TryGetValue("jobId", out var id) && !string.IsNullOrEmpty(id))
        {
            var j = _jobs.Get(id);
            if (j is null)
                return Err(404, "没有这个任务");
            return HttpResponse.Json(JsonSerializer.Serialize(new { ok = true, job = j.ToJson() }));
        }

        var all = _jobs.Snapshot().Take(20).Select(j => j.ToJson()).ToArray();
        return HttpResponse.Json(JsonSerializer.Serialize(new { ok = true, jobs = all }));
    }

    // ---------------------------------------------------------------- 两段式：待确认 → 游戏内确认 → 安装

    private HttpResponse Propose(HttpRequest req)
    {
        var body = Parse(req);
        var (source, isLocal, err) = SourceResolver.Resolve(body, _config.AllowAnyUrl);
        if (source is null)
            return Err(400, err ?? "缺少 url 或 localPath");

        var name = SourceResolver.Get(body, "name");
        var request = new InstallRequest
        {
            Name = string.IsNullOrWhiteSpace(name) ? System.IO.Path.GetFileNameWithoutExtension(source) : name.Trim(),
            Author = SourceResolver.Get(body, "author"),
            Description = SourceResolver.Get(body, "description"),
            Source = source,
            IsLocal = isLocal,
            CoverPath = SourceResolver.Get(body, "coverPath") ?? SourceResolver.Get(body, "coverImage"),
            CoverWebpPath = SourceResolver.Get(body, "coverWebpPath") ?? SourceResolver.Get(body, "coverWebp"),
            CoverDrawPath = SourceResolver.Get(body, "coverDrawPath") ?? SourceResolver.Get(body, "coverDraw"),
            DirName = SourceResolver.Get(body, "dirName") ?? SourceResolver.Get(body, "directory"),
            Enable = SourceResolver.GetBool(body, "enable") ?? _config.EnableOnInstall,
            Priority = SourceResolver.GetInt(body, "priority"),
            Origin = SourceResolver.Get(body, "origin") ?? "web",
        };

        var added = _requests.Add(request);
        if (added is null)
            return Err(400, "待确认队列满了（最多 20 条），先在游戏里处理掉一些");

        NewRequest?.Invoke(added);
        _log.Information($"[ModBridge] 收到待确认安装：{added.Name} ← {added.Origin}（{added.Source}）");
        return HttpResponse.Json(JsonSerializer.Serialize(new
        {
            ok = true,
            requestId = added.Id,
            state = "pending",
            message = "已送到游戏里，请在游戏内窗口点「确认安装」",
            poll = "/requests",
        }));
    }

    private HttpResponse Requests()
    {
        var pending = _requests.Pending().Select(r => r.ToJson()).ToArray();
        var recent = _requests.All().Take(20).Select(r => r.ToJson()).ToArray();
        return HttpResponse.Json(JsonSerializer.Serialize(new
        {
            ok = true,
            pendingCount = pending.Length,
            pending,
            recent,
        }));
    }

    private HttpResponse Decide(HttpRequest req)
    {
        var body = Parse(req);
        var id = SourceResolver.Get(body, "requestId") ?? SourceResolver.Get(body, "id")
                 ?? (req.Query.TryGetValue("requestId", out var q) ? q : null);
        if (string.IsNullOrEmpty(id))
            return Err(400, "缺少 requestId");

        var approve = SourceResolver.GetBool(body, "approve") ?? SourceResolver.GetBool(body, "confirm") ?? true;
        var request = _requests.Decide(id, approve);
        if (request is null)
            return Err(404, "没有这条待确认请求（可能已经处理过）");

        if (!approve)
            return HttpResponse.Json(JsonSerializer.Serialize(new { ok = true, state = "rejected" }));

        var job = _jobs.Start(request.Source, request.IsLocal, request.DirName, request.Enable,
                              request.Priority, request.CoverPath, request.CoverWebpPath, request.CoverDrawPath);
        _requests.MarkApproved(request.Id, job.Id);
        return HttpResponse.Json(JsonSerializer.Serialize(new
        {
            ok = true,
            state = "approved",
            jobId = job.Id,
            poll = $"/status?jobId={job.Id}",
        }));
    }

    // ---------------------------------------------------------------- 直接装 / 其它

    private HttpResponse Install(HttpRequest req)
    {
        var body = Parse(req);
        var (source, isLocal, err) = SourceResolver.Resolve(body, _config.AllowAnyUrl);
        if (source is null)
            return Err(400, err ?? "缺少 url 或 localPath");

        var dirName = SourceResolver.Get(body, "dirName") ?? SourceResolver.Get(body, "directory");
        var enable = SourceResolver.GetBool(body, "enable") ?? _config.EnableOnInstall;
        var priority = SourceResolver.GetInt(body, "priority");

        var cover = SourceResolver.Get(body, "coverPath") ?? SourceResolver.Get(body, "coverImage");
        var coverWebp = SourceResolver.Get(body, "coverWebpPath") ?? SourceResolver.Get(body, "coverWebp");
        var coverDraw = SourceResolver.Get(body, "coverDrawPath") ?? SourceResolver.Get(body, "coverDraw");
        var job = _jobs.Start(source, isLocal, dirName, enable, priority, cover, coverWebp, coverDraw);
        return HttpResponse.Json(JsonSerializer.Serialize(new
        {
            ok = true,
            jobId = job.Id,
            state = job.State.ToString().ToLowerInvariant(),
            poll = $"/status?jobId={job.Id}",
        }));
    }

    private HttpResponse Cancel(HttpRequest req)
    {
        var id = SourceResolver.Get(Parse(req), "jobId")
                 ?? (req.Query.TryGetValue("jobId", out var q) ? q : null);
        if (string.IsNullOrEmpty(id))
            return Err(400, "缺少 jobId");
        var ok = _jobs.Cancel(id);
        return HttpResponse.Json(JsonSerializer.Serialize(new { ok, cancelled = ok }));
    }

    private HttpResponse Enable(HttpRequest req)
    {
        var body = Parse(req);
        var dir = SourceResolver.Get(body, "dir") ?? SourceResolver.Get(body, "modDir");
        var name = SourceResolver.Get(body, "name") ?? SourceResolver.Get(body, "modName") ?? "";
        var on = SourceResolver.GetBool(body, "enabled") ?? SourceResolver.GetBool(body, "enable") ?? true;
        if (string.IsNullOrEmpty(dir))
            return Err(400, "缺少 dir");

        Guid col;
        var yours = _bridge.YourCollection();
        if (Guid.TryParse(SourceResolver.Get(body, "collectionId"), out var parsed))
            col = parsed;
        else if (yours is not null)
            col = yours.Value.Id;
        else
            return Err(400, "没找到当前集合，请显式传 collectionId");

        var res = _bridge.SetEnabled(col, dir, on, name);
        _bridge.Redraw();
        return HttpResponse.Json(JsonSerializer.Serialize(new { ok = res == "Success", penumbra = res }));
    }

    private HttpResponse Priority(HttpRequest req)
    {
        var body = Parse(req);
        var dir = SourceResolver.Get(body, "dir") ?? SourceResolver.Get(body, "modDir");
        var name = SourceResolver.Get(body, "name") ?? SourceResolver.Get(body, "modName") ?? "";
        var pr = SourceResolver.GetInt(body, "priority");
        if (string.IsNullOrEmpty(dir) || pr is null)
            return Err(400, "需要 dir 与 priority");

        Guid col;
        var yours = _bridge.YourCollection();
        if (Guid.TryParse(SourceResolver.Get(body, "collectionId"), out var parsed))
            col = parsed;
        else if (yours is not null)
            col = yours.Value.Id;
        else
            return Err(400, "没找到当前集合");

        var res = _bridge.SetPriority(col, dir, pr.Value, name);
        _bridge.Redraw();
        return HttpResponse.Json(JsonSerializer.Serialize(new { ok = res == "Success", penumbra = res }));
    }

    /// <summary>给已经在 Penumbra 里的某条 mod 补/换预览图（按目录名找）。
    /// body: {dir, coverPath, coverWebpPath?} —— dir 是 Penumbra 里的目录名，coverPath 是本机图片。</summary>
    private HttpResponse FixCover(HttpRequest req)
    {
        var body = Parse(req);
        var dir = SourceResolver.Get(body, "dir") ?? SourceResolver.Get(body, "modDir");
        var cover = SourceResolver.Get(body, "coverPath") ?? SourceResolver.Get(body, "cover");
        var coverWebp = SourceResolver.Get(body, "coverWebpPath") ?? SourceResolver.Get(body, "coverWebp");
        var coverDraw = SourceResolver.Get(body, "coverDrawPath") ?? SourceResolver.Get(body, "coverDraw");
        if (string.IsNullOrEmpty(dir))
            return Err(400, "缺少 dir（Penumbra 里的 Mod 目录名）");

        var rootDir = _bridge.ModDirectory;
        if (string.IsNullOrEmpty(rootDir))
            return Err(400, "Penumbra 未就绪（先点「重新探测 Penumbra」），读不到 mod 目录");

        var abs = System.IO.Path.Combine(rootDir, dir);
        var r = CoverWriter.Apply(abs, cover, coverWebp, coverDraw);
        if (r.Ok)
        {
            _bridge.Reload(dir, "");
            _log.Information($"[ModBridge] 预览图已写入 {dir}：{r.CoverFile ?? r.RelPath}");
        }
        else if (r.Skipped)
        {
            _log.Information($"[ModBridge] {dir} 本来就有预览图（{r.CoverFile ?? r.RelPath}），不动");
        }
        else
        {
            _log.Warning($"[ModBridge] {dir} 预览图失败：{r.Error}");
        }

        return HttpResponse.Json(JsonSerializer.Serialize(new
        {
            ok = r.Ok,
            status = r.Ok ? "written" : (r.Skipped ? "skipped" : "error"),
            relPath = r.RelPath,
            error = r.Error,
        }));
    }

    /// <summary>查某条 mod 当前的预览图状态：GET /cover-check?dir=xxx
    /// 返回 meta.json 里的 Image 值、cover.webp 在不在、以及 mod 目录里有哪些图片。</summary>
    private HttpResponse CoverCheck(HttpRequest req)
    {
        var dir = req.Query.TryGetValue("dir", out var d) ? d : "";
        var rootDir = _bridge.ModDirectory;
        if (string.IsNullOrEmpty(rootDir))
            return Err(400, "Penumbra 未就绪，读不到 mod 目录");
        if (string.IsNullOrEmpty(dir))
            return Err(400, "缺少 dir（Penumbra 里的 Mod 目录名）");

        var abs = System.IO.Path.Combine(rootDir, dir);
        var metaPath = System.IO.Path.Combine(abs, "meta.json");
        string image = "", imageAbs = "";
        bool metaExists = System.IO.File.Exists(metaPath), imageExists = false;
        string? error = null;

        if (metaExists)
        {
            try
            {
                var obj = JsonNode.Parse(System.IO.File.ReadAllText(metaPath)) as JsonObject;
                image = obj?["Image"]?.GetValue<string>() ?? "";
                if (!string.IsNullOrWhiteSpace(image))
                {
                    imageAbs = System.IO.Path.Combine(
                        abs, image.Replace('\\', System.IO.Path.DirectorySeparatorChar)
                                  .Replace('/', System.IO.Path.DirectorySeparatorChar));
                    imageExists = System.IO.File.Exists(imageAbs);
                }
            }
            catch (Exception e) { error = "meta.json 读不了：" + e.Message; }
        }

        var pics = new List<string>();
        try
        {
            if (System.IO.Directory.Exists(abs))
            {
                foreach (var f in System.IO.Directory.EnumerateFiles(abs, "*", SearchOption.AllDirectories))
                {
                    var e2 = System.IO.Path.GetExtension(f).ToLowerInvariant();
                    if (e2 is ".png" or ".jpg" or ".jpeg" or ".webp")
                        pics.Add(System.IO.Path.GetRelativePath(abs, f));
                    if (pics.Count >= 12)
                        break;
                }
            }
        }
        catch { /* 忽略 */ }

        return HttpResponse.Json(JsonSerializer.Serialize(new
        {
            ok = true,
            dir,
            modFolder = abs,
            modFolderExists = System.IO.Directory.Exists(abs),
            metaExists,
            image,
            imageExists,
            hasPreview = imageExists,
            imagesInMod = pics.ToArray(),
            error,
            hint = imageExists
                ? "已就绪：Penumbra 里应该能看到这张图（看不到就重启一次游戏）"
                : (metaExists ? "meta.json 里没有可用的 Image → 用 POST /fix-cover 补一张" : "这个目录里没有 meta.json"),
        }));
    }

    private HttpResponse Redraw()
    {
        _bridge.Redraw();
        return HttpResponse.Json("{\"ok\":true}");
    }

    private HttpResponse Reveal(HttpRequest req)
    {
        var body = Parse(req);
        var dir = SourceResolver.Get(body, "dir") ?? SourceResolver.Get(body, "modDir") ?? "";
        var name = SourceResolver.Get(body, "name") ?? SourceResolver.Get(body, "modName") ?? "";
        var res = _bridge.OpenModsTab(dir, name);
        return HttpResponse.Json(JsonSerializer.Serialize(new { ok = res != "Exception", penumbra = res }));
    }

    private HttpResponse Refresh()
    {
        _bridge.Refresh();
        return Ping();
    }

    private HttpResponse Help()
        => HttpResponse.Json(JsonSerializer.Serialize(new
        {
            ok = true,
            endpoints = new[]
            {
                "GET  /ping                                  插件是否在跑（不需要 token）",
                "GET  /mods                                  Penumbra 里已装的 mod 列表",
                "GET  /collections                           集合列表 + 你当前生效的集合",
                "POST /propose   {url|localPath,name,author?,coverPath?,dirName?,enable?} → {requestId}（送到游戏里等确认）",
                "GET  /requests                              待确认 + 最近处理记录",
                "POST /decide    {requestId,approve}          游戏里确认/拒绝 → 批准则返回 {jobId}",
                "POST /install   {url|localPath,dirName?,enable?,priority?,coverPath?} → {jobId}（跳过确认，直接装）",
                "    说明：coverPath 是本机封面图路径，装完会写进 mod 的 images\\_MetaImage.<ext> 并改写 meta.json 的 Image",
                "GET  /status?jobId=xxx                       任务进度",
                "POST /cancel    {jobId}",
                "POST /enable    {dir,name?,enabled?,collectionId?}",
                "POST /priority  {dir,name?,priority}",
                "POST /redraw",
                "POST /reveal    {dir,name?}                  在 Penumbra 窗口里高亮这条 mod",
                "POST /fix-cover {dir,coverPath,coverWebpPath?,coverDrawPath?} 给已装的 mod 补/换预览图（写 cover.webp + images\\_MetaImage + meta.json 的 Image）",
                "GET  /cover-check?dir=xxx                    查这条 mod 现在有没有预览图（排查用）",
                "POST /refresh                                重新探测 Penumbra",
            },
            auth = "所有接口（除 /ping）都要带 X-ModBridge-Token 头，值在插件窗口里复制",
        }));

    private static JsonElement? Parse(HttpRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.Body))
            return null;
        using var doc = JsonDocument.Parse(req.Body);
        return doc.RootElement.Clone();
    }
}
