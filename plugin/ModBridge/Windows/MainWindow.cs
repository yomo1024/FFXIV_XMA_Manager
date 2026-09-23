using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Numerics;
using Dalamud.Bindings.ImGui;
using Dalamud.Interface.Textures;
using Dalamud.Interface.Utility;
using Dalamud.Interface.Windowing;
using ModBridge.Http;

namespace ModBridge.Windows;

public class MainWindow : Window, IDisposable
{
    private readonly Plugin _plugin;
    private static readonly Vector4 Green = new(0.45f, 0.85f, 0.45f, 1f);
    private static readonly Vector4 Red = new(0.95f, 0.45f, 0.45f, 1f);
    private static readonly Vector4 Dim = new(0.7f, 0.7f, 0.7f, 1f);
    private static readonly Vector4 Yellow = new(0.95f, 0.8f, 0.45f, 1f);

    // 只读展示 token 用
    private string _tokenView = "";
    // 缩略图缓存：路径 → 纹理（避免每帧重新加载）
    private readonly Dictionary<string, ISharedImmediateTexture?> _covers = [];

    public MainWindow(Plugin plugin)
        : base($"Mod Bridge v{Plugin.PluginVersion}###ModBridgeMainWindow", ImGuiWindowFlags.NoScrollbar)
    {
        SizeConstraints = new WindowSizeConstraints
        {
            MinimumSize = new Vector2(620, 480),
            MaximumSize = new Vector2(float.MaxValue, float.MaxValue),
        };
        _plugin = plugin;
    }

    public void Dispose() { }

    public override void Draw()
    {
        var cfg = _plugin.Configuration;
        var bridge = _plugin.Bridge;
        var server = _plugin.Server;

        // 版本监控：一进来就能看到"插件是哪个版本、在服务哪个端口"
        ImGui.TextColored(Dim, $"ModBridge v{Plugin.PluginVersion}   端口 {server.Port}   Penumbra " +
                               (bridge.Available ? $"API {bridge.ApiMajor}.{bridge.ApiMinor}" : "未连接"));
        ImGui.Separator();

        UpdateAutoClose(cfg);      // 「安装完成后自动关闭窗口」

        // ================= 待确认安装（两段式的核心） =================
        var pending = _plugin.Requests.Pending();
        if (pending.Count > 0)
        {
            ImGui.TextColored(Yellow, $"待确认安装：{pending.Count} 条");
            ImGui.SameLine();
            ImGui.TextColored(Dim, "—— 确认后才会装进 Penumbra");
            ImGui.Separator();

            foreach (var r in pending)
            {
                ImGui.PushID(r.Id);
                DrawPending(r);
                ImGui.PopID();
                ImGui.Separator();
            }
        }
        else
        {
            ImGui.TextColored(Dim, "待确认安装：无（mod 管理器点「安装到游戏」后会出现在这里）");
            ImGui.Separator();
        }

        // ================= Penumbra 状态 =================
        if (ImGui.Button("重新探测 Penumbra"))
            bridge.Refresh();
        ImGui.SameLine();
        if (bridge.Available)
            ImGui.TextColored(Green, $"Penumbra 已连接 · API {bridge.ApiMajor}.{bridge.ApiMinor}");
        else
            ImGui.TextColored(Red, "Penumbra 未连接（没装 / 还在加载 / 版本太老）");

        if (bridge.Available)
        {
            ImGui.TextColored(Dim, $"mod 数：{bridge.Mods().Count}");
            ImGui.TextColored(Dim, "mod 目录：");
            ImGui.SameLine();
            ImGui.TextWrapped(bridge.ModDirectory);
            if (ImGui.Button("复制 mod 目录"))
                ImGui.SetClipboardText(bridge.ModDirectory);
        }

        ImGui.Separator();

        // ================= 本地 HTTP 服务 =================
        ImGui.Text("本地 HTTP 服务");
        if (server.IsRunning)
            ImGui.TextColored(Green, $"运行中：http://127.0.0.1:{server.Port}/");
        else
            ImGui.TextColored(Red, "未运行");

        var port = cfg.Port;
        ImGui.SetNextItemWidth(120);
        if (ImGui.InputInt("端口", ref port))
        {
            if (port is > 1024 and < 65535)
            {
                cfg.Port = port;
                cfg.Save();
            }
        }
        ImGui.SameLine();
        if (server.IsRunning)
        {
            if (ImGui.Button("停止"))
                _plugin.StopServer();
        }
        else
        {
            if (ImGui.Button("启动"))
                _plugin.StartServer();
        }
        ImGui.SameLine();
        if (ImGui.Button("复制接口地址"))
            ImGui.SetClipboardText($"http://127.0.0.1:{server.Port}");

        if (ImGui.Button("复制 Token"))
            ImGui.SetClipboardText(cfg.Token);
        ImGui.SameLine();
        ImGui.TextColored(Dim, "管理器请求要带 X-ModBridge-Token 头（除 /ping）");
        ImGui.SetNextItemWidth(-1);
        _tokenView = cfg.Token;
        ImGui.InputText("##token", ref _tokenView, 256, ImGuiInputTextFlags.ReadOnly);

        ImGui.Separator();

        // ================= 行为开关 =================
        var enable = cfg.EnableOnInstall;
        if (ImGui.Checkbox("装完自动在当前集合里启用", ref enable))
        {
            cfg.EnableOnInstall = enable;
            cfg.Save();
        }
        ImGui.SameLine();
        var autoOpen = cfg.AutoOpenOnRequest;
        if (ImGui.Checkbox("收到请求时自动弹这个窗口", ref autoOpen))
        {
            cfg.AutoOpenOnRequest = autoOpen;
            cfg.Save();
        }
        ImGui.SameLine();
        var autoClose = cfg.AutoCloseWhenDone;
        if (ImGui.Checkbox("安装完成后自动关闭这个窗口", ref autoClose))
        {
            cfg.AutoCloseWhenDone = autoClose;
            cfg.Save();
        }

        var anyUrl = cfg.AllowAnyUrl;
        if (ImGui.Checkbox("允许任意下载域名（关掉则只信任常见 mod 站）", ref anyUrl))
        {
            cfg.AllowAnyUrl = anyUrl;
            cfg.Save();
        }
        ImGui.SameLine();
        var cleanup = cfg.CleanupTempFiles;
        if (ImGui.Checkbox("装完删除临时下载文件（本地包永不删）", ref cleanup))
        {
            cfg.CleanupTempFiles = cleanup;
            cfg.Save();
        }

        var autoStart = cfg.AutoStart;
        if (ImGui.Checkbox("下次启动插件时自动开 HTTP", ref autoStart))
        {
            cfg.AutoStart = autoStart;
            cfg.Save();
        }

        ImGui.Separator();

        // ================= 安装记录 =================
        ImGui.Text("安装记录");
        ImGui.SameLine();
        ImGui.TextColored(Dim, "（确认后在这里看下载/安装进度）");

        if (ImGui.BeginTable("jobs", 6,
                ImGuiTableFlags.Borders | ImGuiTableFlags.RowBg | ImGuiTableFlags.ScrollY,
                new Vector2(0, 220)))
        {
            ImGui.TableSetupColumn("时间", ImGuiTableColumnFlags.WidthFixed, 60);
            ImGui.TableSetupColumn("状态", ImGuiTableColumnFlags.WidthFixed, 70);
            ImGui.TableSetupColumn("进度", ImGuiTableColumnFlags.WidthFixed, 110);
            ImGui.TableSetupColumn("Mod", ImGuiTableColumnFlags.WidthStretch);
            ImGui.TableSetupColumn("信息", ImGuiTableColumnFlags.WidthStretch);
            ImGui.TableSetupColumn("操作", ImGuiTableColumnFlags.WidthFixed, 60);
            ImGui.TableHeadersRow();

            foreach (var j in _plugin.Jobs.Snapshot())
            {
                ImGui.TableNextRow();
                ImGui.TableNextColumn();
                ImGui.Text(j.StartedAt.ToString("HH:mm:ss"));

                ImGui.TableNextColumn();
                var color = j.State switch
                {
                    JobState.Done => Green,
                    JobState.Error => Red,
                    JobState.Cancelled => Dim,
                    _ => Yellow,
                };
                ImGui.TextColored(color, StateText(j.State));

                ImGui.TableNextColumn();
                if (j.State == JobState.Downloading && j.Total > 0)
                    ImGui.ProgressBar((float)(j.Percent / 100.0), new Vector2(-1, 16), $"{j.Percent:F0}%");
                else if (j.Total > 0)
                    ImGui.TextColored(Dim, $"{j.Total / 1048576.0:F1} MB");

                ImGui.TableNextColumn();
                ImGui.TextWrapped(j.ModName ?? j.ModDirName ?? Path.GetFileName(j.Url));
                if (ImGui.IsItemHovered() && j.Steps.Count > 0)
                    ImGui.SetTooltip(string.Join("\n", j.Steps.TakeLast(10)));

                ImGui.TableNextColumn();
                if (!string.IsNullOrEmpty(j.Error))
                    ImGui.TextColored(Red, Truncate(j.Error, 70));
                else
                    ImGui.TextColored(Dim, j.PenumbraResult ?? "");

                ImGui.TableNextColumn();
                if (j.State is JobState.Queued or JobState.Downloading or JobState.Installing)
                {
                    if (ImGui.SmallButton($"取消##{j.Id}"))
                        _plugin.Jobs.Cancel(j.Id);
                }
                else if (j.ModDirName is not null)
                {
                    if (ImGui.SmallButton($"定位##{j.Id}"))
                        _plugin.Bridge.OpenModsTab(j.ModDirName, j.ModName ?? "");
                }
            }
            ImGui.EndTable();
        }

        ImGui.Separator();
        ImGui.TextColored(Dim, "管理器怎么调：");
        ImGui.TextWrapped($"POST http://127.0.0.1:{server.Port}/propose " +
                          "{\"localPath\":\"G:\\\\...\\\\mod.pmp\",\"name\":\"...\",\"author\":\"...\"} " +
                          "→ 在游戏里确认 → 自动下载/安装/启用/重绘。也可用 /install 直接装（跳过确认）。");
        if (ImGui.Button("复制 curl 示例（送到待确认）"))
        {
            var u = $"http://127.0.0.1:{server.Port}/propose";
            ImGui.SetClipboardText(
                $"curl -X POST {u} -H \"Content-Type: application/json\" " +
                $"-H \"X-ModBridge-Token: {cfg.Token}\" " +
                "-d \"{\\\"localPath\\\":\\\"G:\\\\Games\\\\FFXIV\\\\MOD\\\\202609\\\\...\\\\xxx.pmp\\\"," +
                "\\\"name\\\":\\\"示例 Mod\\\",\\\"author\\\":\\\"作者\\\"}\"");
        }
    }

    private void DrawPending(ModBridge.Requests.InstallRequest r)
    {
        const float thumb = 96f;

        // 封面缩略图（本地文件路径）
        var hasCover = !string.IsNullOrEmpty(r.CoverPath) && File.Exists(r.CoverPath);
        if (hasCover)
        {
            var path = r.CoverPath!;
            if (!_covers.TryGetValue(path, out var tex))
            {
                try { tex = Plugin.TextureProvider.GetFromFile(path); }
                catch (Exception e)
                {
                    Plugin.Log.Debug($"[ModBridge] 封面读不了（{path}）: {e.Message}");
                    tex = null;
                }
                _covers[path] = tex;   // 失败也缓存，避免每帧重试
            }
            var wrap = tex?.GetWrapOrDefault();
            if (wrap is not null)
            {
                var size = FitSize(wrap.Size, thumb);
                ImGui.Image(wrap.Handle, size);
                ImGui.SameLine();
            }
        }

        ImGui.BeginGroup();
        ImGui.TextColored(Yellow, r.Name);
        ImGui.TextColored(Dim, string.IsNullOrWhiteSpace(r.Author) ? "作者：—" : $"作者：{r.Author}");
        if (!string.IsNullOrWhiteSpace(r.Description))
            ImGui.TextWrapped(Truncate(r.Description!, 160));
        ImGui.TextColored(Dim, (r.IsLocal ? "本地包：" : "下载地址：") + Truncate(r.Source, 90));
        if (!string.IsNullOrEmpty(r.DirName))
            ImGui.TextColored(Dim, $"目标目录名：{r.DirName}" + (r.Enable ? "　装完自动启用" : "　装完不自动启用"));
        else
            ImGui.TextColored(Dim, r.Enable ? "装完自动启用" : "装完不自动启用");
        if (r.Priority is { } pr)
            ImGui.TextColored(Dim, $"　优先级 {pr}");
        ImGui.TextColored(Dim, $"来源：{r.Origin}　{r.CreatedAt:HH:mm:ss}");

        var approve = ImGui.Button($"确认安装##ok{r.Id}", new Vector2(96, 26));
        ImGui.SameLine();
        var reject = ImGui.Button($"忽略##no{r.Id}", new Vector2(72, 26));
        ImGui.SameLine();
        if (ImGui.Button("定位文件", new Vector2(84, 26)))
        {
            try
            {
                var dir = Path.GetDirectoryName(r.Source);
                if (!string.IsNullOrEmpty(dir) && Directory.Exists(dir))
                    System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
                    {
                        FileName = dir,
                        UseShellExecute = true,
                    });
            }
            catch (Exception e)
            {
                Plugin.Log.Debug($"[ModBridge] 打开目录失败: {e.Message}");
            }
        }
        ImGui.EndGroup();

        if (approve)
        {
            var res = Approve(r.Id);
            Plugin.ChatGui.Print($"[Mod Bridge] {res}");
        }
        else if (reject)
        {
            _plugin.Requests.Decide(r.Id, false);
            Plugin.ChatGui.Print($"[Mod Bridge] 已忽略：{r.Name}");
        }
    }

    /// <summary>游戏内点"确认安装"：批准请求 → 起安装任务。</summary>
    private string Approve(string requestId)
    {
        var r = _plugin.Requests.Decide(requestId, true);
        if (r is null)
            return "这条请求已经处理过了";

        if (!_plugin.Bridge.Available)
        {
            _plugin.Requests.Decide(requestId, false);
            return "Penumbra 不可用，先确认它已加载";
        }

        var job = _plugin.Jobs.Start(r.Source, r.IsLocal, r.DirName, r.Enable, r.Priority);
        _plugin.Requests.MarkApproved(r.Id, job.Id);
        return $"开始安装「{r.Name}」…（进度见下方安装记录）";
    }

    // ---- 「安装完成后自动关闭窗口」的状态 ----
    private bool _sawRunningJob;                    // 见到过在跑的任务（避免刚开窗就被关掉）
    private DateTime _allDoneAt = DateTime.MinValue;

    /// <summary>
    /// 勾了「安装完成后自动关闭这个窗口」时：任务全部结束 → 停留几秒 → 自动关窗。
    /// 失败也会关（详情在聊天框和安装记录里），但会先在聊天框提醒一句。
    /// </summary>
    private void UpdateAutoClose(Configuration cfg)
    {
        if (!cfg.AutoCloseWhenDone)
        {
            _sawRunningJob = false;
            _allDoneAt = DateTime.MinValue;
            return;
        }

        var jobs = _plugin.Jobs.Snapshot();
        if (jobs.Any(j => j.State is JobState.Queued or JobState.Downloading or JobState.Installing))
        {
            _sawRunningJob = true;
            _allDoneAt = DateTime.MinValue;
            return;
        }

        if (!_sawRunningJob || !IsOpen)
            return;

        var delay = Math.Clamp(cfg.AutoCloseDelaySec, 0, 60);
        if (_allDoneAt == DateTime.MinValue)
        {
            _allDoneAt = DateTime.Now;
            var failed = jobs.Count(j => j.State == JobState.Error);
            Plugin.ChatGui.Print(failed > 0
                ? $"[Mod Bridge] 有 {failed} 条安装失败，窗口 {delay} 秒后自动关闭（详情：/modbridge）"
                : $"[Mod Bridge] 安装完成，窗口 {delay} 秒后自动关闭");
            return;
        }

        if ((DateTime.Now - _allDoneAt).TotalSeconds >= delay)
        {
            IsOpen = false;
            _sawRunningJob = false;
            _allDoneAt = DateTime.MinValue;
        }
    }

    private static Vector2 FitSize(Vector2 src, float box)
    {
        if (src.X <= 0 || src.Y <= 0)
            return new Vector2(box, box);
        var k = MathF.Min(box / src.X, box / src.Y);
        return new Vector2(src.X * k, src.Y * k);
    }

    private static string StateText(JobState s) => s switch
    {
        JobState.Queued => "排队",
        JobState.Downloading => "下载中",
        JobState.Installing => "安装中",
        JobState.Done => "完成",
        JobState.Error => "失败",
        JobState.Cancelled => "已取消",
        _ => s.ToString(),
    };

    private static string Truncate(string s, int n)
        => s.Length <= n ? s : s[..n] + "…";
}
