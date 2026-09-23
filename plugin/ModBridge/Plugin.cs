using System;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using Dalamud.Game.Command;
using Dalamud.Interface.Windowing;
using Dalamud.IoC;
using Dalamud.Plugin;
using Dalamud.Plugin.Services;
using ModBridge.Http;
using ModBridge.Requests;
using ModBridge.Windows;

namespace ModBridge;

public sealed class Plugin : IDalamudPlugin
{
    public string Name => "Mod Bridge";

    /// <summary>插件版本（取自程序集，csproj 里的 <Version>）。管理器靠它做"版本监控"。</summary>
    public static string PluginVersion => typeof(Plugin).Assembly.GetName().Version?.ToString(3) ?? "0.0.0";

    /// <summary>这个版本具备的能力，管理器用来判断该走哪条路。</summary>
    public static readonly string[] Features =
    [
        "propose",        // 两段式：送到游戏里确认
        "cover.webp",     // 写 mod 根目录 cover.webp（Heliosphere 认这个文件名）
        "coverDraw",      // 自己挂 Penumbra 绘制事件画封面
        "helioNaming",    // 装 Heliosphere 包时用它的规范目录名
        "coverInject",    // ★ 把封面塞进包再交给 Penumbra（0.2.12+）：Penumbra 只接受包文件，
                          //   包内没图 = 装出来没图；旧版只能"装完再写"，那一步不可靠
    ];

    private const string CommandName = "/modbridge";

    [PluginService] internal static IDalamudPluginInterface PluginInterface { get; private set; } = null!;
    [PluginService] internal static ICommandManager CommandManager { get; private set; } = null!;
    [PluginService] internal static IChatGui ChatGui { get; private set; } = null!;
    [PluginService] internal static IFramework Framework { get; private set; } = null!;
    [PluginService] internal static IPluginLog Log { get; private set; } = null!;
    [PluginService] internal static ITextureProvider TextureProvider { get; private set; } = null!;

    public Configuration Configuration { get; }
    public PenumbraBridge Bridge { get; }
    public JobManager Jobs { get; }
    public HttpMiniServer Server { get; }
    public RequestStore Requests { get; }
    public PenumbraCoverDrawer CoverDrawer { get; }

    /// <summary>最近一次"待确认"提示用的计数（窗口里也看得到）。</summary>
    public int PendingCount => Requests.Pending().Count;

    public readonly WindowSystem WindowSystem = new("ModBridge");
    private readonly MainWindow _window;
    private readonly HttpClient _http;

    public Plugin()
    {
        Configuration = PluginInterface.GetPluginConfig() as Configuration ?? new Configuration();

        if (string.IsNullOrEmpty(Configuration.Token))
        {
            Configuration.Token = Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant();
            Configuration.Save();
            Log.Information("[ModBridge] 已生成新的访问 token");
        }

        _http = new HttpClient { Timeout = TimeSpan.FromMinutes(20) };

        Bridge = new PenumbraBridge(PluginInterface, Framework, Log);
        CoverWriter.CleanupInjected();          // 清掉上一次注入留在 %TEMP% 里的包（超过 24h 的）

        var tempDir = Path.Combine(PluginInterface.ConfigDirectory.FullName, "downloads");
        Jobs = new JobManager(_http, Bridge, Configuration, Log, tempDir);

        Requests = new RequestStore();

        ApiRouter router = null!;
        Server = new HttpMiniServer(Configuration.Port, req => router.Handle(req), new PluginLogAdapter(Log));
        router = new ApiRouter(Bridge, Jobs, Requests, Configuration, Server, Log,
                               typeof(Plugin).Assembly.GetName().Version?.ToString(3) ?? "0.1.0");

        // 在 Penumbra 的 mod 面板里自己画封面（不依赖 Heliosphere，也不用改目录名）
        CoverDrawer = new PenumbraCoverDrawer(this, TextureProvider, Log);

        _window = new MainWindow(this);
        WindowSystem.AddWindow(_window);

        // 收到网页送来的"待确认安装"：聊条提醒 + （可选）自动开窗
        router.NewRequest += OnNewRequest;

        CommandManager.AddHandler(CommandName, new CommandInfo(OnCommand)
        {
            HelpMessage = "打开 Mod Bridge 窗口（查看端口 / token / 安装记录）",
        });

        PluginInterface.UiBuilder.Draw += WindowSystem.Draw;
        PluginInterface.UiBuilder.OpenMainUi += ToggleMainUi;
        PluginInterface.UiBuilder.OpenConfigUi += ToggleMainUi;

        if (Configuration.AutoStart)
            StartServer();
        else
            Log.Information("[ModBridge] 配置为不自动启动 HTTP（可在窗口里手动开）");

        ChatGui.Print($"[Mod Bridge] 已加载。用 {CommandName} 打开窗口查看端口和 token。");
    }

    public int StartServer()
    {
        var port = Server.Start(Configuration.Port);
        if (port == 0)
        {
            ChatGui.PrintError("[Mod Bridge] HTTP 起不来：端口都被占用了，换个端口再试。");
            return 0;
        }

        Log.Information($"[ModBridge] 监听 http://127.0.0.1:{port}/  (token 已就绪)");
        return port;
    }

    public void StopServer()
    {
        Server.Stop();
        Log.Information("[ModBridge] HTTP 已停止");
    }

    private void OnNewRequest(InstallRequest r)
    {
        var who = string.IsNullOrWhiteSpace(r.Author) ? "" : $"（{r.Author}）";
        ChatGui.Print($"[Mod Bridge] 收到安装请求：{r.Name}{who} —— 请在窗口里确认。");
        Log.Information($"[ModBridge] 新请求 {r.Id}: {r.Name} ← {(r.IsLocal ? "本地包 " : "")}{r.Source}");
        if (Configuration.AutoOpenOnRequest)
            _window.IsOpen = true;
    }

    private void OnCommand(string command, string args)
        => _window.Toggle();

    public void ToggleMainUi() => _window.Toggle();

    public void Dispose()
    {
        PluginInterface.UiBuilder.Draw -= WindowSystem.Draw;
        PluginInterface.UiBuilder.OpenMainUi -= ToggleMainUi;
        PluginInterface.UiBuilder.OpenConfigUi -= ToggleMainUi;
        CommandManager.RemoveHandler(CommandName);

        CoverDrawer?.Dispose();

        StopServer();
        Jobs.Dispose();
        Bridge.Dispose();
        _http.Dispose();
        WindowSystem.RemoveAllWindows();
    }
}
