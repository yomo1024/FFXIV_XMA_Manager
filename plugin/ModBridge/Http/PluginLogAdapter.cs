using Dalamud.Plugin.Services;

namespace ModBridge.Http;

/// <summary>把 Dalamud 的 IPluginLog 适配成 HTTP 层用的 IModBridgeLog。</summary>
public sealed class PluginLogAdapter(IPluginLog log) : IModBridgeLog
{
    public void Info(string message) => log.Information(message);
    public void Warn(string message) => log.Warning(message);
    public void Debug(string message) => log.Debug(message);
    public void Error(string message) => log.Error(message);
}
