using System;
using Dalamud.Configuration;

namespace ModBridge;

[Serializable]
public class Configuration : IPluginConfiguration
{
    public int Version { get; set; } = 1;

    /// <summary>本地 HTTP 监听端口（只绑 127.0.0.1）。被占用时会自动向后顺延。</summary>
    public int Port { get; set; } = 42100;

    /// <summary>鉴权 token：网页请求必须带 X-ModBridge-Token 头（/ping 除外）。</summary>
    public string Token { get; set; } = string.Empty;

    /// <summary>插件加载时自动开启 HTTP 服务。</summary>
    public bool AutoStart { get; set; } = true;

    /// <summary>装完后自动在（当前集合里）启用。</summary>
    public bool EnableOnInstall { get; set; } = true;

    /// <summary>是否允许网页指定任意下载地址（关掉则只接受白名单域名）。</summary>
    public bool AllowAnyUrl { get; set; } = true;

    /// <summary>下载时带的 Referer（有些站点挡外链）。</summary>
    public string DownloadReferer { get; set; } = "https://www.xivmodarchive.com/";

    /// <summary>安装成功后是否删除临时下载文件。</summary>
    public bool CleanupTempFiles { get; set; } = true;

    /// <summary>
    /// 装上 Heliosphere 出的包（.pmp 里有 heliosphere.json）时，把 mod 目录名做成
    /// Heliosphere 的规范形式（hs-名字-版本-Sqids码），这样 Heliosphere 插件才会在
    /// Penumbra 里给它画封面。关掉就按普通方式装。
    /// </summary>
    public bool UseHeliosphereNaming { get; set; } = true;

    /// <summary>在 Penumbra 的 mod 面板里自己画封面（挂 Penumbra 的 PreSettingsTabBarDraw 事件）。</summary>
    public bool DrawCovers { get; set; } = true;

    /// <summary>封面高度 = 面板宽度 × 这个比例（和 Heliosphere 的默认值一样）。</summary>
    public float CoverSize { get; set; } = 0.375f;

    /// <summary>目录名是 Heliosphere 规范（hs-… + heliosphere.json）的 mod 让给 Heliosphere 插件画，免得画两遍。</summary>
    public bool SkipHeliosphereMods { get; set; } = true;

    /// <summary>收到"待确认安装"时自动弹出插件窗口。</summary>
    public bool AutoOpenOnRequest { get; set; } = true;

    /// <summary>最近安装记录条数上限。</summary>
    public int MaxHistory { get; set; } = 50;

    public void Save() => Plugin.PluginInterface.SavePluginConfig(this);
}
