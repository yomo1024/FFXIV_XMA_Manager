using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
namespace ModBridge.Http;

public sealed record HttpRequest(
    string Method,
    string Path,
    Dictionary<string, string> Query,
    Dictionary<string, string> Headers,
    string Body)
{
    public string? Header(string name)
        => Headers.TryGetValue(name, out var v) ? v : null;
}

public sealed record HttpResponse(int Status, byte[] Body, string ContentType,
                                  Dictionary<string, string>? Headers = null)
{
    public static HttpResponse Json(string json, int status = 200)
        => new(status, Encoding.UTF8.GetBytes(json), "application/json; charset=utf-8");

    public static HttpResponse Text(string text, int status = 200)
        => new(status, Encoding.UTF8.GetBytes(text), "text/plain; charset=utf-8");

    public static HttpResponse Empty(int status = 204)
        => new(status, [], "text/plain");
}

/// <summary>
/// 极简 HTTP/1.1 服务：只用 TcpListener，不依赖 ASP.NET Core。
/// 游戏进程里没有 ASP.NET Core 共享框架，用 HttpListener 又要 URL ACL/管理员，
/// 所以这里手写一个够用的小服务器（仅本机、仅短请求、Connection: close）。
/// </summary>
public sealed class HttpMiniServer : IDisposable
{
    private const int MaxHeaderBytes = 64 * 1024;
    private const int MaxBodyBytes = 64 * 1024 * 1024;
    private const int PortTries = 20;

    private readonly Func<HttpRequest, HttpResponse> _handler;
    private readonly IModBridgeLog _log;
    private TcpListener? _listener;
    private Thread? _acceptThread;
    private volatile bool _running;

    public int Port { get; private set; }
    public bool IsRunning => _running;

    public HttpMiniServer(int preferredPort, Func<HttpRequest, HttpResponse> handler, IModBridgeLog log)
    {
        _handler = handler;
        _log = log;
        Port = preferredPort;
    }

    /// <summary>启动监听（只绑 127.0.0.1）。端口被占则自动向后顺延。返回实际端口，失败返回 0。</summary>
    public int Start(int preferredPort)
    {
        if (_running)
            return Port;

        for (var p = preferredPort; p < preferredPort + PortTries; p++)
        {
            try
            {
                var l = new TcpListener(IPAddress.Loopback, p);
                l.Start();
                _listener = l;
                Port = p;
                break;
            }
            catch (SocketException)
            {
                // 端口被占，试下一个
            }
        }

        if (_listener is null)
        {
            _log.Error($"[ModBridge] {preferredPort}~{preferredPort + PortTries - 1} 都被占用，HTTP 没起来。");
            return 0;
        }

        _running = true;
        _acceptThread = new Thread(AcceptLoop) { IsBackground = true, Name = "ModBridge-HTTP" };
        _acceptThread.Start();
        _log.Info($"[ModBridge] HTTP 已监听 http://127.0.0.1:{Port}/");
        return Port;
    }

    public void Stop()
    {
        _running = false;
        try { _listener?.Stop(); } catch { /* 忽略 */ }
        _listener = null;
        _acceptThread = null;
    }

    private void AcceptLoop()
    {
        while (_running)
        {
            TcpClient? client = null;
            try
            {
                client = _listener!.AcceptTcpClient();
            }
            catch (Exception)
            {
                if (!_running)
                    break;
                Thread.Sleep(50);
                continue;
            }

            var c = client;
            ThreadPool.QueueUserWorkItem(_ => HandleClient(c));
        }
    }

    private void HandleClient(TcpClient client)
    {
        using (client)
        {
            try
            {
                client.ReceiveTimeout = 10_000;
                client.SendTimeout = 30_000;
                using var stream = client.GetStream();

                var req = ReadRequest(stream);
                if (req is null)
                    return;

                HttpResponse resp;
                try
                {
                    // CORS 预检属于传输层：不打扰业务路由，直接 204（CORS/PNA 头统一在 WriteResponse 里加）
                    resp = req.Method == "OPTIONS" ? HttpResponse.Empty(204) : _handler(req);
                }
                catch (Exception e)
                {
                    _log.Warn($"[ModBridge] 处理 {req.Method} {req.Path} 出错: {e}");
                    resp = HttpResponse.Json($"{{\"ok\":false,\"error\":\"{Escape(e.Message)}\"}}", 500);
                }

                WriteResponse(stream, req, resp);
            }
            catch (Exception e)
            {
                _log.Debug($"[ModBridge] 连接处理异常: {e.Message}");
            }
        }
    }

    private static HttpRequest? ReadRequest(NetworkStream stream)
    {
        var head = new MemoryStream();
        var buf = new byte[4096];
        var headerEnd = -1;

        while (headerEnd < 0)
        {
            var n = stream.Read(buf, 0, buf.Length);
            if (n <= 0)
                return null;
            head.Write(buf, 0, n);
            if (head.Length > MaxHeaderBytes)
                return null;
            var arr = head.GetBuffer();
            var len = (int)head.Length;
            for (var i = 3; i < len; i++)
            {
                if (arr[i - 3] == 13 && arr[i - 2] == 10 && arr[i - 1] == 13 && arr[i] == 10)
                {
                    headerEnd = i + 1;
                    break;
                }
            }
        }

        var all = head.ToArray();
        var headText = Encoding.UTF8.GetString(all, 0, headerEnd);
        var rest = new byte[all.Length - headerEnd];
        Array.Copy(all, headerEnd, rest, 0, rest.Length);

        var lines = headText.Split("\r\n", StringSplitOptions.None);
        if (lines.Length == 0)
            return null;

        var parts = lines[0].Split(' ');
        if (parts.Length < 2)
            return null;

        var method = parts[0].ToUpperInvariant();
        var target = parts[1];
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 1; i < lines.Length; i++)
        {
            var idx = lines[i].IndexOf(':');
            if (idx > 0)
                headers[lines[i][..idx].Trim()] = lines[i][(idx + 1)..].Trim();
        }

        var qIdx = target.IndexOf('?');
        var path = qIdx >= 0 ? target[..qIdx] : target;
        var query = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (qIdx >= 0)
        {
            foreach (var kv in target[(qIdx + 1)..].Split('&', StringSplitOptions.RemoveEmptyEntries))
            {
                var eq = kv.IndexOf('=');
                var k = eq >= 0 ? kv[..eq] : kv;
                var v = eq >= 0 ? kv[(eq + 1)..] : "";
                query[Uri.UnescapeDataString(k)] = Uri.UnescapeDataString(v.Replace('+', ' '));
            }
        }

        var body = "";
        if (headers.TryGetValue("Content-Length", out var clText) && int.TryParse(clText, out var cl) && cl > 0)
        {
            if (cl > MaxBodyBytes)
                return null;
            var bodyBuf = new byte[cl];
            var have = Math.Min(rest.Length, cl);
            Array.Copy(rest, bodyBuf, have);
            while (have < cl)
            {
                var n = stream.Read(bodyBuf, have, cl - have);
                if (n <= 0)
                    break;
                have += n;
            }
            body = Encoding.UTF8.GetString(bodyBuf, 0, have);
        }

        return new HttpRequest(method, path, query, headers, body);
    }

    private static void WriteResponse(NetworkStream stream, HttpRequest req, HttpResponse resp)
    {
        var origin = req.Header("Origin") ?? "*";
        var sb = new StringBuilder();
        sb.Append("HTTP/1.1 ").Append(resp.Status).Append(' ').Append(StatusText(resp.Status)).Append("\r\n");
        sb.Append("Content-Type: ").Append(resp.ContentType).Append("\r\n");
        sb.Append("Content-Length: ").Append(resp.Body.Length).Append("\r\n");
        sb.Append("Connection: close\r\n");
        // CORS：允许网页跨源调用
        sb.Append("Access-Control-Allow-Origin: ").Append(origin).Append("\r\n");
        sb.Append("Vary: Origin\r\n");
        sb.Append("Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n");
        sb.Append("Access-Control-Allow-Headers: Content-Type, X-ModBridge-Token\r\n");
        sb.Append("Access-Control-Expose-Headers: *\r\n");
        sb.Append("Access-Control-Max-Age: 600\r\n");
        // 公网 https 页面访问 127.0.0.1 会走 Preflight + Private Network Access
        if (req.Method == "OPTIONS" || string.Equals(req.Header("Access-Control-Request-Private-Network"),
                                                      "true", StringComparison.OrdinalIgnoreCase))
            sb.Append("Access-Control-Allow-Private-Network: true\r\n");
        if (resp.Headers is not null)
            foreach (var (k, v) in resp.Headers)
                sb.Append(k).Append(": ").Append(v).Append("\r\n");
        sb.Append("\r\n");

        var head = Encoding.UTF8.GetBytes(sb.ToString());
        stream.Write(head, 0, head.Length);
        if (resp.Body.Length > 0)
            stream.Write(resp.Body, 0, resp.Body.Length);
        stream.Flush();
    }

    private static string StatusText(int status) => status switch
    {
        200 => "OK",
        204 => "No Content",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        413 => "Payload Too Large",
        500 => "Internal Server Error",
        _ => "OK",
    };

    public static string Escape(string s)
        => s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", " ").Replace("\n", " ");

    public void Dispose() => Stop();
}
