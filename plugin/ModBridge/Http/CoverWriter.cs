using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace ModBridge.Http;

/// <summary>
/// 给已安装的 Mod 补上预览图。
///
/// 结论演进（每一步都有实证，别退回旧结论）：
///   1. 官方 Penumbra（含 1.7.2.x）**界面根本不画 mod 封面**：
///      全仓库搜 "cover"（排除 discover）只命中 recover；Image 字段只被
///      ModSerialization/ModDeserialization 与 ModAdapter(IPC) 使用。
///   2. 用户游戏里那个 "Penumbra v1.7.2.2 + 中文界面" 是**第三方汉化增强版**
///      （官方 tag 只到 1.7.2.0），封面是它自己加的。
///   3. 实测能显示封面的 mod，文件夹里是 **`cover.webp`**（Heliosphere 系：
///      带 heliosphere.json，封面 1920x1080 WebP）；用户反馈"有 cover.jpg 却不显示"。
///      ⇒ 判定：**认的是文件名 `cover.webp`**。
///   4. 本机还发现：有的 .pmp 把 WebP 内容命名成 `cover.jpg`（[Lux Huria] Trigun.pmp），
///      说明 Heliosphere 的封面一律是 WebP 内容，文件名则不一定规范。
///
/// 所以这里写**四份**，谁认哪份都能出图：
///   1) &lt;modDir&gt;\cover.webp              ← 你这个版本认它（最重要）
///   2) &lt;modDir&gt;\cover.&lt;png|jpg&gt;         ← 有人按固定名+扩展名找
///   3) &lt;modDir&gt;\images\_MetaImage.&lt;ext&gt;  ← 官方版/包作者的命名习惯
///   4) meta.json 的 Image 指向 3)          ← 官方版读它并通过 IPC 给别的插件
/// 已经存在 cover.webp 就跳过（不覆盖作者/Heliosphere 的图）。
/// 包（.pmp）里自带封面时也能直接抽出来用——Heliosphere 的包全都带。
/// </summary>
public static class CoverWriter
{
    public const string MetaDir = "images";
    public const string MetaBase = "_MetaImage";
    public const string CoverBase = "cover";
    public const string CoverWebp = "cover.webp";

    private static readonly string[] ImageExts = [".png", ".jpg", ".jpeg", ".webp"];

    public static string MetaRelPath(string ext) => MetaDir + "\\" + MetaBase + ext;

    /// <summary>
    /// 这个文件是不是**真 WebP**（RIFF....WEBP）。
    ///
    /// 用来分辨「作者/Heliosphere 给的真封面」和「早先把 jpg 改名成 cover.webp 留下的假货」：
    /// 假货让认 cover.webp 的那个汉化版 Penumbra 解不出图 —— 看起来就是「游戏里没封面」，
    /// 而且老逻辑「已有 cover.webp 就跳过」会让**之后所有补封面全部失效**（2026-09 主人现场反馈）。
    /// </summary>
    public static bool IsRealWebp(string? path)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
                return false;
            using var fs = File.OpenRead(path);
            var head = new byte[12];
            if (fs.Read(head, 0, 12) < 12)
                return false;
            return head[0] == (byte)'R' && head[1] == (byte)'I' && head[2] == (byte)'F' && head[3] == (byte)'F'
                && head[8] == (byte)'W' && head[9] == (byte)'E' && head[10] == (byte)'B' && head[11] == (byte)'P';
        }
        catch { return false; }
    }

    /// <summary>mod 文件夹里已经有的固定名封面（cover.webp / cover.png / cover.jpg …）。
    /// `cover.webp` **必须内容真是 WebP** 才算（假货不算，得让后面的修复流程能动手）。</summary>
    public static string? ExistingRootCover(string modFolder)
    {
        var webp = Path.Combine(modFolder, CoverWebp);
        if (File.Exists(webp) && IsRealWebp(webp))
            return CoverWebp;
        foreach (var ext in ImageExts)
        {
            if (ext == ".webp") continue;   // ★ 上面已按"内容真是 WebP"判过；这里再按存在判会把假货又算成有封面
            var p = Path.Combine(modFolder, CoverBase + ext);
            if (File.Exists(p))
                return CoverBase + ext;
        }
        return null;
    }

    /// <summary>
    /// 把封面**塞进包里**再交给 Penumbra —— 让图真正落进 mod 目录的可靠做法。
    ///
    /// 为什么必须这样：Penumbra 的 `InstallMod` 只接受**包文件**（.pmp/.zip…，它自己解包成目录），
    /// 包内没有图 → 解出来的目录就没有图。而"装完再往目录里写"那一步会因时机/权限/占位等原因失败，
    /// 现场表现就是「Penumbra 里那条 mod 一个图都没有」（2026-09 主人拷出目录实证：
    /// 171 个条目、零张图、meta.json 连 Image 字段都没有）。塞进包里则解包时自然带上，不依赖事后写入。
    ///
    /// 返回新包路径（临时目录）；没有可用封面、或包不是 zip 时返回 null（调用方继续用原包，不影响安装）。
    /// </summary>
    public static string? InjectIntoPackage(string source, string? coverPath, string? coverWebpPath = null,
                                            string? coverDrawPath = null)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(source) || !File.Exists(source))
                return null;

            var webpSrc = !string.IsNullOrWhiteSpace(coverWebpPath) && File.Exists(coverWebpPath)
                          && IsRealWebp(coverWebpPath) ? coverWebpPath : null;
            var drawSrc = coverDrawPath is not null && File.Exists(coverDrawPath)
                          && Array.IndexOf(ImageExts, Path.GetExtension(coverDrawPath).ToLowerInvariant()) >= 0
                ? coverDrawPath
                : (coverPath is not null && File.Exists(coverPath) ? coverPath : null);
            if (webpSrc is null && drawSrc is null)
                return null;                                   // 没图就不折腾，原包直接用

            var drawExt = drawSrc is null ? ".jpg" : Path.GetExtension(drawSrc).ToLowerInvariant();
            if (Array.IndexOf(ImageExts, drawExt) < 0)
                drawExt = ".jpg";

            var dir = Path.Combine(Path.GetTempPath(), "ModBridgeCoverPacks");
            Directory.CreateDirectory(dir);
            var ext = Path.GetExtension(source);
            if (string.IsNullOrWhiteSpace(ext))
                ext = ".pmp";
            var dest = Path.Combine(dir, Path.GetFileNameWithoutExtension(source) + "-cover" + ext);
            if (File.Exists(dest))
                File.Delete(dest);

            string? metaJson = null;
            var authorCoverKept = false;      // 作者自带的**真** cover.webp：保留，不覆盖
            using (var src = ZipFile.OpenRead(source))
            using (var outStream = File.Create(dest))
            using (var dst = new ZipArchive(outStream, ZipArchiveMode.Create))
            {
                foreach (var e in src.Entries)
                {
                    var name = e.FullName.Replace('\\', '/');
                    var atRoot = name.IndexOf('/') < 0;
                    var isWebpName = atRoot && e.Name.Equals(CoverWebp, StringComparison.OrdinalIgnoreCase);
                    var isRootCover = atRoot && e.Name.StartsWith(CoverBase + ".", StringComparison.OrdinalIgnoreCase);
                    var isMetaImg = !atRoot && name.StartsWith(MetaDir + "/", StringComparison.OrdinalIgnoreCase)
                        && e.Name.StartsWith(MetaBase + ".", StringComparison.OrdinalIgnoreCase);

                    if (isWebpName)
                    {
                        // 作者给的是真 WebP → 原样留着（跟"装完补写"一个规矩：不覆盖作者的图）
                        var head = new byte[12];
                        using (var s0 = e.Open())
                        {
                            var n0 = s0.Read(head, 0, 12);
                            var real = n0 >= 12 && head[0] == (byte)'R' && head[1] == (byte)'I'
                                && head[2] == (byte)'F' && head[3] == (byte)'F'
                                && head[8] == (byte)'W' && head[9] == (byte)'E' && head[10] == (byte)'B' && head[11] == (byte)'P';
                            if (real)
                            {
                                authorCoverKept = true;
                                var keep = dst.CreateEntry(name, CompressionLevel.Fastest);
                                using var to0 = keep.Open();
                                using var from0 = e.Open();
                                from0.CopyTo(to0);
                                continue;
                            }
                        }
                        continue;                       // 伪 WebP（旧版留下的假货）→ 丢掉，换成我们的
                    }
                    if (isRootCover)
                        continue;                       // 其它 cover.<ext>：由我们统一写 cover.<drawExt>
                    if (isMetaImg)
                        continue;                       // _MetaImage 由我们统一写
                    if (atRoot && e.Name.Equals("meta.json", StringComparison.OrdinalIgnoreCase))
                    {
                        using var s = e.Open();
                        using var reader = new StreamReader(s, Encoding.UTF8);
                        metaJson = reader.ReadToEnd();
                        continue;                                  // meta.json 最后自己写回去
                    }
                    var copy = dst.CreateEntry(name, CompressionLevel.Fastest);
                    using var from = e.Open();
                    using var to = copy.Open();
                    from.CopyTo(to);
                }

                if (webpSrc is not null && !authorCoverKept)
                    AddBytes(dst, CoverWebp, File.ReadAllBytes(webpSrc));
                // 跟"装完补写"一样：cover.<真扩展名> 也放一份（有人按固定名+扩展名找）
                if (drawSrc is not null && drawExt != ".webp")
                    AddBytes(dst, CoverBase + drawExt, File.ReadAllBytes(drawSrc));
                if (drawSrc is not null)
                    AddBytes(dst, MetaDir + "/" + MetaBase + drawExt, File.ReadAllBytes(drawSrc));

                if (metaJson is not null)
                {
                    var text = metaJson;
                    try
                    {
                        if (JsonNode.Parse(metaJson) is JsonObject obj)
                        {
                            obj["Image"] = MetaRelPath(drawExt);   // 官方版/Penumbra 读它
                            text = obj.ToJsonString();
                        }
                    }
                    catch { /* 解析不了就原样写回 */ }
                    var outEntry = dst.CreateEntry("meta.json", CompressionLevel.Fastest);
                    using var w = new StreamWriter(outEntry.Open(), new UTF8Encoding(false));
                    w.Write(text);
                }
            }

            return File.Exists(dest) ? dest : null;
        }
        catch
        {
            return null;      // 注入失败不影响安装，装完还有"事后补写"这一层兜底
        }
    }

    private static void AddBytes(ZipArchive dst, string entryName, byte[] data)
    {
        var e = dst.CreateEntry(entryName, CompressionLevel.Fastest);
        using var s = e.Open();
        s.Write(data, 0, data.Length);
    }

    /// <summary>清理注入出来的临时包（插件启动时调一次，别让 %TEMP% 里堆着）。</summary>
    public static void CleanupInjected(int olderThanHours = 24)
    {
        try
        {
            var dir = Path.Combine(Path.GetTempPath(), "ModBridgeCoverPacks");
            if (!Directory.Exists(dir))
                return;
            var limit = DateTime.UtcNow.AddHours(-olderThanHours);
            foreach (var f in Directory.GetFiles(dir, "*-cover.*"))
            {
                try { if (File.GetLastWriteTimeUtc(f) < limit) File.Delete(f); } catch { /* 忽略 */ }
            }
        }
        catch { /* 忽略 */ }
    }

    /// <summary>
    /// 管理器没给封面时的兜底：先在 .pmp/.zip 旁边找同名图片（`Xxx.pmp` ↔ `Xxx.jpg`），
    /// 找不到就**打开包本身**，从里面抽出根部的 `cover.*`（Heliosphere 的包都自带）。
    /// </summary>
    public static string? GuessFromPackage(string? packagePath)
    {
        if (string.IsNullOrWhiteSpace(packagePath) || !File.Exists(packagePath))
            return null;

        var full = Path.GetFullPath(packagePath);
        var stem = Path.Combine(Path.GetDirectoryName(full) ?? string.Empty,
                                Path.GetFileNameWithoutExtension(full));
        foreach (var ext in ImageExts)
        {
            var cand = stem + ext;
            if (File.Exists(cand))
                return cand;
        }

        return ExtractCoverFromPackage(full);
    }

    /// <summary>从 .pmp/.zip/.pcp 里抽出根部的 cover.*（优先 cover.webp），存到临时目录后返回路径。</summary>
    public static string? ExtractCoverFromPackage(string packagePath)
    {
        try
        {
            using var zip = ZipFile.OpenRead(packagePath);
            var entries = zip.Entries
                .Where(e => e.FullName.IndexOf('/') < 0 && e.FullName.IndexOf('\\') < 0)   // 只看根目录
                .Where(e => e.Name.StartsWith(CoverBase + ".", StringComparison.OrdinalIgnoreCase))
                .OrderBy(e => e.Name.Equals(CoverWebp, StringComparison.OrdinalIgnoreCase) ? 0 : 1)
                .ToArray();
            if (entries.Length == 0)
                return null;

            var pick = entries[0];
            var dir = Path.Combine(Path.GetTempPath(), "ModBridgeCoverCache");
            Directory.CreateDirectory(dir);
            var outPath = Path.Combine(dir, Path.GetFileNameWithoutExtension(packagePath) + "_" + pick.Name);
            if (!File.Exists(outPath) || new FileInfo(outPath).Length != pick.Length)
            {
                using var src = pick.Open();
                using var dst = File.Create(outPath);
                src.CopyTo(dst);
            }
            return File.Exists(outPath) ? outPath : null;
        }
        catch
        {
            return null;   // 包坏了／不是 zip，就当没封面
        }
    }

    /// <summary>结果：Ok=写入成功；Skipped=本来就有图，没动；否则 Error 有原因。</summary>
    public readonly record struct Result(bool Ok, bool Skipped, string? RelPath, string? Error,
                                        string? CoverFile = null, string? Note = null)
    {
        public static Result Fail(string why) => new(false, false, null, why);
        public static Result Skip(string rel, string? coverFile = null) => new(false, true, rel, null, coverFile);
    }

    /// <summary>
    /// modFolder 是这个 Mod 在 Penumbra 里的目录；
    /// coverPath 是要当预览图的本地图片；
    /// coverWebpPath（可选）是已经转好的真 WebP（管理器用 Pillow 转的），有就用它写 cover.webp。
    /// </summary>
    public static Result Apply(string modFolder, string? coverPath, string? coverWebpPath = null, string? coverDrawPath = null)
    {
        if (string.IsNullOrWhiteSpace(modFolder) || !Directory.Exists(modFolder))
            return Result.Fail("Mod 文件夹不存在");

        var metaPath = Path.Combine(modFolder, "meta.json");
        if (!File.Exists(metaPath))
            return Result.Fail("Mod 里没有 meta.json（Penumbra 还没写完？稍后可重试）");

        JsonObject? obj;
        try
        {
            // File.ReadAllText 会自动去掉 UTF-8 BOM（有些包的 meta.json 带 BOM）
            obj = JsonNode.Parse(File.ReadAllText(metaPath)) as JsonObject;
        }
        catch (Exception e)
        {
            return Result.Fail("meta.json 读不了：" + e.Message);
        }

        if (obj is null)
            return Result.Fail("meta.json 不是 JSON 对象");

        // 已经有 cover.webp → 不动（作者/Heliosphere 给的图优先）
        var rootCover = ExistingRootCover(modFolder);
        if (string.Equals(rootCover, CoverWebp, StringComparison.OrdinalIgnoreCase))
            return Result.Skip(CoverWebp, CoverWebp);

        // meta.json 里已经指着的一张存在的图（官方版的机制）
        var existing = obj["Image"]?.GetValue<string>() ?? string.Empty;
        var existingValid = false;
        if (!string.IsNullOrWhiteSpace(existing))
        {
            var existAbs = Path.Combine(modFolder, existing.Replace('\\', Path.DirectorySeparatorChar)
                                                                .Replace('/', Path.DirectorySeparatorChar));
            existingValid = File.Exists(existAbs);
        }

        // 没人给封面，但 mod 文件夹里已经有别的名字的封面
        // （Penumbra 直接导入 .pmp 时会保留包里的 cover.jpg）→ 就用它自己，只要补出 cover.webp
        if (string.IsNullOrWhiteSpace(coverPath) && string.IsNullOrWhiteSpace(coverWebpPath)
            && rootCover is not null
            && !string.Equals(rootCover, CoverWebp, StringComparison.OrdinalIgnoreCase))
            coverPath = Path.Combine(modFolder, rootCover);

        // 管理器给的 coverPath：必须在、且真的是图片（这两条要明确报出来，别被下面的兜底吞掉）
        if (!string.IsNullOrWhiteSpace(coverPath))
        {
            if (!File.Exists(coverPath))
                return Result.Fail("封面文件不存在：" + coverPath);
            var given = Path.GetExtension(coverPath).ToLowerInvariant();
            if (Array.IndexOf(ImageExts, given) < 0)
                return Result.Fail("封面不是图片：" + given);
        }

        // 选一个真实存在的封面源：优先真 WebP，其次原始封面图
        // 只认**真 WebP**：管理器用 Pillow 转的才合格；转不出来时宁可不写 cover.webp（见下）
        var webpSrc = !string.IsNullOrWhiteSpace(coverWebpPath) && File.Exists(coverWebpPath)
                      && IsRealWebp(coverWebpPath) ? coverWebpPath : null;
        var src = webpSrc ?? (string.IsNullOrWhiteSpace(coverPath) ? null : coverPath);

        if (src is null)
            return existingValid
                ? Result.Skip(existing, null)
                : Result.Fail("没有提供封面图（管理器没传 coverPath）");

        var ext = Path.GetExtension(coverPath ?? src).ToLowerInvariant();

        // 1) 根目录封面：**有真 WebP 才写 cover.webp**
        //    以前这里不管三七二十一把拿到的图（可能是 jpg/png）复制成 cover.webp —— 内容不是 WebP，
        //    认 cover.webp 的 Penumbra 解不出来 = 看起来"没图"，而且会让后续补封面被 skip 死锁住。
        string? note = null;
        var webpDest = Path.Combine(modFolder, CoverWebp);
        if (webpSrc is not null)
        {
            try
            {
                File.Copy(webpSrc, webpDest, true);
            }
            catch (Exception e)
            {
                return Result.Fail("写 cover.webp 失败：" + e.Message);
            }
        }
        else
        {
            if (File.Exists(webpDest) && !IsRealWebp(webpDest))
                note = "现有 cover.webp 不是真 WebP（早先 jpg 改名留下的假货），已用 cover." + ext.TrimStart('.')
                       + " + images\\_MetaImage 出图；等管理器转出真 WebP 再自动替换";
        }

        string? rel = existingValid ? existing : null;
        try
        {
            // 2) 兼容"固定名 + 扩展名"的读法
            var rootDest = Path.Combine(modFolder, CoverBase + ext);
            if (coverPath is not null && File.Exists(coverPath) && Array.IndexOf(ImageExts, ext) >= 0 && ext != ".webp"
                && !string.Equals(Path.GetFullPath(coverPath), Path.GetFullPath(rootDest), StringComparison.OrdinalIgnoreCase))
                File.Copy(coverPath, rootDest, true);

            // 3 ~ 4) 官方版那一套：images\_MetaImage.<ext> + meta.json 的 Image（原来没有可用图时才动）
            //   这一份优先用"游戏内插件能解码"的那张（真 JPEG/PNG）——
            //   Dalamud 的贴图加载不认 WebP，所以插件自己画封面时读的就是这里。
            var drawSrc = coverDrawPath is not null && File.Exists(coverDrawPath)
                          && Array.IndexOf(ImageExts, Path.GetExtension(coverDrawPath).ToLowerInvariant()) >= 0
                ? coverDrawPath
                : coverPath is not null && File.Exists(coverPath) ? coverPath : null;
            var drawExt = drawSrc is null ? ".jpg" : Path.GetExtension(drawSrc).ToLowerInvariant();
            if (!existingValid && drawSrc is not null)
            {
                var dir = Path.Combine(modFolder, MetaDir);
                Directory.CreateDirectory(dir);
                foreach (var other in ImageExts)
                {
                    if (other == drawExt)
                        continue;
                    var stale = Path.Combine(dir, MetaBase + other);
                    if (File.Exists(stale))
                    {
                        try { File.Delete(stale); } catch { /* 忽略 */ }
                    }
                }
                File.Copy(drawSrc, Path.Combine(dir, MetaBase + drawExt), true);
                rel = MetaRelPath(drawExt);

                obj["Image"] = rel;
                var json = obj.ToJsonString(new JsonSerializerOptions { WriteIndented = false });
                File.WriteAllText(metaPath, json, new UTF8Encoding(false));   // 写回不带 BOM
            }
        }
        catch (Exception e)
        {
            // cover.webp 已经写好了，这一份失败不算致命
            return new Result(true, false, rel, "附加步骤失败：" + e.Message, CoverWebp, note);
        }

        return new Result(true, false, rel, null, webpSrc is not null ? CoverWebp : (CoverBase + ext), note);
    }
}
