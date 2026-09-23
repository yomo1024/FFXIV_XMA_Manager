using System;
using System.Collections.Generic;
using System.Linq;

namespace ModBridge.Requests;

public enum RequestState { Pending, Approved, Rejected }

/// <summary>
/// 一次"待确认安装"。mod 管理器把 mod 信息发过来先存这里，
/// 在游戏内窗口里给人看过、点了「确认安装」才真正去下载/安装。
/// </summary>
public sealed class InstallRequest
{
    public string Id { get; init; } = Guid.NewGuid().ToString("N")[..10];
    public string Name { get; init; } = "";
    public string? Author { get; init; }
    public string? Description { get; init; }

    /// <summary>http(s) 直链，或本机 .pmp/.pcp/.ttmp 路径。</summary>
    public string Source { get; init; } = "";
    public bool IsLocal { get; init; }

    /// <summary>本机封面图路径（可选，用于窗口里显示缩略图）。</summary>
    public string? CoverPath { get; init; }
    /// <summary>管理器转好的真 WebP 封面路径（可选）。有它就写 mod 根目录的 cover.webp。</summary>
    public string? CoverWebpPath { get; init; }
    /// <summary>管理器转好的"能解码"封面（真 JPEG，可选）。写进 images\_MetaImage 供插件自己画。</summary>
    public string? CoverDrawPath { get; init; }
    /// <summary>目标 mod 目录名提示（Penumbra 可能自己规范名字，仅作参考）。</summary>
    public string? DirName { get; init; }
    public bool Enable { get; init; } = true;
    public int? Priority { get; init; }

    /// <summary>来源标注，例如 "ModManagerWeb"。</summary>
    public string? Origin { get; init; }
    public DateTime CreatedAt { get; init; } = DateTime.Now;

    public RequestState State { get; set; } = RequestState.Pending;
    public string? JobId { get; set; }
    public DateTime? DecidedAt { get; set; }

    public object ToJson() => new
    {
        id = Id,
        name = Name,
        author = Author,
        description = Description,
        source = Source,
        isLocal = IsLocal,
        coverPath = CoverPath,
        coverWebpPath = CoverWebpPath,
        coverDrawPath = CoverDrawPath,
        dirName = DirName,
        enable = Enable,
        priority = Priority,
        origin = Origin,
        state = State.ToString().ToLowerInvariant(),
        jobId = JobId,
        createdAt = CreatedAt.ToString("HH:mm:ss"),
        decidedAt = DecidedAt?.ToString("HH:mm:ss"),
    };
}

/// <summary>
/// 待确认队列 + 最近处理过的记录。刻意不依赖任何 Dalamud/游戏类型，方便单测。
/// </summary>
public sealed class RequestStore
{
    private readonly object _lock = new();
    private readonly List<InstallRequest> _all = [];

    public int MaxKeep { get; init; } = 40;
    public int MaxPending { get; init; } = 20;

    /// <summary>加一条待确认请求。待确认队列满了返回 null。</summary>
    public InstallRequest? Add(InstallRequest req)
    {
        lock (_lock)
        {
            if (_all.Count(x => x.State == RequestState.Pending) >= MaxPending)
                return null;
            _all.Insert(0, req);
            Trim();
            return req;
        }
    }

    public IReadOnlyList<InstallRequest> Pending()
    {
        lock (_lock)
            return _all.Where(x => x.State == RequestState.Pending).ToList();
    }

    public IReadOnlyList<InstallRequest> All()
    {
        lock (_lock)
            return _all.ToList();
    }

    public InstallRequest? Get(string id)
    {
        lock (_lock)
            return _all.FirstOrDefault(x => x.Id == id);
    }

    /// <summary>批准/拒绝一条。返回处理后的请求；不存在或已经处理过返回 null。</summary>
    public InstallRequest? Decide(string id, bool approve)
    {
        lock (_lock)
        {
            var req = _all.FirstOrDefault(x => x.Id == id);
            if (req is null || req.State != RequestState.Pending)
                return null;

            // 立刻落状态，避免同一请求被两次批准（HTTP 线程可能并发进来）
            req.State = approve ? RequestState.Approved : RequestState.Rejected;
            req.DecidedAt = DateTime.Now;
            return req;
        }
    }

    public void MarkApproved(string id, string jobId)
    {
        lock (_lock)
        {
            var req = _all.FirstOrDefault(x => x.Id == id);
            if (req is null)
                return;
            req.State = RequestState.Approved;
            req.JobId = jobId;
            req.DecidedAt = DateTime.Now;
        }
    }

    private void Trim()
    {
        while (_all.Count > MaxKeep)
            _all.RemoveAt(_all.Count - 1);
    }
}
