using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace ModBridge.Http;

/// <summary>
/// 决定「这次安装该往哪个 mod 目录里写东西」。
///
/// 背景（2026-09 主人在游戏里重装后仍然没图）：mod 已经存在时再装一次，Penumbra
/// **不会新增目录** → 老逻辑只等"新目录出现"，等不到就超时退出，
/// **后面的封面步骤全都没执行** → 现场表现就是"重装了还是没有图"。
/// 所以：等不到新目录时，按目录名提示 / 包内 meta.json 的 Name 找回已存在的那个，继续干活。
/// </summary>
public static class InstallTarget
{
    /// <summary>名字规范化：去 [作者]、开头序号、hs- 前缀、非字母数字，统一小写（容错比对用）。</summary>
    public static string Norm(string? s)
    {
        if (string.IsNullOrWhiteSpace(s))
            return string.Empty;
        var t = s.Trim().ToLowerInvariant();
        t = Regex.Replace(t, @"^\[[^\]]*\]\s*", "");
        t = Regex.Replace(t, @"^\d+[.\-_]\s*", "");
        if (t.StartsWith("hs-", StringComparison.Ordinal))
            t = t[3..];
        t = Regex.Replace(t, @"[^a-z0-9\u4e00-\u9fff]+", "");
        return t;
    }

    /// <summary>包（.pmp/.zip）内 meta.json 的 Name（Penumbra 用它当目录名/显示名）。读不到返回 null。</summary>
    public static string? PackageMetaName(string? packagePath)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(packagePath) || !File.Exists(packagePath))
                return null;
            using var z = ZipFile.OpenRead(packagePath);
            var e = z.Entries.FirstOrDefault(x =>
                x.FullName.Replace('\\', '/').Equals("meta.json", StringComparison.OrdinalIgnoreCase));
            if (e is null)
                return null;
            using var s = e.Open();
            using var r = new StreamReader(s, Encoding.UTF8);
            if (JsonNode.Parse(r.ReadToEnd()) is JsonObject o)
                return o["Name"]?.GetValue<string>();
            return null;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// 从「Penumbra 已装列表」（dir → 显示名）里挑出这次装的是哪一条。
    /// 顺序：① 目录名提示完全一致 ② 包内 Name 完全一致 ③ 规范化后一致。
    /// </summary>
    public static string? PickExisting(string? wantDirName, string? packageName,
                                       IReadOnlyDictionary<string, string>? mods, string? packagePath = null)
    {
        if (mods is null || mods.Count == 0)
            return null;
        if (!string.IsNullOrWhiteSpace(wantDirName) && mods.ContainsKey(wantDirName!))
            return wantDirName;

        var pkg = string.IsNullOrWhiteSpace(packageName) ? PackageMetaName(packagePath) : packageName;
        if (!string.IsNullOrWhiteSpace(pkg))
        {
            foreach (var kv in mods)
                if (string.Equals(kv.Value, pkg, StringComparison.OrdinalIgnoreCase))
                    return kv.Key;
        }

        var wantN = Norm(wantDirName);
        var pkgN = Norm(pkg);
        foreach (var kv in mods)
        {
            var a = Norm(kv.Key);
            var b = Norm(kv.Value);
            if (wantN.Length > 0 && (a == wantN || b == wantN))
                return kv.Key;
            if (pkgN.Length > 0 && (a == pkgN || b == pkgN))
                return kv.Key;
        }
        return null;
    }
}
