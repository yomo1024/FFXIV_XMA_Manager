using System;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.Json.Nodes;

namespace ModBridge.Http;

/// <summary>
/// Heliosphere 的 mod 目录命名规则。
///
/// 来源：**反编译用户机器上的 Heliosphere 插件本体**（heliosphere-plugin.dll 4.10.7.0），
/// 并用用户真实目录名双向验证过（encode(13476)=="gWc2" ↔ hs-…-1.1.0-gWc2；
/// decode("EXXk")==18921 ↔ hs-Trigun […]-1.0.0-EXXk）。
///
/// 它的判定逻辑（Heliosphere/Ui/PenumbraWindowIntegration.cs + PackageState.cs）：
///   · 只扫 **目录名以 "hs-" 开头、且目录里有 heliosphere.json** 的 mod；
///   · 目录名必须能被 HeliosphereMeta.ParseDirectory 解析：按 '-' 切开后
///     第一段 == "hs"，**最后一段**能被 Sqids 解码（= ShortVariantId），倒数第二段当成版本；
///   · 封面文件：优先 &lt;dir&gt;\cover.webp，没有才用 &lt;dir&gt;\cover.jpg；
///   · 满足这些就画封面（受设置 "Show mod image previews in Penumbra" 控制）。
///
/// 目录名格式（HeliosphereMeta.ModDirectoryName）：
///   <c>hs-{Name（非法文件名字符换成 '-'）}-{Version}-{SqidsEncode(ShortVariantId)}</c>
///
/// 而 Penumbra 导入 .pmp 时是用**包内 meta.json 的 Name** 建目录
/// （Penumbra/Import/TexToolsImporter.Archives.cs: CreateModFolder(_baseDirectory, name, …)），
/// 所以这里把包复制一份、只改里面 meta.json 的 Name，就能让装出来的目录名符合规范
/// ——用户的原始包一个字节都不动。
/// </summary>
public static class HelioNaming
{
    /// <summary>Heliosphere 私有的 Sqids 字母表（来自 HeliosphereMeta.SqidsAlphabet）。</summary>
    public const string Alphabet = "PB02vEmaJ7WqrSFZ5ILoQf8tUu9GNhkKRw1H34slVcOdjT6CyeDYAgpiXMxnbz";

    /// <summary>Sqids 构造时会无条件 ConsistentShuffle 一遍字母表。</summary>
    private static readonly char[] Shuffled = SqidsShuffle(Alphabet.ToCharArray());

    private static char[] SqidsShuffle(char[] chars)
    {
        var c = (char[])chars.Clone();
        var num = 0;
        for (var i = c.Length - 1; i > 0; --i)
        {
            var index = (num * i + c[num] + c[i]) % c.Length;
            (c[num], c[index]) = (c[index], c[num]);
            ++num;
        }

        return c;
    }

    private static string ToId(ulong num, char[] alphabet)
    {
        var sb = new StringBuilder();
        do
        {
            sb.Insert(0, alphabet[(int)(num % (ulong)alphabet.Length)]);
            num /= (ulong)alphabet.Length;
        } while (num > 0);

        return sb.ToString();
    }

    /// <summary>Sqids 单值编码（MinLength=0，和我们用到的 ID 不会命中 blocklist）。</summary>
    public static string Encode(uint number)
    {
        var alphabet = Shuffled;
        var num      = 0;
        num += alphabet[number % alphabet.Length] + 0;
        num = (1 + num) % alphabet.Length;

        var sp    = alphabet.Skip(num).Concat(alphabet.Take(num)).ToArray();   // 左旋 num
        var first = sp[0];
        sp = sp.Reverse().ToArray();                                           // 再整体反转
        var sb = new StringBuilder();
        sb.Append(first);
        sb.Append(ToId(number, sp[1..]));
        return sb.ToString();
    }

    /// <summary>与 Heliosphere 一致：把非法文件名字符换成 '-'。</summary>
    public static string Sanitize(string name)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sb      = new StringBuilder(name.Length);
        foreach (var c in name)
            sb.Append(Array.IndexOf(invalid, c) < 0 ? c : '-');

        return sb.ToString();
    }

    public static string DirectoryName(string name, string version, uint shortVariantId)
        => $"hs-{Sanitize(name)}-{version}-{Encode(shortVariantId)}";

    public readonly record struct HelioInfo(string Name, string Version, uint ShortVariantId, int MetaVersion)
    {
        public string DirectoryName => HelioNaming.DirectoryName(Name, Version, ShortVariantId);

        /// <summary>Heliosphere 自己的显示名习惯（设置里的 Penumbra mod title prefix）。</summary>
        public string DisplayName => "[HS] " + Name;
    }

    /// <summary>从 mod 包（.pmp/.zip）里读 heliosphere.json。
    /// 只有写了 ShortVariantId 的（MetaVersion 4）才算得岀 Heliosphere 的规范目录名；
    /// MetaVersion 3 的老包要它联网查，我们算不了，返回 null。</summary>
    public static HelioInfo? FromPackage(string? packagePath)
    {
        if (string.IsNullOrWhiteSpace(packagePath) || !File.Exists(packagePath))
            return null;

        try
        {
            using var zip = ZipFile.OpenRead(packagePath);
            var entry = zip.Entries.FirstOrDefault(e =>
                e.FullName.IndexOf('/') < 0 && e.FullName.IndexOf('\\') < 0
                && e.Name.Equals("heliosphere.json", StringComparison.OrdinalIgnoreCase));
            if (entry is null)
                return null;

            string text;
            using (var s = entry.Open())
            using (var reader = new StreamReader(s, Encoding.UTF8))
                text = reader.ReadToEnd();

            if (JsonNode.Parse(text) is not JsonObject obj)
                return null;

            var name    = obj["Name"]?.GetValue<string>();
            var version = obj["Version"]?.GetValue<string>();
            var metaVer = obj["MetaVersion"]?.GetValue<int>() ?? 0;
            if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(version))
                return null;

            var shortId = obj["ShortVariantId"];
            if (shortId is null)
                return null;

            return new HelioInfo(name, version, shortId.GetValue<uint>(), metaVer);
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// 复制一份包，只把内部 meta.json 的 Name 改成 newName（Penumbra 会用这个 Name 当目录名）。
    /// 返回新包路径；失败返回 null（调用方退回原包，不影响安装）。
    /// </summary>
    public static string? PatchPackageName(string source, string newName)
    {
        try
        {
            var dir  = Path.Combine(Path.GetTempPath(), "ModBridgeHelioPacks");
            Directory.CreateDirectory(dir);
            var dest = Path.Combine(dir, Path.GetFileNameWithoutExtension(source) + "-helio.pmp");
            if (File.Exists(dest))
                File.Delete(dest);

            using (var src = ZipFile.OpenRead(source))
            using (var outStream = File.Create(dest))
            using (var dst = new ZipArchive(outStream, ZipArchiveMode.Create))
            {
                var wroteMeta = false;
                foreach (var entry in src.Entries)
                {
                    var isMeta = entry.FullName.IndexOf('/') < 0 && entry.FullName.IndexOf('\\') < 0
                        && entry.Name.Equals("meta.json", StringComparison.OrdinalIgnoreCase);
                    if (!isMeta)
                    {
                        var copy = dst.CreateEntry(entry.FullName, CompressionLevel.Fastest);
                        using var from = entry.Open();
                        using var to   = copy.Open();
                        from.CopyTo(to);
                        continue;
                    }

                    string json;
                    using (var s = entry.Open())
                    using (var reader = new StreamReader(s, Encoding.UTF8))
                        json = reader.ReadToEnd();

                    var patched = false;
                    try
                    {
                        if (JsonNode.Parse(json) is JsonObject obj)
                        {
                            obj["Name"] = newName;
                            json        = obj.ToJsonString();
                            patched     = true;
                        }
                    }
                    catch
                    {
                        // 解析失败就原样拷贝
                    }

                    var outEntry = dst.CreateEntry(entry.FullName, CompressionLevel.Fastest);
                    using (var w = new StreamWriter(outEntry.Open(), new UTF8Encoding(false)))
                        w.Write(json);
                    wroteMeta = patched || wroteMeta;
                }

                if (!wroteMeta)
                {
                    // 没有可改的 meta.json → 这个包不能靠改名控制目录
                    return null;
                }
            }

            return File.Exists(dest) ? dest : null;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>装完之后，把 mod 的显示名改回好看的样子（只动 meta.json 的 Name，目录名保持规范）。</summary>
    public static bool SetDisplayName(string modFolder, string displayName)
    {
        try
        {
            var metaPath = Path.Combine(modFolder, "meta.json");
            if (!File.Exists(metaPath))
                return false;

            if (JsonNode.Parse(File.ReadAllText(metaPath)) is not JsonObject obj)
                return false;

            obj["Name"] = displayName;
            File.WriteAllText(metaPath, obj.ToJsonString(), new UTF8Encoding(false));
            return true;
        }
        catch
        {
            return false;
        }
    }
}
