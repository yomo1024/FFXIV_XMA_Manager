using System;
using System.Collections.Generic;
using System.Linq;
using Dalamud.Plugin;
using Dalamud.Plugin.Services;
using Penumbra.Api.Enums;
using Penumbra.Api.IpcSubscribers;

namespace ModBridge;

/// <summary>
/// Penumbra 的 IPC 封装。
/// 所有方法内部都会把调用切到 framework 线程（重复调用时 Dalamud 会直接内联执行），
/// 因此 HTTP 线程也可以安全地直接调。
/// IPC 不是"请求-应答"式保证的：Penumbra 没装/没加载时会抛，这里统一吞掉并返回安全值。
/// </summary>
public sealed class PenumbraBridge : IDisposable
{
    private readonly IDalamudPluginInterface _pi;
    private readonly IFramework _framework;
    private readonly IPluginLog _log;

    private readonly ApiVersion _apiVersion;
    private readonly GetModDirectory _getModDirectory;
    private readonly GetModList _getModList;
    private readonly GetCollection _getCollection;
    private readonly GetCollections _getCollections;
    private readonly InstallMod _installMod;
    private readonly AddMod _addMod;
    private readonly ReloadMod _reloadMod;
    private readonly DeleteMod _deleteMod;
    private readonly TrySetMod _trySetMod;
    private readonly TrySetModPriority _trySetModPriority;
    private readonly RedrawAll _redrawAll;
    private readonly OpenMainWindow _openMainWindow;

    private readonly IDisposable _modAddedSub;
    private readonly IDisposable _initializedSub;
    private readonly IDisposable _disposedSub;

    /// <summary>Penumbra 装好一个 mod 时触发，参数是 mod 的目录名（注意：InstallMod 本身不返回这个）。</summary>
    public event Action<string>? ModAdded;

    public bool Available { get; private set; }
    public int ApiMajor { get; private set; }
    public int ApiMinor { get; private set; }
    public string ModDirectory { get; private set; } = string.Empty;

    public PenumbraBridge(IDalamudPluginInterface pi, IFramework framework, IPluginLog log)
    {
        _pi = pi;
        _framework = framework;
        _log = log;

        _apiVersion = new ApiVersion(pi);
        _getModDirectory = new GetModDirectory(pi);
        _getModList = new GetModList(pi);
        _getCollection = new GetCollection(pi);
        _getCollections = new GetCollections(pi);
        _installMod = new InstallMod(pi);
        _addMod = new AddMod(pi);
        _reloadMod = new ReloadMod(pi);
        _deleteMod = new DeleteMod(pi);
        _trySetMod = new TrySetMod(pi);
        _trySetModPriority = new TrySetModPriority(pi);
        _redrawAll = new RedrawAll(pi);
        _openMainWindow = new OpenMainWindow(pi);

        _modAddedSub = ModAdded_Subscribe();
        // Initialized / Disposed / ModAdded 都是静态类：静态 Subscriber(pi, handler)
        _initializedSub = Penumbra.Api.IpcSubscribers.Initialized.Subscriber(pi, Refresh);
        _disposedSub = Penumbra.Api.IpcSubscribers.Disposed.Subscriber(pi, () => Available = false);
        Refresh();
    }

    private IDisposable ModAdded_Subscribe()
        => Penumbra.Api.IpcSubscribers.ModAdded.Subscriber(_pi, OnModAdded);

    private void OnModAdded(string modDir)
        => ModAdded?.Invoke(modDir);

    /// <summary>重新探测 Penumbra 是否可用（插件启动时、Penumbra 重载后都要调）。</summary>
    public void Refresh()
    {
        RunOnFx(() =>
        {
            try
            {
                var (major, minor) = _apiVersion.Invoke();
                ApiMajor = major;
                ApiMinor = minor;
                Available = major > 0; // 能拿到版本就说明 Penumbra 在
                ModDirectory = Available ? _getModDirectory.Invoke() : string.Empty;
                _log.Information($"[ModBridge] Penumbra API {major}.{minor}, mods 目录: {ModDirectory}");
            }
            catch (Exception e)
            {
                Available = false;
                ModDirectory = string.Empty;
                _log.Debug($"[ModBridge] Penumbra 暂不可用: {e.Message}");
            }
        });
    }

    public Dictionary<string, string> Mods()
    {
        var result = new Dictionary<string, string>();
        RunOnFx(() =>
        {
            try
            {
                foreach (var kv in _getModList.Invoke())
                    result[kv.Key] = kv.Value;
            }
            catch (Exception e) { _log.Debug($"[ModBridge] GetModList 失败: {e.Message}"); }
        });
        return result;
    }

    public List<(Guid Id, string Name)> Collections()
    {
        var list = new List<(Guid, string)>();
        RunOnFx(() =>
        {
            try
            {
                foreach (var kv in _getCollections.Invoke())
                    list.Add((kv.Key, kv.Value));
            }
            catch (Exception e) { _log.Debug($"[ModBridge] GetCollections 失败: {e.Message}"); }
        });
        return list.OrderBy(c => c.Item2, StringComparer.CurrentCultureIgnoreCase).ToList();
    }

    /// <summary>当前角色实际生效的集合（"装完就启用"默认用它）。</summary>
    public (Guid Id, string Name)? YourCollection()
    {
        (Guid, string)? result = null;
        RunOnFx(() =>
        {
            try
            {
                var cur = _getCollection.Invoke(ApiCollectionType.Yourself);
                if (cur != null)
                    result = (cur.Value.Id, cur.Value.Name);
            }
            catch (Exception e) { _log.Debug($"[ModBridge] GetCollection 失败: {e.Message}"); }
        });
        return result;
    }

    public string Install(string packagePath)
        => Invoke(nameof(Install), () => _installMod.Invoke(packagePath).ToString());

    public string Add(string modDirectoryName)
        => Invoke(nameof(Add), () => _addMod.Invoke(modDirectoryName).ToString());

    public string Reload(string modDirectory, string modName)
        => Invoke(nameof(Reload), () => _reloadMod.Invoke(modDirectory, modName).ToString());

    public string Delete(string modDirectory, string modName)
        => Invoke(nameof(Delete), () => _deleteMod.Invoke(modDirectory, modName).ToString());

    public string SetEnabled(Guid collectionId, string modDirectory, bool enabled, string modName)
        => Invoke(nameof(SetEnabled),
                  () => _trySetMod.Invoke(collectionId, modDirectory, enabled, modName).ToString());

    public string SetPriority(Guid collectionId, string modDirectory, int priority, string modName)
        => Invoke(nameof(SetPriority),
                  () => _trySetModPriority.Invoke(collectionId, modDirectory, priority, modName).ToString());

    public void Redraw()
        => Invoke(nameof(Redraw), () =>
        {
            _redrawAll.Invoke(RedrawType.Redraw);
            return "ok";
        });

    public string OpenModsTab(string modDirectory, string modName)
        => Invoke(nameof(OpenModsTab),
                  () => _openMainWindow.Invoke(TabType.Mods, modDirectory, modName).ToString());

    private string Invoke(string what, Func<string> body)
    {
        if (!Available)
            return "PenumbraUnavailable";

        var result = "Exception";
        RunOnFx(() =>
        {
            try { result = body(); }
            catch (Exception e)
            {
                result = "Exception: " + e.Message;
                _log.Warning($"[ModBridge] Penumbra.{what} 调用失败: {e}");
            }
        });
        return result;
    }

    /// <summary>切到 framework 线程执行（已经在该线程时 Dalamud 会直接内联跑）。</summary>
    private void RunOnFx(Action action)
    {
        try { _framework.RunOnFrameworkThread(action); }
        catch (Exception e)
        {
            _log.Debug($"[ModBridge] RunOnFrameworkThread 失败: {e.Message}");
            try { action(); } catch { /* 忽略 */ }
        }
    }

    public void Dispose()
    {
        _modAddedSub.Dispose();
        _initializedSub.Dispose();
        _disposedSub.Dispose();
    }
}
