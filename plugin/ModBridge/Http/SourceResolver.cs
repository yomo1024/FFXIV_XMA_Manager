using System;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace ModBridge.Http;

/// <summary>
/// 解析"要装哪个 mod 包"：本机路径优先，其次 http(s) 直链。
/// 刻意不依赖 Dalamud 类型 —— 这样这段校验逻辑可以脱离游戏单独测。
/// </summary>
public static class SourceResolver
{
    /// <summary>关掉"允许任意地址"时只认这些域名。</summary>
    public static readonly string[] AllowedHosts =
    [
        "xivmodarchive.com", "heliosphere.app", "repo.heliosphere.app",
        "github.com", "objects.githubusercontent.com", "raw.githubusercontent.com",
        "cdn.jsdelivr.net",
    ];

    public static readonly string[] PackageExtensions = [".pmp", ".pcp", ".ttmp", ".ttmp2", ".zip"];

    public static (string? Source, bool IsLocal, string? Error) Resolve(JsonElement? body, bool allowAnyUrl)
    {
        // ---------- 1. 本机路径（管理器最常用）----------
        var local = Get(body, "localPath") ?? Get(body, "path") ?? Get(body, "file");
        if (!string.IsNullOrWhiteSpace(local))
        {
            var raw = local.Trim().Trim('"');
            string full;
            try { full = Path.GetFullPath(raw); }
            catch (Exception e) { return (null, false, "路径不合法：" + e.Message); }

            if (!File.Exists(full))
                return (null, false, "本机找不到这个 mod 包：" + full);

            var ext = Path.GetExtension(full).ToLowerInvariant();
            if (!PackageExtensions.Contains(ext))
                return (null, false, $"不支持的包格式 {ext}（只认 {string.Join("/", PackageExtensions)}）");

            return (full, true, null);
        }

        // ---------- 2. 直链 ----------
        var url = Get(body, "url") ?? Get(body, "link") ?? Get(body, "downloadUrl");
        if (string.IsNullOrWhiteSpace(url))
            return (null, false, "需要 url（直链）或 localPath（本机 mod 包路径）");

        url = url.Trim();
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) ||
            (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
            return (null, false, "url 必须是 http/https 直链");

        if (!allowAnyUrl && !AllowedHosts.Any(h => uri.Host.EndsWith(h, StringComparison.OrdinalIgnoreCase)))
            return (null, false, $"不受信任的域名 {uri.Host}（可在插件里打开「允许任意地址」）");

        return (url, false, null);
    }

    /// <summary>从请求 JSON 里按字段名取值（大小写不敏感）。</summary>
    public static string? Get(JsonElement? el, string name)
    {
        if (el is null || el.Value.ValueKind != JsonValueKind.Object)
            return null;
        foreach (var p in el.Value.EnumerateObject())
        {
            if (!string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase))
                continue;
            return p.Value.ValueKind switch
            {
                JsonValueKind.String => p.Value.GetString(),
                JsonValueKind.Number => p.Value.ToString(),
                JsonValueKind.True => "true",
                JsonValueKind.False => "false",
                _ => null,
            };
        }
        return null;
    }

    public static bool? GetBool(JsonElement? el, string name)
    {
        var s = Get(el, name);
        return s is null ? null : s.Equals("true", StringComparison.OrdinalIgnoreCase) || s == "1";
    }

    public static int? GetInt(JsonElement? el, string name)
        => int.TryParse(Get(el, name), out var v) ? v : null;
}
