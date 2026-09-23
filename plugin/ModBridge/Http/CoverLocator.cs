using System;
using System.IO;

namespace ModBridge.Http;

/// <summary>
/// 找一个 mod 文件夹里"我们自己能画"的封面文件。
///
/// 为什么挑格式：Dalamud 的贴图加载只认 png/jpg 这类位图，**WebP 不行**
/// （Heliosphere 为了 WebP 自己带了个解码器）。所以：
///   · 优先 images\_MetaImage.png / .jpg —— 这是插件/管理器主动写了进去的（真图，能解码）
///   · 其次根目录的 cover.png / cover.jpg
///   · cover.webp 不在这里（那留给 Heliosphere 插件用）
/// </summary>
public static class CoverLocator
{
    private static readonly string[] DrawableNames =
    [
        "images\\_MetaImage.png", "images\\_MetaImage.jpg", "images\\_MetaImage.jpeg",
        "cover.png", "cover.jpg", "cover.jpeg",
    ];

    /// <summary>返回可以直接喂给贴图加载器的封面路径；没有就 null。</summary>
    public static string? FindDrawable(string modFolder)
    {
        if (string.IsNullOrWhiteSpace(modFolder) || !Directory.Exists(modFolder))
            return null;

        foreach (var rel in DrawableNames)
        {
            var p = Path.Combine(modFolder, rel.Replace('\\', Path.DirectorySeparatorChar));
            if (File.Exists(p))
                return p;
        }

        return null;
    }

    /// <summary>
    /// 是不是 Heliosphere 的 mod：目录名以 "hs-" 开头、且目录里有 heliosphere.json。
    /// 这种默认交给 Heliosphere 插件自己画，免得同一张图被画两遍。
    /// </summary>
    public static bool IsHeliosphereMod(string modFolderName, string modFolder)
    {
        if (string.IsNullOrWhiteSpace(modFolderName)
            || !modFolderName.StartsWith("hs-", StringComparison.OrdinalIgnoreCase))
            return false;

        return File.Exists(Path.Combine(modFolder, "heliosphere.json"));
    }
}
