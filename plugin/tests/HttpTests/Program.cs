using System.Linq;
using System.Net;
using System.Text;
using System.Text.Json;
using ModBridge.Http;

namespace HttpTests;

/// <summary>
/// 手写 HTTP 层的独立测试：不需要 Dalamud，也不需要游戏。
/// 覆盖：路由分发、CORS/PNA 预检、token 鉴权语义（这里用假 handler 模拟）、
///      大 body（mod 包信息/上传）、无 body、404、连接复用与关闭。
/// </summary>
public static class Program
{
    private static int _fails;
    private static readonly List<string> Log = [];

    private static void Check(string label, bool ok, string? detail = null)
    {
        Console.WriteLine((ok ? "  OK   " : "  FAIL ") + label.PadRight(52) + (detail ?? ""));
        if (!ok)
            _fails++;
    }

    public static async Task<int> Main()
    {
        var port0 = 45999;
        var seen = new List<string>();

        HttpResponse Handler(HttpRequest req)
        {
            lock (seen)
                seen.Add($"{req.Method} {req.Path}");

            switch (req.Path.TrimEnd('/'))
            {
                case "" or "/ping":
                    return HttpResponse.Json(JsonSerializer.Serialize(new
                    {
                        ok = true,
                        path = req.Path,
                        origin = req.Header("Origin"),
                        bodyLen = req.Body.Length,
                        q = req.Query.TryGetValue("x", out var x) ? x : null,
                    }));

                case "/big":
                    return HttpResponse.Json($"{{\"ok\":true,\"got\":{req.Body.Length}}}");

                case "/echo":
                    return HttpResponse.Text(req.Body);

                case "/boom":
                    throw new InvalidOperationException("故意炸一下 \"引号\" 和换行\n第二行");

                default:
                    return HttpResponse.Json("{\"ok\":false,\"error\":\"没有这个接口\"}", 404);
            }
        }

        using var server = new HttpMiniServer(port0, Handler, new NullLog());
        var port = server.Start(port0);
        Check("服务启动并拿到端口", port > 0, $"port={port}");
        Check("端口顺延逻辑存在（首选被占也应有端口）", port is > 0 and < 46000 + 20);
        Check("IsRunning 为真", server.IsRunning);

        var baseUrl = $"http://127.0.0.1:{port}";
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };

        // ---------- 1. 基本 GET + query ----------
        var r1 = await http.GetAsync($"{baseUrl}/ping?x=he%20llo");
        var b1 = await r1.Content.ReadAsStringAsync();
        Check("GET /ping → 200", r1.StatusCode == HttpStatusCode.OK, ((int)r1.StatusCode).ToString());
        Check("返回 JSON", r1.Content.Headers.ContentType?.MediaType == "application/json");
        Check("query 解码正确", b1.Contains("he llo"), b1.Length > 120 ? b1[..120] : b1);
        Check("CORS: 无 Origin 时给 *", r1.Headers.TryGetValues("Access-Control-Allow-Origin", out var ao)
                                       && ao.First() == "*");
        Check("Content-Length 正确", r1.Content.Headers.ContentLength == Encoding.UTF8.GetByteCount(b1));

        // ---------- 2. 带 Origin 的跨源请求 + PNA 预检 ----------
        var opt = new HttpRequestMessage(HttpMethod.Options, $"{baseUrl}/install");
        opt.Headers.Add("Origin", "https://my-mod-site.example");
        opt.Headers.Add("Access-Control-Request-Method", "POST");
        opt.Headers.Add("Access-Control-Request-Headers", "content-type,x-modbridge-token");
        opt.Headers.Add("Access-Control-Request-Private-Network", "true");
        var r2 = await http.SendAsync(opt);
        Check("OPTIONS 预检 → 204", r2.StatusCode == HttpStatusCode.NoContent, ((int)r2.StatusCode).ToString());
        Check("回显 Origin（不是 *）",
            r2.Headers.TryGetValues("Access-Control-Allow-Origin", out var ao2)
            && ao2.First() == "https://my-mod-site.example");
        Check("允许自定义头 X-ModBridge-Token",
            r2.Headers.TryGetValues("Access-Control-Allow-Headers", out var ah)
            && ah.First().Contains("X-ModBridge-Token", StringComparison.OrdinalIgnoreCase));
        Check("私有网络访问头（PNA）已回",
            r2.Headers.TryGetValues("Access-Control-Allow-Private-Network", out var pna)
            && pna.First() == "true");
        Check("OPTIONS 没有触发业务 handler", !seen.Any(s => s.Contains("OPTIONS")));

        // ---------- 3. POST JSON ----------
        var body = JsonSerializer.Serialize(new { url = "https://example.com/中文名.pmp", enable = true });
        var r3 = await http.PostAsync($"{baseUrl}/big",
            new StringContent(body, Encoding.UTF8, "application/json"));
        var b3 = await r3.Content.ReadAsStringAsync();
        var got = JsonDocument.Parse(b3).RootElement.GetProperty("got").GetInt32();
        Check("POST 带 UTF-8 body 长度正确", got == Encoding.UTF8.GetByteCount(body),
            $"发送 {Encoding.UTF8.GetByteCount(body)} / 收到 {got}");

        // ---------- 4. 大 body（8 MB）跨包读取 ----------
        var big = new string('x', 8 * 1024 * 1024);
        var r4 = await http.PostAsync($"{baseUrl}/big", new StringContent(big));
        var b4 = await r4.Content.ReadAsStringAsync();
        var got4 = JsonDocument.Parse(b4).RootElement.GetProperty("got").GetInt32();
        Check("8 MB body 完整收到", got4 == big.Length, $"收到 {got4}");

        // ---------- 5. 无 body / 未定义路由 ----------
        var r5 = await http.GetAsync($"{baseUrl}/nope");
        Check("未知路由 → 404", r5.StatusCode == HttpStatusCode.NotFound, ((int)r5.StatusCode).ToString());

        // ---------- 6. handler 抛异常 → 500 JSON，不崩服务 ----------
        var r6 = await http.GetAsync($"{baseUrl}/boom");
        var b6 = await r6.Content.ReadAsStringAsync();
        Check("handler 抛异常 → 500", r6.StatusCode == HttpStatusCode.InternalServerError,
            ((int)r6.StatusCode).ToString());
        Check("异常信息被转义成合法 JSON",
            b6.Contains("故意炸一下") && !b6.Contains('\n'), b6[..Math.Min(90, b6.Length)]);
        Check("异常后服务还活着", (await http.GetAsync($"{baseUrl}/ping")).StatusCode == HttpStatusCode.OK);

        // ---------- 7. 畸形请求不崩 ----------
        try
        {
            using var raw = new System.Net.Sockets.TcpClient();
            await raw.ConnectAsync(IPAddress.Loopback, port);
            var junk = Encoding.ASCII.GetBytes("GARBAGE\r\n\r\n");
            await raw.GetStream().WriteAsync(junk);
            await raw.GetStream().FlushAsync();
            await Task.Delay(200);
        }
        catch { /* 忽略 */ }
        Check("畸形请求后服务仍可用", (await http.GetAsync($"{baseUrl}/ping")).StatusCode == HttpStatusCode.OK);

        // ---------- 8. 并发 ----------
        var tasks = Enumerable.Range(0, 30).Select(i => http.GetAsync($"{baseUrl}/ping?x={i}")).ToArray();
        var all = await Task.WhenAll(tasks);
        Check("30 个并发请求全 200", all.All(x => x.StatusCode == HttpStatusCode.OK));

        // ---------- 9. 停止 ----------
        server.Stop();
        Check("停止后 IsRunning=false", !server.IsRunning);
        var stopped = false;
        try { await http.GetAsync($"{baseUrl}/ping"); }
        catch { stopped = true; }
        Check("停止后连接被拒", stopped);

        // ---------- 10. 两段式：待确认队列 ----------
        Console.WriteLine();
        Console.WriteLine("待确认队列（/propose → 游戏内确认 → /decide）：");
        var store = new ModBridge.Requests.RequestStore { MaxKeep = 5, MaxPending = 3 };

        var a = store.Add(new ModBridge.Requests.InstallRequest
        {
            Name = "Tight Leggings", Author = "Pocky",
            Source = @"G:\Games\FFXIV\MOD\202609\衣服\SFW\6.[Pocky] Tight Leggings.pmp",
            IsLocal = true, Enable = true, Origin = "ModManagerWeb",
        });
        Check("加入一条待确认", a is not null && store.Pending().Count == 1, a?.Id);

        var b2 = store.Add(new ModBridge.Requests.InstallRequest { Name = "B", Source = "x" });
        var c2 = store.Add(new ModBridge.Requests.InstallRequest { Name = "C", Source = "x" });
        Check("待确认队列上限生效（第 4 条被拒）",
            store.Add(new ModBridge.Requests.InstallRequest { Name = "D", Source = "x" }) is null
            && store.Pending().Count == 3);

        Check("批准前状态是 pending", a!.State == ModBridge.Requests.RequestState.Pending);
        var decided = store.Decide(a.Id, true);
        Check("批准返回该请求", decided is not null && decided.State == ModBridge.Requests.RequestState.Approved);
        Check("不能重复批准", store.Decide(a.Id, true) is null);
        Check("批准后不在待确认列表", store.Pending().All(x => x.Id != a.Id));

        store.MarkApproved(a.Id, "job12345");
        Check("回填 jobId", store.Get(a.Id)!.JobId == "job12345");

        var rejected = store.Decide(b2!.Id, false);
        Check("拒绝生效", rejected is not null
            && rejected.State == ModBridge.Requests.RequestState.Rejected
            && store.Get(b2.Id)!.State == ModBridge.Requests.RequestState.Rejected);
        Check("拒绝的也不再待确认", store.Pending().All(x => x.Id != b2.Id));

        Check("不存在的 id 返回 null", store.Decide("nope", true) is null);
        Check("MaxKeep 会裁掉旧记录（共 5 条以内）", store.All().Count <= 5, store.All().Count.ToString());
        Check("JSON 可序列化（界面要用）",
            System.Text.Json.JsonSerializer.Serialize(a.ToJson()).Contains("tight leggings".Replace("tight leggings", "Tight Leggings")));

        // ---------- 11. 来源校验（/propose 与 /install 都走它） ----------
        Console.WriteLine();
        Console.WriteLine("来源校验 SourceResolver（以前完全没被测过的那块）：");
        var tmpDir = Path.Combine(Path.GetTempPath(), "modbridge_src_test");
        Directory.CreateDirectory(tmpDir);
        var goodPmp = Path.Combine(tmpDir, "示例 Mod.pmp");
        File.WriteAllBytes(goodPmp, new byte[2048]);
        var txtFile = Path.Combine(tmpDir, "readme.txt");
        File.WriteAllText(txtFile, "nope");

        static System.Text.Json.JsonElement? Body(string json)
        {
            using var d = System.Text.Json.JsonDocument.Parse(json);
            return d.RootElement.Clone();
        }

        var pmpJson = "{\"localPath\":" + System.Text.Json.JsonSerializer.Serialize(goodPmp) + ",\"name\":\"示例\"}";
        var r = ModBridge.Http.SourceResolver.Resolve(Body(pmpJson), true);
        Check("本机 .pmp 被接受", r.Source == goodPmp && r.IsLocal && r.Error is null, r.Error);
        Check("带中文/空格的路径也对", r.Source!.Contains("示例 Mod"), r.Source);

        r = ModBridge.Http.SourceResolver.Resolve(Body("{\"localPath\":\"Z:\\\\nope\\\\x.pmp\"}"), true);
        Check("不存在的路径被拒", r.Source is null && r.Error!.Contains("找不到"), r.Error);

        r = ModBridge.Http.SourceResolver.Resolve(Body($"{{\"localPath\":{System.Text.Json.JsonSerializer.Serialize(txtFile)}}}"), true);
        Check("非 mod 包的扩展名被拒", r.Source is null && r.Error!.Contains("不支持"), r.Error);

        r = ModBridge.Http.SourceResolver.Resolve(Body("{\"url\":\"https://example.com/a.pmp\"}"), true);
        Check("https 直链被接受", !r.IsLocal && r.Source == "https://example.com/a.pmp", r.Error);

        r = ModBridge.Http.SourceResolver.Resolve(Body("{\"url\":\"ftp://example.com/a.pmp\"}"), true);
        Check("非 http/https 被拒", r.Source is null && r.Error!.Contains("http/https"), r.Error);

        r = ModBridge.Http.SourceResolver.Resolve(Body("{\"url\":\"javascript:alert(1)\"}"), true);
        Check("javascript: 被拒（防注入）", r.Source is null, r.Error);

        r = ModBridge.Http.SourceResolver.Resolve(Body("{\"url\":\"https://evil.example/x.pmp\"}"), false);
        Check("白名单模式拒绝陌生域名", r.Source is null && r.Error!.Contains("不受信任"), r.Error);

        r = ModBridge.Http.SourceResolver.Resolve(Body("{\"url\":\"https://www.xivmodarchive.com/x.pmp\"}"), false);
        Check("白名单模式放行 xivmodarchive", r.Source is not null, r.Error);

        r = ModBridge.Http.SourceResolver.Resolve(Body("{\"url\":\"https://static.xivmodarchive.com/x.pmp\"}"), false);
        Check("子域名也放行", r.Source is not null, r.Error);

        r = ModBridge.Http.SourceResolver.Resolve(Body("{}"), true);
        Check("两个来源都没给 → 提示要 url 或 localPath",
            r.Source is null && r.Error!.Contains("url") && r.Error.Contains("localPath"), r.Error);

        r = ModBridge.Http.SourceResolver.Resolve(Body($"{{\"LOCALPATH\":{System.Text.Json.JsonSerializer.Serialize(goodPmp)}}}"), true);
        Check("字段名大小写不敏感", r.Source == goodPmp, r.Error);

        Check("GetBool 认 true/1/True",
            ModBridge.Http.SourceResolver.GetBool(Body("{\"a\":true}"), "a") == true
            && ModBridge.Http.SourceResolver.GetBool(Body("{\"a\":\"1\"}"), "a") == true
            && ModBridge.Http.SourceResolver.GetBool(Body("{\"a\":false}"), "a") == false
            && ModBridge.Http.SourceResolver.GetBool(Body("{}"), "a") is null);
        Check("GetInt 认数字字符串",
            ModBridge.Http.SourceResolver.GetInt(Body("{\"p\":7}"), "p") == 7
            && ModBridge.Http.SourceResolver.GetInt(Body("{\"p\":\"12\"}"), "p") == 12
            && ModBridge.Http.SourceResolver.GetInt(Body("{\"p\":\"x\"}"), "p") is null);

        r = ModBridge.Http.SourceResolver.Resolve(Body("{\"localPath\":\"  \"}"), true);
        Check("空白路径当成没给", r.Source is null && r.Error!.Contains("url"), r.Error);

        try { Directory.Delete(tmpDir, true); } catch { }

        // ---------- 12. 预览图写入（CoverWriter） ----------
        Console.WriteLine();
        Console.WriteLine("预览图写入 Penumbra mod（根目录 cover.webp + cover.<ext> + images\\_MetaImage + meta.json 的 Image）：");
        var root = Path.Combine(Path.GetTempPath(), "modbridge_cover_test");
        try { Directory.Delete(root, true); } catch { }
        Directory.CreateDirectory(root);

        string MakeMod(string name, string metaJson, bool bom = false)
        {
            var dir = Path.Combine(root, name);
            Directory.CreateDirectory(dir);
            var bytes = new System.Text.UTF8Encoding(bom).GetBytes(metaJson);
            File.WriteAllBytes(Path.Combine(dir, "meta.json"), bytes);
            return dir;
        }
        string jpgLater() => MakeImg("c_later.jpg", ".jpg");
        string MakeImg(string name, string ext)
        {
            var f = Path.Combine(root, name);
            // 1x1 PNG / 假 jpg 都行，这里只当文件搬运
            File.WriteAllBytes(f, ext switch
            {
                ".png"  => Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/AF/6lwAAAAASUVORK5CYII="),
                ".webp" => Convert.FromBase64String("UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEAAUAmJaQAA3AA/v89WAAAAA=="),  // 1x1 真 WebP
                _       => new byte[] { 0xFF, 0xD8, 0xFF, 0xE0, 1, 2, 3, 4, 5 },
            });
            return f;
        }

        // a) 正常写入：Image 被设置，其它字段保留
        var m1 = MakeMod("m1", "{\"FileVersion\":4,\"Name\":\"测试mod\",\"Author\":\"作者\",\"Image\":\"\",\"ModTags\":[]}");
        var cover = MakeImg("cover.png", ".png");
        var cv1 = ModBridge.Http.CoverWriter.Apply(m1, cover);
        Check("写入成功", cv1.Ok && !cv1.Skipped, cv1.Error);
        Check("返回的相对路径符合约定", cv1.RelPath == "images\\_MetaImage.png", cv1.RelPath);
        Check("图片落在 images\\_MetaImage.png", File.Exists(Path.Combine(m1, "images", "_MetaImage.png")));
        var meta1 = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(Path.Combine(m1, "meta.json")))!;
        Check("meta.json 的 Image 已指向它", meta1["Image"]!.GetValue<string>() == "images\\_MetaImage.png",
            meta1["Image"]!.GetValue<string>());
        Check("其它字段没丢", meta1["Name"]!.GetValue<string>() == "测试mod"
            && meta1["Author"]!.GetValue<string>() == "作者"
            && meta1["FileVersion"]!.GetValue<int>() == 4);

        // a2) 没有真 WebP 时**不伪造** cover.webp
        //     （老逻辑把 png/jpg 改名成 cover.webp → 认 cover.webp 的汉化版 Penumbra 解不出来 = "没图"，
        //      而且"已有 cover.webp 就跳过"会让之后所有补封面全部失效）
        Check("IsRealWebp：png 不是 webp", !ModBridge.Http.CoverWriter.IsRealWebp(cover));
        Check("没给真 WebP → 不写 cover.webp", !File.Exists(Path.Combine(m1, "cover.webp")));
        Check("改成写 cover.png（真扩展名）",
            File.Exists(Path.Combine(m1, "cover.png")) && cv1.CoverFile == "cover.png", cv1.CoverFile);
        Check("同时也写了 cover.<ext>（有人按固定名+扩展名找）", File.Exists(Path.Combine(m1, "cover.png")));
        var metaA = System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(Path.Combine(m1, "meta.json")))!;
        Check("meta.json 的 Image 仍指向 images\\_MetaImage.png",
            metaA["Image"]!.GetValue<string>() == "images\\_MetaImage.png");

        // a3) 管理器转好了真 WebP → cover.webp 用那一份
        var webpSrc = MakeImg("real.webp", ".webp");   // ★ 真 WebP（假 webp 现在会被拒）
        var mW = MakeMod("mw", "{\"Name\":\"webp\"}");
        var cvW = ModBridge.Http.CoverWriter.Apply(mW, jpgLater(), webpSrc);
        Check("给了 coverWebpPath → cover.webp 用它",
            cvW.Ok && cvW.CoverFile == "cover.webp"
            && File.ReadAllBytes(Path.Combine(mW, "cover.webp")).SequenceEqual(File.ReadAllBytes(webpSrc)), cvW.Error);

        // a4) 已有 cover.webp 但是**伪装的**（内容不是 WebP）→ 不能再无脑跳过（那正是"补了也没用"的死锁）
        var mHW = MakeMod("mhw", "{\"Name\":\"假 cover.webp\"}");
        File.WriteAllBytes(Path.Combine(mHW, "cover.webp"), new byte[] { 9, 9, 9 });
        var cvHW = ModBridge.Http.CoverWriter.Apply(mHW, cover);
        Check("伪 cover.webp 不再被当有效封面跳过", cvHW.Ok && !cvHW.Skipped, cvHW.Error);
        Check("会明确报出来（Note）", !string.IsNullOrWhiteSpace(cvHW.Note), cvHW.Note);
        Check("照样补上 images\\_MetaImage.png", File.Exists(Path.Combine(mHW, "images", "_MetaImage.png")));

        // a4b) 给了真 WebP → 把伪装的那份**替换修好**（主人现场那批 mod 就靠这条修）
        var mFix = MakeMod("mfix", "{\"Name\":\"修好它\"}");
        File.WriteAllBytes(Path.Combine(mFix, "cover.webp"), new byte[] { 9, 9, 9 });
        var cvFix = ModBridge.Http.CoverWriter.Apply(mFix, cover, webpSrc);
        Check("真 WebP 来了 → 伪 cover.webp 被替换成真 WebP",
            cvFix.Ok && File.ReadAllBytes(Path.Combine(mFix, "cover.webp")).SequenceEqual(File.ReadAllBytes(webpSrc)), cvFix.Error);
        Check("替换后 IsRealWebp = true", ModBridge.Http.CoverWriter.IsRealWebp(Path.Combine(mFix, "cover.webp")));

        // a4c) 作者给的是**真 WebP** → 跳过、不动人家的图
        var mReal = MakeMod("mreal", "{\"Name\":\"作者的真 webp\"}");
        File.WriteAllBytes(Path.Combine(mReal, "cover.webp"), File.ReadAllBytes(webpSrc));
        var cvReal = ModBridge.Http.CoverWriter.Apply(mReal, cover);
        Check("真 cover.webp → 跳过（不覆盖作者的图）",
            cvReal.Skipped && cvReal.CoverFile == "cover.webp", cvReal.CoverFile);
        Check("原图没被改",
            File.ReadAllBytes(Path.Combine(mReal, "cover.webp")).SequenceEqual(File.ReadAllBytes(webpSrc)));
        Check("跳过后没写 images\\_MetaImage",
            !File.Exists(Path.Combine(mReal, "images", "_MetaImage.png")));

        // a4d) 没人给封面、文件夹里已有一个 cover.jpg（Penumbra 导入包时就是这样）
        //      → 不造假 cover.webp，改用 images\_MetaImage.jpg 出图
        var mSelf = MakeMod("mself", "{\"Name\":\"只有包内封面\"}");
        File.WriteAllBytes(Path.Combine(mSelf, "cover.jpg"), new byte[] { 0xFF, 0xD8, 0xFF, 0xE0 });
        var cvSelf = ModBridge.Http.CoverWriter.Apply(mSelf, null, null);
        Check("没人给封面也能补（用文件夹里已有的那个）→ 写 _MetaImage.jpg",
            cvSelf.Ok && File.Exists(Path.Combine(mSelf, "images", "_MetaImage.jpg")), cvSelf.Error);
        Check("不造假 cover.webp", !File.Exists(Path.Combine(mSelf, "cover.webp")));
        Check("原来的 cover.jpg 还在", File.Exists(Path.Combine(mSelf, "cover.jpg")));

        // a5) 根目录只有 cover.jpg（没有 cover.webp）→ 补 _MetaImage，但别动人家的 cover.jpg
        var mH = MakeMod("mh", "{\"Name\":\"只有 cover.jpg\"}");
        File.WriteAllBytes(Path.Combine(mH, "cover.jpg"), new byte[] { 7, 7, 7 });
        var cvH = ModBridge.Http.CoverWriter.Apply(mH, cover);
        Check("只有 cover.jpg → 补 images\\_MetaImage.png",
            cvH.Ok && File.Exists(Path.Combine(mH, "images", "_MetaImage.png")), cvH.Error);
        Check("不造假 cover.webp", !File.Exists(Path.Combine(mH, "cover.webp")));
        Check("人家的 cover.jpg 没被改",
            File.ReadAllBytes(Path.Combine(mH, "cover.jpg")).SequenceEqual(new byte[] { 7, 7, 7 }));

        // b) 带 BOM 的 meta.json 也能处理
        var m2 = MakeMod("m2", "{\"Name\":\"bom\",\"Image\":\"\"}", bom: true);
        var cv2 = ModBridge.Http.CoverWriter.Apply(m2, cover);
        Check("BOM 的 meta.json 也能改", cv2.Ok, cv2.Error);
        Check("写回后不再带 BOM",
            File.ReadAllBytes(Path.Combine(m2, "meta.json"))[0] != 0xEF);

        // c) 原本就有图且文件在 → 不覆盖（尊重包自带封面）
        var m3 = MakeMod("m3", "{\"Name\":\"已有图\",\"Image\":\"images\\\\_MetaImage.png\"}");
        Directory.CreateDirectory(Path.Combine(m3, "images"));
        File.WriteAllBytes(Path.Combine(m3, "images", "_MetaImage.png"), new byte[] { 1, 2, 3 });
        var before = File.ReadAllBytes(Path.Combine(m3, "images", "_MetaImage.png"));
        var cv3 = ModBridge.Http.CoverWriter.Apply(m3, cover);
        Check("有 Image 但没 cover.webp → 不造假 cover.webp，也不动原来的图",
            cv3.Ok && !File.Exists(Path.Combine(m3, "cover.webp")), cv3.Error);
        Check("没有覆盖原来的图", File.ReadAllBytes(Path.Combine(m3, "images", "_MetaImage.png")).SequenceEqual(before));
        Check("也没改它的 Image",
            System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(Path.Combine(m3, "meta.json")))!["Image"]!
                .GetValue<string>() == "images\\_MetaImage.png");

        // d) meta.json 里写了 Image 但文件不在 → 应该补上
        var m4 = MakeMod("m4", "{\"Name\":\"图丢了\",\"Image\":\"images\\\\_MetaImage.png\"}");
        var cv4 = ModBridge.Http.CoverWriter.Apply(m4, cover);
        Check("文件缺失时重新写入", cv4.Ok, cv4.Error);

        // e) jpg 封面 → 用 jpg 命名
        var jpg = MakeImg("c.jpg", ".jpg");
        var m5 = MakeMod("m5", "{\"Name\":\"jpg\"}");
        var cv5 = ModBridge.Http.CoverWriter.Apply(m5, jpg);
        Check("jpg 用 _MetaImage.jpg", cv5.Ok && cv5.RelPath == "images\\_MetaImage.jpg", cv5.RelPath);
        Check("jpg 文件在", File.Exists(Path.Combine(m5, "images", "_MetaImage.jpg")));

        // f) 换了扩展名时清掉同名的旧文件（可复现路径：meta 指向的图缺失 + 有旧扩展名残留）
        var m5b = MakeMod("m5b", System.Text.Json.JsonSerializer.Serialize(new Dictionary<string, string> { ["Name"] = "stale", ["Image"] = @"images\_MetaImage.png" }));
        Directory.CreateDirectory(Path.Combine(m5b, "images"));
        File.WriteAllBytes(Path.Combine(m5b, "images", "_MetaImage.jpg"), new byte[] { 9 });   // 旧残留
        var cvF = ModBridge.Http.CoverWriter.Apply(m5b, cover);
        Check("补图时清掉旧扩展名残留",
            cvF.Ok && !File.Exists(Path.Combine(m5b, "images", "_MetaImage.jpg"))
            && File.Exists(Path.Combine(m5b, "images", "_MetaImage.png")), cvF.Error);

        // g) 错误路径（都用"本来没有图"的新 mod，否则会走 skip 分支）
        var mErr = MakeMod("mErr", System.Text.Json.JsonSerializer.Serialize(new Dictionary<string, string> { ["Name"] = "无图" }));
        Check("没给封面 → 有原因",
            (ModBridge.Http.CoverWriter.Apply(mErr, null).Error ?? "").Contains("coverPath"));
        Check("封面文件不存在 → 有原因",
            (ModBridge.Http.CoverWriter.Apply(mErr, Path.Combine(root, "nope.png")).Error ?? "").Contains("不存在"));
        File.WriteAllText(Path.Combine(root, "x.txt"), "no");
        Check("txt 封面被拒",
            (ModBridge.Http.CoverWriter.Apply(mErr, Path.Combine(root, "x.txt")).Error ?? "").Contains("图片"));
        var mNoMeta = Path.Combine(root, "mNoMeta");
        Directory.CreateDirectory(mNoMeta);
        Check("没有 meta.json → 有原因",
            (ModBridge.Http.CoverWriter.Apply(mNoMeta, cover).Error ?? "").Contains("meta.json"));
        Check("文件夹不存在 → 有原因",
            (ModBridge.Http.CoverWriter.Apply(Path.Combine(root, "nope"), cover).Error ?? "").Contains("不存在"));

        // g2) 已经有**真 WebP** 封面时：即使传了封面也不动（尊重包自带）
        var cvSkip = ModBridge.Http.CoverWriter.Apply(mReal, cover);
        Check("已有真 WebP cover.webp 时再传封面 → 仍然 skip", cvSkip.Skipped, cvSkip.Error);
        // g2b) 但假货（非 WebP 内容）**不能**让它 skip —— 否则补封面永远补不上
        var cvSkipFake = ModBridge.Http.CoverWriter.Apply(mHW, cover);
        Check("假 cover.webp → 不 skip（能修）", !cvSkipFake.Skipped, cvSkipFake.Error);

        // h) 坏 JSON 不能把原文件写坏
        var mBad = MakeMod("mBad", "{ not json ");
        var badBefore = File.ReadAllText(Path.Combine(mBad, "meta.json"));
        var cvBad = ModBridge.Http.CoverWriter.Apply(mBad, cover);
        Check("坏 JSON → 报错且不改原文件",
            cvBad.Error is not null && File.ReadAllText(Path.Combine(mBad, "meta.json")) == badBefore);

        // ---------- 13. 兜底：从 .pmp 旁边猜封面 ----------
        Console.WriteLine();
        Console.WriteLine("兜底：管理器没给封面时，在包旁边找同名图片（GuessFromPackage）：");
        var gp = Path.Combine(root, "guess");
        Directory.CreateDirectory(gp);
        var pmp = Path.Combine(gp, "1.[Arte] Neolithe Bodystocking.pmp");
        File.WriteAllBytes(pmp, new byte[] { 1, 2, 3 });
        Check("旁边没有图片 → null", ModBridge.Http.CoverWriter.GuessFromPackage(pmp) is null);
        var jpgSib = Path.Combine(gp, "1.[Arte] Neolithe Bodystocking.jpg");
        File.WriteAllBytes(jpgSib, new byte[] { 0xFF, 0xD8 });
        Check("旁边有同名 jpg → 找到它", ModBridge.Http.CoverWriter.GuessFromPackage(pmp) == jpgSib,
            ModBridge.Http.CoverWriter.GuessFromPackage(pmp));
        var pngSib = Path.Combine(gp, "other.png");
        var pmp2 = Path.Combine(gp, "other.pmp");
        File.WriteAllBytes(pmp2, new byte[] { 1 });
        File.WriteAllBytes(pngSib, new byte[] { 0x89, 0x50 });
        Check("png 也认", ModBridge.Http.CoverWriter.GuessFromPackage(pmp2) == pngSib);
        Check("包不存在 → null", ModBridge.Http.CoverWriter.GuessFromPackage(Path.Combine(gp, "nope.pmp")) is null);
        Check("路径为空 → null", ModBridge.Http.CoverWriter.GuessFromPackage(null) is null);
        Check("不是 .pmp 也照样找同名（比如 .zip）",
            ModBridge.Http.CoverWriter.GuessFromPackage(pmp) == jpgSib);
        // 包里面自带 cover.webp（Heliosphere 的包全带）→ 从包里抽出来
        var pmpZip = Path.Combine(gp, "hascover.pmp");
        using (var zs = File.Create(pmpZip))
        using (var za = new System.IO.Compression.ZipArchive(zs, System.IO.Compression.ZipArchiveMode.Create))
        {
            var e1 = za.CreateEntry("cover.webp");
            using (var w = e1.Open()) w.Write(File.ReadAllBytes(MakeImg("ziptmp_real.webp", ".webp")));
            var e2 = za.CreateEntry("meta.json");
            using (var w = new StreamWriter(e2.Open())) w.Write("{\"Name\":\"x\"}");
        }
        var inZip = ModBridge.Http.CoverWriter.GuessFromPackage(pmpZip);
        Check("包内自带 cover.webp → 能抽出来", inZip is not null
            && File.ReadAllBytes(inZip).SequenceEqual(File.ReadAllBytes(MakeImg("ziptmp_real.webp", ".webp"))), inZip);
        var mZip = MakeMod("mzip", "{\"Name\":\"zip\"}");
        var cvZip = ModBridge.Http.CoverWriter.Apply(mZip, null, inZip);
        Check("只有包内封面也能写进 mod（cover.webp）",
            cvZip.Ok && File.Exists(Path.Combine(mZip, "cover.webp")), cvZip.Error);
        // 找到之后能不能一条龙写进 mod
        var mG = MakeMod("mG", System.Text.Json.JsonSerializer.Serialize(
            new Dictionary<string, string> { ["Name"] = "guess" }));
        var found = ModBridge.Http.CoverWriter.GuessFromPackage(pmp);
        var cvG = ModBridge.Http.CoverWriter.Apply(mG, found);
        Check("猜到的封面能直接写进 mod", cvG.Ok && cvG.RelPath == "images\\_MetaImage.jpg", cvG.Error);

        // ---------- 13. Heliosphere 目录命名（反编译它的插件 + 用户真实目录名验证） ----------
        Console.WriteLine();
        Console.WriteLine("Heliosphere 目录命名（hs-名字-版本-Sqids码）：");
        Check("encode(13476) == gWc2（My Boyfriend's Shirt 的真实目录名）",
            ModBridge.Http.HelioNaming.Encode(13476) == "gWc2", ModBridge.Http.HelioNaming.Encode(13476));
        Check("encode(18921) == EXXk（Trigun 的真实目录名）",
            ModBridge.Http.HelioNaming.Encode(18921) == "EXXk", ModBridge.Http.HelioNaming.Encode(18921));
        const string trigunName = "Trigun [Tre, TBSE, Resonecho, Neolithe, Rosaline, Muse, Pythia, Dionys, YAB, Rue, Lavabod]";
        var trigunDir = ModBridge.Http.HelioNaming.DirectoryName(trigunName, "1.0.0", 18921);
        Check("目录名拼装与真实目录完全一致", trigunDir == "hs-" + trigunName + "-1.0.0-EXXk", trigunDir);
        Check("字母表 62 位", ModBridge.Http.HelioNaming.Alphabet.Length == 62);
        Check("非法字符被换成 '-'",
            ModBridge.Http.HelioNaming.Sanitize("a/b:c*d?e").IndexOf('/') < 0
            && ModBridge.Http.HelioNaming.Sanitize("a/b:c*d?e").Contains('-'));

        var hpDir = Path.Combine(root, "heliopack");
        Directory.CreateDirectory(hpDir);
        string MakePmp(string name, string helioJson)
        {
            var f = Path.Combine(hpDir, name);
            using var fs = File.Create(f);
            using var za = new System.IO.Compression.ZipArchive(fs, System.IO.Compression.ZipArchiveMode.Create);
            var m = za.CreateEntry("meta.json");
            using (var w = new StreamWriter(m.Open())) w.Write("{\"FileVersion\":4,\"Name\":\"原来的名字\",\"Author\":\"作者\"}");
            var h = za.CreateEntry("heliosphere.json");
            using (var w = new StreamWriter(h.Open())) w.Write(helioJson);
            var x = za.CreateEntry("cover.webp");
            using (var w = new StreamWriter(x.Open())) w.Write("WEBP");
            return f;
        }
        var pmpV4 = MakePmp("v4.pmp",
            "{\"MetaVersion\":4,\"Name\":\"Trigun [Tre, TBSE]\",\"Version\":\"1.0.0\",\"ShortVariantId\":18921}");
        var v4 = ModBridge.Http.HelioNaming.FromPackage(pmpV4);
        Check("v4 包能读出 heliosphere.json", v4.HasValue, "null");
        Check("算出的目录名符合规范",
            v4.HasValue && v4.Value.DirectoryName == "hs-Trigun [Tre, TBSE]-1.0.0-EXXk",
            v4.HasValue ? v4.Value.DirectoryName : "null");
        Check("显示名是 [HS] 开头", v4.HasValue && v4.Value.DisplayName == "[HS] Trigun [Tre, TBSE]");

        var pmpV3 = MakePmp("v3.pmp", "{\"MetaVersion\":3,\"Name\":\"老包\",\"Version\":\"1.0.0\"}");
        Check("v3 包（没有 ShortVariantId）→ 算不出，返回 null",
            ModBridge.Http.HelioNaming.FromPackage(pmpV3) is null);

        var patched = ModBridge.Http.HelioNaming.PatchPackageName(pmpV4, "hs-Trigun [Tre, TBSE]-1.0.0-EXXk");
        Check("能复制出一个改了 meta.json Name 的包", patched is not null && File.Exists(patched), patched);
        if (patched is not null)
        {
            using var z = System.IO.Compression.ZipFile.OpenRead(patched);
            string Read(string n)
            {
                using var st = z.GetEntry(n)!.Open();
                using var r = new StreamReader(st);
                return r.ReadToEnd();
            }
            Check("新包 meta.json 的 Name 已改成目录名",
                System.Text.Json.Nodes.JsonNode.Parse(Read("meta.json"))!["Name"]!.GetValue<string>()
                    == "hs-Trigun [Tre, TBSE]-1.0.0-EXXk");
            Check("其它字段没丢（Author 还在）",
                System.Text.Json.Nodes.JsonNode.Parse(Read("meta.json"))!["Author"]!.GetValue<string>() == "作者");
            Check("heliosphere.json 原样保留", Read("heliosphere.json").Contains("18921"));
            Check("cover.webp 也带过去了", z.GetEntry("cover.webp") is not null);
        }

        var dispDir = Path.Combine(root, "disp");
        Directory.CreateDirectory(dispDir);
        File.WriteAllText(Path.Combine(dispDir, "meta.json"), "{\"Name\":\"hs-xxx\",\"Author\":\"a\"}");
        Check("装完能把显示名改回来", ModBridge.Http.HelioNaming.SetDisplayName(dispDir, "[HS] 好看的名字"));
        Check("改完 meta.json 其它字段保留",
            System.Text.Json.Nodes.JsonNode.Parse(File.ReadAllText(Path.Combine(dispDir, "meta.json")))!["Author"]!
                .GetValue<string>() == "a");

        // ---------- 14. 自绘封面：找能解码的封面（CoverLocator） ----------
        Console.WriteLine();
        Console.WriteLine("自绘封面：找能解码的封面文件（CoverLocator）：");
        var clDir = Path.Combine(root, "cl");
        Directory.CreateDirectory(clDir);
        Check("啥都没有 → null", ModBridge.Http.CoverLocator.FindDrawable(clDir) is null);
        var clMeta = Path.Combine(clDir, "images");
        Directory.CreateDirectory(clMeta);
        File.WriteAllBytes(Path.Combine(clMeta, "_MetaImage.png"), new byte[] { 1 });
        Check("优先 images\\_MetaImage.png",
            ModBridge.Http.CoverLocator.FindDrawable(clDir)!.EndsWith("_MetaImage.png"),
            ModBridge.Http.CoverLocator.FindDrawable(clDir));
        File.WriteAllBytes(Path.Combine(clDir, "cover.jpg"), new byte[] { 1 });
        Check("有 _MetaImage 时仍优先它",
            ModBridge.Http.CoverLocator.FindDrawable(clDir)!.EndsWith("_MetaImage.png"));
        File.Delete(Path.Combine(clMeta, "_MetaImage.png"));
        Check("没有 _MetaImage 时用根目录 cover.jpg",
            ModBridge.Http.CoverLocator.FindDrawable(clDir)!.EndsWith("cover.jpg"));
        File.WriteAllBytes(Path.Combine(clDir, "cover.webp"), new byte[] { 1 });
        File.Delete(Path.Combine(clDir, "cover.jpg"));
        Check("只有 cover.webp → 不画（Dalamud 解不了 WebP）",
            ModBridge.Http.CoverLocator.FindDrawable(clDir) is null);
        Check("普通目录不算 Heliosphere mod",
            !ModBridge.Http.CoverLocator.IsHeliosphereMod("普通名字", clDir));
        var hsDir = Path.Combine(root, "hsmod");
        Directory.CreateDirectory(hsDir);
        File.WriteAllText(Path.Combine(hsDir, "heliosphere.json"), "{}");
        Check("hs- 开头 + heliosphere.json → 算 Heliosphere mod",
            ModBridge.Http.CoverLocator.IsHeliosphereMod("hs-xxx", hsDir));
        Check("只是 hs- 开头但没 json → 不算",
            !ModBridge.Http.CoverLocator.IsHeliosphereMod("hs-xxx", clDir));

        var mDraw = MakeMod("mdraw", "{\"Name\":\"draw\"}");
        var drawJpg = MakeImg("d.jpg", ".jpg");
        var fakeWebp = MakeImg("d2.webp", ".jpg");
        var cvDraw = ModBridge.Http.CoverWriter.Apply(mDraw, fakeWebp, null, drawJpg);
        Check("给了 coverDrawPath 时 images\\_MetaImage 用那份（jpg）",
            cvDraw.Ok && File.Exists(Path.Combine(mDraw, "images", "_MetaImage.jpg")), cvDraw.Error);

        try { Directory.Delete(root, true); } catch { }

        Console.WriteLine();
        Console.WriteLine(_fails == 0 ? "全部通过 ✔" : $"{_fails} 项失败 ✘");
        return _fails == 0 ? 0 : 1;
    }
}
