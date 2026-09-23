using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Dalamud.Plugin.Services;

namespace ModBridge.Http;

public enum JobState { Queued, Downloading, Installing, Done, Error, Cancelled }

public sealed class InstallJob
{
    public string Id { get; init; } = "";
    public string Url { get; init; } = "";
    /// <summary>本地 .pmp 路径（true 时不下载、也不删原文件）。</summary>
    public bool IsLocal { get; init; }

    /// <summary>要当预览图的本地图片（管理器传的 coverPath）。</summary>
    public string? CoverPath { get; init; }
    /// <summary>管理器转好的真 WebP（可选），写 mod 根目录的 cover.webp 用它。</summary>
    public string? CoverWebpPath { get; init; }
    /// <summary>管理器转好的真 JPEG（可选），写 images\_MetaImage 供插件自己画封面。</summary>
    public string? CoverDrawPath { get; init; }
    /// <summary>预览图处理结果（给界面/网页看）。</summary>
    public string? CoverResult { get; set; }
    public string? WantDirName { get; init; }
    public bool Enable { get; init; }
    public int? Priority { get; init; }
    public string? LocalFile { get; set; }
    public string? FileName { get; set; }

    public JobState State { get; set; } = JobState.Queued;
    public long Downloaded { get; set; }
    public long Total { get; set; }
    public double Percent => Total > 0 ? Math.Round(Downloaded * 100.0 / Total, 1) : 0;
    public string? ModDirName { get; set; }
    public string? ModName { get; set; }
    public string? PenumbraResult { get; set; }
    public string? Error { get; set; }
    public List<string> Steps { get; } = [];
    public DateTime StartedAt { get; } = DateTime.Now;
    public DateTime? FinishedAt { get; set; }
    public CancellationTokenSource Cts { get; } = new();

    public void Step(string s)
    {
        lock (Steps)
        {
            Steps.Add($"{DateTime.Now:HH:mm:ss} {s}");
            if (Steps.Count > 60)
                Steps.RemoveAt(0);
        }
    }

    private string[] StepSnapshot()
    {
        lock (Steps)
            return Steps.ToArray();
    }

    public object ToJson() => new
    {
        id = Id,
        url = Url,
        state = State.ToString().ToLowerInvariant(),
        percent = Percent,
        downloaded = Downloaded,
        total = Total,
        modDir = ModDirName,
        modName = ModName,
        cover = CoverResult,
        penumbra = PenumbraResult,
        error = Error,
        steps = StepSnapshot(),
        startedAt = StartedAt.ToString("HH:mm:ss", CultureInfo.InvariantCulture),
        finishedAt = FinishedAt?.ToString("HH:mm:ss", CultureInfo.InvariantCulture),
        downloadMb = Math.Round(Downloaded / 1048576.0, 1),
        totalMb = Math.Round(Total / 1048576.0, 1),
    };
}

/// <summary>
/// 安装任务管理：下载 → 调 Penumbra 装 → 启用 → 重绘。
/// 注意（来自 Penumbra 的行为）：
///  * InstallMod 只是"入队"，Success ≠ 装好；
///  * 它不返回新建的目录名 —— 目录名要靠 ModAdded 事件或对比 GetModList() 得到；
///  * 同一路径 5 秒内重复提交会被 Penumbra 静默去重，所以每次都用新的临时文件名。
/// </summary>
public sealed class JobManager : IDisposable
{
    private readonly HttpClient _http;
    private readonly PenumbraBridge _bridge;
    private readonly Configuration _config;
    private readonly IPluginLog _log;
    private readonly string _tempDir;
    private readonly object _lock = new();
    private readonly List<InstallJob> _jobs = [];
    private readonly HashSet<string> _pendingFolders = new(StringComparer.OrdinalIgnoreCase);

    public JobManager(HttpClient http, PenumbraBridge bridge, Configuration config, IPluginLog log, string tempDir)
    {
        _http = http;
        _bridge = bridge;
        _config = config;
        _log = log;
        _tempDir = tempDir;
        Directory.CreateDirectory(_tempDir);
        _bridge.ModAdded += OnModAdded;
    }

    // ModAdded 事件里拿到的目录名，可以用来"立刻"知道装到了哪
    private void OnModAdded(string dir)
    {
        lock (_lock)
            _pendingFolders.Add(dir);
    }

    public IReadOnlyList<InstallJob> Snapshot()
    {
        lock (_lock)
            return _jobs.ToList();
    }

    public InstallJob? Get(string id)
    {
        lock (_lock)
            return _jobs.FirstOrDefault(j => j.Id == id);
    }

    public bool Cancel(string id)
    {
        var j = Get(id);
        if (j is null || j.State is JobState.Done or JobState.Error or JobState.Cancelled)
            return false;
        j.Cts.Cancel();
        j.Step("收到取消请求");
        return true;
    }

    public InstallJob Start(string source, bool isLocal, string? dirName, bool enable, int? priority,
                            string? coverPath = null, string? coverWebpPath = null, string? coverDrawPath = null)
    {
        var job = new InstallJob
        {
            Id = Guid.NewGuid().ToString("N")[..12],
            Url = source,
            IsLocal = isLocal,
            CoverPath = coverPath,
            CoverWebpPath = coverWebpPath,
            CoverDrawPath = coverDrawPath,
            WantDirName = dirName,
            Enable = enable,
            Priority = priority,
        };
        lock (_lock)
        {
            _jobs.Insert(0, job);
            while (_jobs.Count > Math.Max(5, _config.MaxHistory))
                _jobs.RemoveAt(_jobs.Count - 1);
        }

        _ = Task.Run(() => RunAsync(job));
        return job;
    }

    private async Task RunAsync(InstallJob job)
    {
        try
        {
            // ---------- 1. 取到本地包：本地路径直接用，URL 就下载 ----------
            string dest;
            if (job.IsLocal)
            {
                dest = job.Url;
                if (!File.Exists(dest))
                    throw new FileNotFoundException($"本地 mod 包不存在：{dest}");
                job.LocalFile = dest;
                job.FileName = Path.GetFileName(dest);
                job.Total = job.Downloaded = new FileInfo(dest).Length;
                job.Step($"使用本地包 {dest}（{job.Total / 1048576.0:F1} MB，不下载）");
            }
            else
            {
                job.State = JobState.Downloading;
                var ext = SafeExtension(job.Url);
                dest = Path.Combine(_tempDir, $"{DateTime.Now:HHmmss}_{job.Id}{ext}");
                job.LocalFile = dest;
                job.FileName = Path.GetFileName(dest);
                job.Step($"开始下载 {job.Url}");

                await DownloadAsync(job.Url, dest, job, job.Cts.Token).ConfigureAwait(false);

                if (job.Cts.IsCancellationRequested)
                {
                    job.State = JobState.Cancelled;
                    job.Step("已取消");
                    return;
                }

                var size = new FileInfo(dest).Length;
                if (size < 1024)
                    throw new IOException($"下载的文件只有 {size} 字节，不像是 mod 包（可能是被站点挡了或链接失效）");
                job.Step($"下载完成：{size / 1048576.0:F1} MB");
            }

            if (job.Cts.IsCancellationRequested)
            {
                job.State = JobState.Cancelled;
                job.Step("已取消");
                return;
            }

            // ---------- 2. 交给 Penumbra ----------
            job.State = JobState.Installing;
            if (!_bridge.Available)
                throw new InvalidOperationException("Penumbra 不可用（没装或还在加载），请稍后重试");

            // Heliosphere 的包：先把目录名做成它的规范形式，否则它的插件不认、不会画封面。
            // 依据是反编译 Heliosphere 插件本体 + 用户真实目录名验证（见 HelioNaming 注释）。
            string? helioDisplayName = null;
            if (_config.UseHeliosphereNaming)
            {
                var info = HelioNaming.FromPackage(dest);
                if (info is { } helio)
                {
                    var want    = helio.DirectoryName;
                    var patched = HelioNaming.PatchPackageName(dest, want);
                    if (patched is not null)
                    {
                        dest             = patched;
                        helioDisplayName = helio.DisplayName;
                        job.Step($"Heliosphere 包：按它的规则把目录名定为 {want}");
                    }
                    else
                    {
                        job.Step("Heliosphere 包：改不了包内 meta.json，按原名安装（Penumbra 里可能不显示封面）");
                    }
                }
            }

            // ★ 把封面塞进包再交给 Penumbra：Penumbra 只接受**包文件**、由它自己解包成目录，
            //   包内没有图 → 解出来就没有图（"装完再写"那一步不可靠，2026-09 主人现场实证过）。
            //   塞进包里则解包时自然带上，不依赖事后写入。
            try
            {
                var injected = CoverWriter.InjectIntoPackage(dest, job.CoverPath, job.CoverWebpPath, job.CoverDrawPath);
                if (injected is not null)
                {
                    job.Step($"封面已塞进包：{Path.GetFileName(injected)}（Penumbra 解包时会一起装上）");
                    dest = injected;
                }
                else
                {
                    job.Step("没有可塞的封面（管理器没给图、包内也没有），先按原包装");
                }
            }
            catch (Exception e)
            {
                job.Step("封面注入失败（继续安装，装完还会再补写一次）：" + e.Message);
            }

            var before = _bridge.Mods();
            job.Step($"Penumbra 已看到 {before.Count} 个 mod，提交安装");
            job.PenumbraResult = _bridge.Install(dest);
            job.Step($"Penumbra.InstallMod → {job.PenumbraResult}");

            // ---------- 3. 等它真正出现 ----------
            var (dir, name) = await WaitForNewModAsync(before, job, TimeSpan.FromSeconds(90))
                .ConfigureAwait(false);
            if (dir is null)
            {
                // ★ 没等到"新"目录 → 多半是**覆盖安装**：同名 mod 已经存在，Penumbra 不会新增目录。
                //   老逻辑在这里直接超时退出 ⇒ 后面的封面步骤全都没执行 ⇒ 重装了还是没图（2026-09 主人现场）。
                //   这里改成：按目录名提示 / 包内 Name 找回已存在的那个，继续把封面写进去。
                var afterInstall = _bridge.Mods();
                var existing = InstallTarget.PickExisting(job.WantDirName, null, afterInstall, dest);
                if (existing is null)
                    throw new TimeoutException(
                        "等了 90 秒没在 Penumbra 里看到这条 mod，按名字也没找到已存在的同名目录"
                        + "（可以打开 Penumbra 看看是不是解包失败）");
                dir = existing;
                name = afterInstall.TryGetValue(existing, out var nm) ? nm : existing;
                job.Step($"Penumbra 没有新增目录（同名已存在 → 覆盖安装）：继续对现有目录 {dir} 写封面");
            }
            job.ModDirName = dir;
            job.ModName = name;
            job.Step($"Penumbra 已装入：{dir}（{name}）");

            // 目录名已经按 Heliosphere 规范了，把显示名改回 [HS] 开头（两者互不影响）
            if (helioDisplayName is not null)
            {
                var absDir = Path.Combine(_bridge.ModDirectory, dir);
                if (HelioNaming.SetDisplayName(absDir, helioDisplayName))
                {
                    job.ModName = helioDisplayName;
                    job.Step($"显示名已设为 {helioDisplayName}");
                }
            }

            // ---------- 3.5 预览图：写进 mod 的 images\ + 改写 meta.json 的 Image ----------
            CoverWriter.Result cr = default;
            // 管理器没给封面时的兜底：在 .pmp 旁边找同名图片（管理器/用户的命名习惯）
            var coverPath = job.CoverPath;
            if (string.IsNullOrWhiteSpace(coverPath))
            {
                coverPath = CoverWriter.GuessFromPackage(job.LocalFile);
                if (!string.IsNullOrWhiteSpace(coverPath))
                    job.Step($"管理器没给封面图，已在包旁边找到同名图片：{Path.GetFileName(coverPath)}");
            }

            if (string.IsNullOrWhiteSpace(coverPath))
            {
                // 兜底 2：打开包本身，把里面的 cover.*（.pmp/.zip 常自带）抽出来当封面。
                // 以前只找「包旁边同名图片」，包里自带的那份没利用 —— 这类包就会「没图、不重绘」。
                try
                {
                    coverPath = CoverWriter.ExtractCoverFromPackage(job.LocalFile ?? "");
                }
                catch { coverPath = null; }
                if (!string.IsNullOrWhiteSpace(coverPath))
                    job.Step($"包内自带封面，已抽出来用：{Path.GetFileName(coverPath)}");
            }

            if (string.IsNullOrWhiteSpace(coverPath))
            {
                // 一定要留痕：否则"没这一步"和"这一步没跑"分不清
                job.CoverResult = "未提供（管理器没发 coverPath，包旁边/包内都没有封面）";
                job.Step("预览图：没有可用的封面（管理器没发 coverPath，包旁边/包内都没有），跳过");
            }
            else
            {
                job.Step($"预览图：使用封面 {coverPath}");
                var modRoot = _bridge.ModDirectory;
                var modAbs = string.IsNullOrEmpty(modRoot) ? "" : Path.Combine(modRoot, dir);
                cr = CoverWriter.Apply(modAbs, coverPath, job.CoverWebpPath, job.CoverDrawPath);
                // Penumbra 刚导入完，meta.json 可能还差一点点才写完 → 重试几次
                for (var attempt = 0; attempt < 8 && cr.Error is not null
                                              && cr.Error.Contains("meta.json"); attempt++)
                {
                    await Task.Delay(400).ConfigureAwait(false);
                    cr = CoverWriter.Apply(modAbs, coverPath, job.CoverWebpPath, job.CoverDrawPath);
                }

                if (cr.Ok)
                {
                    job.CoverResult = "已写入 " + (cr.CoverFile ?? cr.RelPath);
                    job.Step($"预览图已写入：{cr.RelPath}");
                    if (!string.IsNullOrWhiteSpace(cr.Note))
                        job.Step("注意：" + cr.Note);
                    job.Step($"ReloadMod → {_bridge.Reload(dir, name ?? "")}（让 Penumbra 重新读 meta.json）");
                }
                else if (cr.Skipped)
                {
                    job.CoverResult = "沿用包自带：" + (cr.CoverFile ?? cr.RelPath);
                    job.Step($"包里自带预览图（{cr.RelPath}），保持不动");
                }
                else
                {
                    job.CoverResult = "失败：" + cr.Error;
                    job.Step("预览图没写上：" + cr.Error);
                }
            }

            // ---------- 3.6 封面自检：把「游戏里到底有没有图、是不是真 WebP」写进步骤 ----------
            //    失败要可见：否则"没这一步"和"这一步没跑"分不清（主人要求"信息不留空"）
            try
            {
                var absCheck = string.IsNullOrEmpty(_bridge.ModDirectory) ? "" : Path.Combine(_bridge.ModDirectory, dir);
                if (!string.IsNullOrEmpty(absCheck) && Directory.Exists(absCheck))
                {
                    var cvAbs = Path.Combine(absCheck, "cover.webp");
                    var hasCv = File.Exists(cvAbs);
                    var realCv = CoverWriter.IsRealWebp(cvAbs);
                    var draw = CoverLocator.FindDrawable(absCheck);
                    job.Step("封面自检：cover.webp "
                             + (hasCv ? (realCv ? "✓ 是真 WebP" : "✗ 内容是伪装的（不是 WebP，认 cover.webp 的 Penumbra 会解不出来）")
                                      : "✗ 没有")
                             + " ｜ 本插件能画的图：" + (draw is null ? "✗ 没有" : "✓ " + Path.GetFileName(draw)));
                }
            }
            catch { /* 自检失败不影响安装 */ }

            // ---------- 4. 启用 / 优先级 / 重绘 ----------
            if (job.Enable)
            {
                var col = _bridge.YourCollection();
                if (col is null)
                {
                    job.Step("没找到当前集合，跳过启用（可在 Penumbra 里手动开）");
                }
                else
                {
                    job.Step($"在集合「{col.Value.Name}」里启用");
                    job.Step($"TrySetMod → {_bridge.SetEnabled(col.Value.Id, dir, true, name ?? "")}");
                    if (job.Priority is { } pr)
                        job.Step($"TrySetModPriority({pr}) → {_bridge.SetPriority(col.Value.Id, dir, pr, name ?? "")}");
                }
            }

            _bridge.Redraw();
            job.Step("已请求游戏重绘");

            job.State = JobState.Done;
            job.FinishedAt = DateTime.Now;
            job.Step("完成 ✔");

            if (_config.CleanupTempFiles && !job.IsLocal)
            {
                // 注意：只删自己下到临时目录的包，绝不动用户/管理器给的本地原文件
                try { File.Delete(dest); } catch { /* 忽略 */ }
            }
        }
        catch (OperationCanceledException)
        {
            job.State = JobState.Cancelled;
            job.FinishedAt = DateTime.Now;
            job.Step("已取消");
        }
        catch (Exception e)
        {
            job.State = JobState.Error;
            job.Error = e.Message;
            job.FinishedAt = DateTime.Now;
            job.Step("失败：" + e.Message);
            _log.Warning($"[ModBridge] 安装失败 {job.Url}: {e}");
        }
    }

    /// <summary>等新版出现：先用 ModAdded 事件给的目录名，其次对比列表，最后看目录 mtime。</summary>
    private async Task<(string? Dir, string? Name)> WaitForNewModAsync(
        Dictionary<string, string> before, InstallJob job, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (job.Cts.IsCancellationRequested)
                return (null, null);

            lock (_lock)
            {
                var hit = _pendingFolders.FirstOrDefault(d => !before.ContainsKey(d));
                if (hit is not null)
                {
                    _pendingFolders.Remove(hit);
                    var after0 = _bridge.Mods();
                    return (hit, after0.TryGetValue(hit, out var n0) ? n0 : hit);
                }
            }

            var after = _bridge.Mods();
            var added = after.Keys.Where(k => !before.ContainsKey(k)).ToList();
            if (added.Count > 0)
            {
                var d = added[0];
                return (d, after[d]);
            }

            await Task.Delay(400).ConfigureAwait(false);
        }

        // 兜底：万一 Penumbra 覆盖了同名目录（列表没有新键），用 mtime 找刚写过的目录
        try
        {
            var root = _bridge.ModDirectory;
            if (!string.IsNullOrEmpty(root) && Directory.Exists(root))
            {
                var newest = new DirectoryInfo(root).EnumerateDirectories()
                    .OrderByDescending(d => d.LastWriteTimeUtc)
                    .FirstOrDefault();
                if (newest != null && DateTime.UtcNow - newest.LastWriteTimeUtc < TimeSpan.FromMinutes(5))
                {
                    var after = _bridge.Mods();
                    job.Step($"列表没出现新目录，按修改时间推断为 {newest.Name}");
                    return (newest.Name, after.TryGetValue(newest.Name, out var n) ? n : newest.Name);
                }
            }
        }
        catch (Exception e)
        {
            job.Step("兜底探测失败：" + e.Message);
        }

        return (null, null);
    }

    private async Task DownloadAsync(string url, string dest, InstallJob job, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(HttpMethod.Get, url);
        req.Headers.TryAddWithoutValidation("User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0 Safari/537.36");
        if (!string.IsNullOrWhiteSpace(_config.DownloadReferer))
            req.Headers.TryAddWithoutValidation("Referer", _config.DownloadReferer);
        req.Headers.TryAddWithoutValidation("Accept", "*/*");

        using var resp = await _http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct)
            .ConfigureAwait(false);
        if (!resp.IsSuccessStatusCode)
            throw new HttpRequestException($"HTTP {(int)resp.StatusCode} {resp.ReasonPhrase}（站点可能挡外链，试试换个直链或在浏览器里先下一份）");

        job.Total = resp.Content.Headers.ContentLength ?? 0;
        await using var src = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        await using var dst = new FileStream(dest, FileMode.Create, FileAccess.Write, FileShare.None);
        var buf = new byte[128 * 1024];
        var lastReport = DateTime.UtcNow;
        while (true)
        {
            var n = await src.ReadAsync(buf, ct).ConfigureAwait(false);
            if (n <= 0)
                break;
            await dst.WriteAsync(buf.AsMemory(0, n), ct).ConfigureAwait(false);
            job.Downloaded += n;
            if (DateTime.UtcNow - lastReport > TimeSpan.FromMilliseconds(300))
            {
                lastReport = DateTime.UtcNow;
                job.Step($"下载中 {job.Downloaded / 1048576.0:F1} MB"
                         + (job.Total > 0 ? $" / {job.Total / 1048576.0:F1} MB" : ""));
            }
        }
    }

    private static string SafeExtension(string url)
    {
        try
        {
            var p = Uri.TryCreate(url, UriKind.Absolute, out var uri) ? uri.AbsolutePath : url;
            var ext = Path.GetExtension(p).ToLowerInvariant();
            return ext is ".pmp" or ".pcp" or ".ttmp" or ".ttmp2" or ".zip" ? ext : ".pmp";
        }
        catch { return ".pmp"; }
    }

    public void Dispose()
    {
        _bridge.ModAdded -= OnModAdded;
        foreach (var j in Snapshot())
        {
            try { j.Cts.Cancel(); } catch { /* 忽略 */ }
        }
    }
}
