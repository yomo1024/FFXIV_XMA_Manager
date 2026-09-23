using System;
using System.Collections.Generic;
using System.IO;
using System.Numerics;
using Dalamud.Bindings.ImGui;
using Dalamud.Interface.Textures;
using Dalamud.Interface.Textures.TextureWraps;
using Dalamud.Plugin.Services;
using ModBridge.Http;
using Penumbra.Api.IpcSubscribers;

namespace ModBridge;

/// <summary>
/// 在 Penumbra 的 mod 面板里画封面。
///
/// 做法：挂 Penumbra 给的 <c>PreSettingsTabBarDraw(string directory, float width, float titleWidth)</c>
/// IPC 事件（Heliosphere 插件用的就是同一个），在它的设置页上方画一张图。
/// 这样**不必**依赖 Heliosphere、也**不必**改 mod 目录名 ——
/// 管理器的"这条 mod 装没装"判断（按目录名匹配）完全不受影响。
///
/// 只画自己能解码的格式（png/jpg，见 <see cref="CoverLocator"/>）；
/// 目录名是 Heliosphere 规范（hs-… + heliosphere.json）的 mod 默认让给它的插件画。
/// </summary>
public sealed class PenumbraCoverDrawer : IDisposable
{
    private readonly Plugin _plugin;
    private readonly ITextureProvider _textures;
    private readonly IPluginLog _log;

    private IDisposable? _subscription;

    private readonly Dictionary<string, ISharedImmediateTexture?> _cache = new(StringComparer.OrdinalIgnoreCase);
    private readonly LinkedList<string> _order = [];

    private const int MaxCache = 48;

    public bool Active => _subscription is not null;

    public PenumbraCoverDrawer(Plugin plugin, ITextureProvider textures, IPluginLog log)
    {
        _plugin   = plugin;
        _textures = textures;
        _log      = log;

        try
        {
            _subscription = PreSettingsTabBarDraw.Subscriber(Plugin.PluginInterface, OnDraw);
            _log.Information("[ModBridge] 已挂上 Penumbra 的封面绘制事件（会在 mod 面板里自己画封面）");
        }
        catch (Exception e)
        {
            _log.Warning($"[ModBridge] 挂 Penumbra 封面绘制事件失败（不会自己画封面）：{e.Message}");
        }
    }

    private void OnDraw(string directory, float width, float titleWidth)
    {
        try
        {
            var cfg = _plugin.Configuration;
            if (!cfg.DrawCovers || width <= 0 || string.IsNullOrWhiteSpace(directory))
                return;

            var modDir = Path.Combine(_plugin.Bridge.ModDirectory, directory);
            if (!Directory.Exists(modDir))
                return;

            if (cfg.SkipHeliosphereMods && CoverLocator.IsHeliosphereMod(directory, modDir))
                return;

            var path = CoverLocator.FindDrawable(modDir);
            if (path is null)
                return;

            var wrap = Get(path);
            if (wrap is null || wrap.Height == 0)
                return;

            var maxHeight = width * (float)Math.Clamp(cfg.CoverSize, 0.1, 1.0);
            var aspect    = (float)wrap.Width / wrap.Height;
            var drawWidth = width;
            var drawHeight = drawWidth / aspect;
            if (drawHeight > maxHeight)
            {
                drawHeight = maxHeight;
                drawWidth  = drawHeight * aspect;
            }

            ImGui.SetCursorPosX(ImGui.GetCursorPosX() + Math.Max(0f, (width - drawWidth) / 2f));
            ImGui.Image(wrap.Handle, new Vector2(drawWidth, drawHeight));
            ImGui.Spacing();
        }
        catch (Exception e)
        {
            // 绘制回调里绝不能把异常抛回 Penumbra
            _log.Warning($"[ModBridge] 画封面出错（{directory}）：{e.Message}");
        }
    }

    /// <summary>按"路径 + 修改时间"缓存，文件换了会自动重新加载。</summary>
    private IDalamudTextureWrap? Get(string path)
    {
        string key;
        try
        {
            key = path + "|" + File.GetLastWriteTimeUtc(path).Ticks;
        }
        catch
        {
            key = path;
        }

        if (_cache.TryGetValue(key, out var cached))
            return cached?.GetWrapOrDefault();

        ISharedImmediateTexture? tex = null;
        try
        {
            tex = _textures.GetFromFile(path);
        }
        catch (Exception e)
        {
            _log.Warning($"[ModBridge] 封面读取失败 {Path.GetFileName(path)}：{e.Message}");
        }

        _cache[key] = tex;
        _order.AddLast(key);
        while (_order.Count > MaxCache)
        {
            var oldest = _order.First!.Value;
            _order.RemoveFirst();
            _cache.Remove(oldest);
        }

        return tex?.GetWrapOrDefault();
    }

    public void Dispose()
    {
        try
        {
            _subscription?.Dispose();
        }
        catch
        {
            // 忽略
        }

        _subscription = null;
        _cache.Clear();
        _order.Clear();
    }
}
