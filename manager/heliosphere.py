# -*- coding: utf-8 -*-
"""Heliosphere（heliosphere.app）Mod 站：读页面信息 + 下载 mod（PMP）+ 取封面。

为什么单独一个模块（2026-09-30，主人要求「把 heliosphere.app 也列入管理中来，
从该站上下载 mod 和封面图」）：

实测结论（一次问清，别再靠猜）：

1. **页面**是 SvelteKit，SSR 里内嵌了 `/api/graphql` 的响应 —— **匿名就能读到**
   名称 / 作者 / 简介 / 标签 / Affects(影响替换) / 版本 / 更新时间 / 下载大小 /
   封面图 id / versionId。一次 GET 页面全拿到，**不需要登录、不需要浏览器、没有 Cloudflare**。
   （和 XIVModArchive 完全不同 —— 那边 NSFW 必须真浏览器。）

2. **下载**：官方 PMP 是**浏览器里客户端打包**的
   （`_app/immutable/workers/pmpDownloader.worker-*.js` 这个 SharedWorker）：
     GraphQL `getVersion(id)` → `neededFiles{baseUri, files}` → 逐个文件下（zstd 压缩）
     → 重压 → 打成 zip → 包内 `heliosphere.json` + `cover.jpg` + `files/**` + `meta.json`
   这里照同一规则用**纯 Python** 复刻（7-Zip 解 zstd + zipfile 打包）。
   正确性证据：与官方 worker 的产物逐条比对 —— 16 个条目名一致、
   13 个文件内容 sha256 全部相同、`meta.json` 深度相等（只有 zip 内条目顺序的差别）。

3. **封面**：`https://heliosphere.app/api/web/package/<包id>/image/<图id>`
   （匿名可取，实测 image/webp 268 KB；官方把它写进包里的名字是 `cover.jpg`，
   内容是 WebP —— Heliosphere 系一贯如此）。

⚠ 依赖：解 zstd 需要一个能解 .zst 的程序（本机 `C:/Program Files/7-Zip/7z.exe`，
   或 PATH 里的 7z/zstd —— 见 `zstd_exe()`）。纯标准库 Python 3.12 没有 zstd。
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile

import mod_manager as mm

MOD_BASE = "https://heliosphere.app"
GQL_URL = MOD_BASE + "/api/graphql"
DATA_BASE = "https://data.heliosphere.app/files/"
IMG_URL = MOD_BASE + "/api/web/package/%s/image/%s"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")

SEVEN_ZIP_CANDIDATES = (
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
)

# 从官方 worker 里原样抄出来的查询（字段一个不少，免得自己裁字段裁出「缺字段」的坑）
VERSION_QUERY = """\
query Download($versionId: UUID!) {
    getVersion(id: $versionId) {
        version
        batched
        batches
        defaultPreferredItemIds
        metaInfo {
            identifier
            description
            url
            requiredFeatures
            pageNames
            __typename
        }
        defaultOption {
            fileSwaps
            __typename
        }
        variant {
            id
            name
            package {
                id
                name
                tagline
                description
                tags {
                    slug
                    __typename
                }
                user {
                    id
                    visibleName
                    __typename
                }
                images {
                    id
                    __typename
                }
                __typename
            }
            __typename
        }
        groups {
            standard {
                name
                displayName
                description
                priority
                defaultSettings
                layout
                condition
                page
                penumbraId
                parentSetting
                groupType
                originalIndex
                options {
                    hsId
                    name
                    displayName
                    description
                    priority
                    penumbraId
                    layout
                    condition
                    color
                    fileSwaps
                    manipulations
                    isDefault
                    __typename
                }
                __typename
            }
            imc {
                name
                displayName
                description
                priority
                defaultSettings
                layout
                condition
                page
                penumbraId
                parentSetting
                groupType
                identifier
                allVariants
                onlyAttributes
                defaultEntry
                originalIndex
                options {
                    name
                    displayName
                    description
                    penumbraId
                    layout
                    condition
                    color
                    isDisableSubMod
                    attributeMask
                    __typename
                }
                __typename
            }
            combining {
                name
                displayName
                description
                priority
                defaultSettings
                layout
                condition
                page
                penumbraId
                parentSetting
                groupType
                originalIndex
                options {
                    name
                    displayName
                    description
                    penumbraId
                    layout
                    condition
                    color
                    isDefault
                    __typename
                }
                containers {
                    hsId
                    name
                    gamePaths
                    manipulations
                    fileSwaps
                    __typename
                }
                __typename
            }
            __typename
        }
        neededFiles(downloadKind: INSTALL) {
            baseUri
            files
            defaultManipulations
            __typename
        }
        __typename
        id
    }
}
"""


# --------------------------------------------------------------- 小工具
def is_helio(addr) -> bool:
    return "heliosphere" in str(addr or "").lower()


def modid_of(addr) -> str:
    """从地址里取 shortId（形如 qtbfxc99ss7a5arzjmv83aanwg）"""
    m = re.search(r"/mod/([A-Za-z0-9]+)", str(addr or ""))
    return m.group(1) if m else ""


def page_url(modid) -> str:
    return "%s/mod/%s" % (MOD_BASE, modid)


def zstd_exe(cfg=None) -> str:
    """能解 zstd 的程序：先看配置里的 sevenzip，再找 7-Zip 默认位置，最后看 PATH"""
    cands = []
    if cfg:
        cands.append(str(cfg.get("sevenzip") or ""))
    cands += list(SEVEN_ZIP_CANDIDATES)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    for name in ("7z", "7zz", "zstd"):
        p = shutil.which(name)
        if p:
            return p
    return ""


def have_zstd(cfg=None) -> bool:
    return bool(zstd_exe(cfg))


def _headers(extra=None) -> dict:
    h = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
         "Referer": MOD_BASE + "/", "Origin": MOD_BASE}
    if extra:
        h.update(extra)
    return h


def _get(url, timeout=40, retries=3, extra=None, on_bytes=None, should_cancel=None) -> bytes:
    """下载到内存（小文件用），带重试；on_bytes(本块, 累计) 用于进度"""
    last = None
    for i in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers=_headers(extra))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                total = int(r.headers.get("Content-Length") or 0)
                buf, got = [], 0
                while True:
                    if should_cancel and should_cancel():
                        raise mm.BackupCancelled()
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    buf.append(chunk)
                    got += len(chunk)
                    if on_bytes:
                        on_bytes(got, total)
                # ★ 必须核对长度：网络抖一下会「读到一半就 EOF」，此时 read() 只是返回空、
                #   不抛异常 —— 以前会把这半截字节当成下载成功，交给 7z 时才炸
                #   （exe 实测：ERROR: Unexpected end of data）。不符就走重试。
                if total and got != total:
                    raise RuntimeError("下载不完整（%d/%d 字节）" % (got, total))
                return b"".join(buf)
        except mm.BackupCancelled:
            raise
        except Exception as e:                      # 网络抖动/TLS 偶发
            last = e
            if i < retries - 1:
                time.sleep(0.8 * (i + 1))
    raise RuntimeError("下载失败：%s" % str(last)[:120])


# --------------------------------------------------------------- 页面信息
def _iter_ssr_gql(html):
    """页面 SSR 里内嵌的 /api/graphql 响应（Houdini/SvelteKit 的 fetch 结果）"""
    for m in re.finditer(r'<script[^>]*data-sveltekit-fetched[^>]*data-url="/api/graphql"[^>]*>(.*?)</script>',
                         html or "", re.S):
        raw = m.group(1).strip()
        try:
            outer = json.loads(raw)
        except Exception:
            continue
        body = outer.get("body") if isinstance(outer, dict) else None
        if not body:
            continue
        try:
            j = json.loads(body)
        except Exception:
            continue
        yield j


def parse_page(html) -> dict:
    """从 Mod 页 HTML 里解析出这条 Mod 的全部信息（匿名可读）。"""
    out = {"ok": False, "error": "", "modid": "", "package_id": "", "image_id": "",
           "version_id": "", "variant_id": "", "variant_name": "", "version": "",
           "name": "", "author": "", "tagline": "", "desc": "", "tags": [], "affects": "",
           "updated": "", "released": "", "downloads": 0, "size_mb": 0.0, "meta_ok": False,
           "source": ""}
    pkg = None
    for j in _iter_ssr_gql(html):
        p = ((j.get("data") or {}).get("package")) if isinstance(j, dict) else None
        if p:
            pkg = p
            break
    if not pkg:
        return out                            # 交给调用方走正则兜底
    out["package_id"] = str(pkg.get("id") or "")
    out["name"] = str(pkg.get("name") or "")
    out["tagline"] = str(pkg.get("tagline") or "")
    out["desc"] = str(pkg.get("description") or "")
    out["author"] = str(((pkg.get("user") or {}).get("visibleName"))
                        or ((pkg.get("user") or {}).get("username")) or "")
    out["downloads"] = int(pkg.get("downloads") or 0)
    out["updated"] = _iso_local(pkg.get("updatedAt") or "")
    out["released"] = _iso_local(pkg.get("createdAt") or "")
    tgs = [str((t or {}).get("slug") or "") for t in (pkg.get("tags") or [])]
    out["tags"] = [t for t in dict.fromkeys(tgs) if t][:40]
    imgs = pkg.get("images") or []
    if imgs:
        out["image_id"] = str((imgs[0] or {}).get("id") or "")
    vs = pkg.get("variants") or []
    if vs:
        v0 = vs[0] or {}
        out["variant_id"] = str(v0.get("id") or "")
        out["variant_name"] = str(v0.get("name") or "")
        ver = (v0.get("versions") or [])
        if ver:
            vv = ver[0] or {}
            out["version_id"] = str(vv.get("id") or "")
            out["version"] = str(vv.get("version") or "")
            aff = [str(x) for x in (vv.get("affects") or []) if x]
            out["affects"] = mm.norm_affects(", ".join(aff)) if aff else ""
            out["updated"] = _iso_local(vv.get("createdAt") or "") or out["updated"]
            try:
                out["size_mb"] = round(int(vv.get("downloadSize") or 0) / 1048576.0, 1)
            except (TypeError, ValueError):
                out["size_mb"] = 0.0
    out["ok"] = bool(out["name"] and (out["version_id"] or out["version"]))
    out["meta_ok"] = bool(out["tags"] or out["affects"])
    out["source"] = "heliosphere"
    if not out["ok"]:
        out["error"] = "页面里没找到这条 Mod 的信息（可能已删除/隐藏）"
    return out


def _iso_local(text) -> str:
    """2026-09-21T05:36:25.342711+00:00 → 本机时区字符串（复用 mm 的算法）"""
    try:
        return mm._helio_iso(str(text or ""))
    except Exception:
        return ""


def fetch_page_info(addr, timeout=40) -> dict:
    """读这条 Mod 在 heliosphere 上的信息（GET 页面解析 SSR，匿名即可）"""
    mid = modid_of(addr)
    if not mid:
        return {"ok": False, "error": "不是 heliosphere 的 Mod 链接（地址里要有 /mod/<id>）",
                "modid": "", "source": ""}
    try:
        html = _get(page_url(mid), timeout=timeout).decode("utf-8", "replace")
    except Exception as e:
        return {"ok": False, "error": "页面读取失败：%s" % str(e)[:80], "modid": mid, "source": ""}
    info = parse_page(html)
    info["modid"] = mid
    if not info.get("ok"):                    # 兜底：老的 flat 正则（SSR 结构变了也能凑出时间/版本）
        info = _fallback_from_html(html, info)
    return info


def _fallback_from_html(html, info) -> dict:
    """SSR 结构万一变了：退回「转义 JSON + 正则」的老办法拿版本/时间/标签"""
    try:
        flat = str(html).replace('\\"', '"').replace("\\/", "/")
        v = re.search(r'"version"\s*:\s*"([^"]+)"', flat)
        up = re.search(r'"updatedAt"\s*:\s*"([^"]+)"', flat)
        rel = re.search(r'"releasedAt"\s*:\s*"([^"]+)"', flat)
        tgs = re.findall(r'\{"category":(?:true|false),"slug":"([^"]+)"', flat)
        aff = re.search(r'"affects"\s*:\s*\[([^\]]*)\]', flat)
        dl = re.search(r'"downloadSize"\s*:\s*(\d+)', flat)
        if v:
            info["version"] = v.group(1)
        if tgs:
            info["tags"] = [x.strip() for x in dict.fromkeys(tgs) if x.strip()][:40]
        if aff is not None:
            items = [mm.unescape(x).strip() for x in re.findall(r'"([^"]*)"', aff.group(1))]
            info["affects"] = ", ".join(x for x in items if x)
        iso = (up.group(1) if up else (rel.group(1) if rel else ""))
        if iso:
            info["updated"] = _iso_local(iso)
        if dl and dl.group(1).isdigit():
            info["size_mb"] = round(int(dl.group(1)) / 1048576.0, 1)
        info["meta_ok"] = bool(info["tags"] or info["affects"])
        if info.get("version") or info.get("updated"):
            info["ok"] = True
            info["error"] = ""
            info["source"] = "heliosphere-flat"
    except Exception as e:
        info["error"] = info.get("error") or ("解析失败：%s" % str(e)[:60])
    return info


def cover_url(info) -> str:
    pid, iid = str((info or {}).get("package_id") or ""), str((info or {}).get("image_id") or "")
    return IMG_URL % (pid, iid) if (pid and iid) else ""


def cover_bytes(info, timeout=60) -> bytes:
    """取封面字节（WebP）。地址不对/取不到返回 b""（调用方决定兜底）。

    地址来源：① package_id + image_id（页面解析的结果）② 直接用 info["cover"]
    —— 调用方手上常常只有后者（比如入库流程里的页面信息字典）。
    """
    u = cover_url(info) or str((info or {}).get("cover") or "")
    if not u:
        return b""
    try:
        return _get(u, timeout=timeout, retries=2)
    except Exception as e:
        mm.log("heliosphere 封面下载失败：%s" % str(e)[:100])
        return b""


# --------------------------------------------------------------- GraphQL
def _gql(query, variables, timeout=60, retries=3) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    last = None
    for i in range(max(1, retries)):
        try:
            req = urllib.request.Request(GQL_URL, data=body, headers=_headers({
                "Content-Type": "application/json",
                "Accept": "application/graphql-response+json, application/json"}))
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            if i < retries - 1:
                time.sleep(0.8 * (i + 1))
    raise RuntimeError("GraphQL 请求失败：%s" % str(last)[:120])


# --------------------------------------------------------------- zstd / 打包
def unzstd(cfg, data: bytes, tmp_dir) -> bytes:
    """把 zstd 字节解成原始字节（7-Zip `e -so`；没有工具就报可读的错）"""
    exe = zstd_exe(cfg)
    if not exe:
        raise RuntimeError("没有找到能解 zstd 的程序（需要 7-Zip：https://7-zip.org/）——"
                           "装好后重试，或到「设置」里填 7z.exe 的路径")
    d = str(tmp_dir)
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, "_hszst.tmp")
    with open(src, "wb") as fh:
        fh.write(data)
    try:
        if os.path.basename(exe).lower().startswith("zstd"):
            p = subprocess.run([exe, "-d", "-c", "-q", src], capture_output=True,
                               creationflags=mm.console_flags())
        else:
            # ★ creationflags：7-Zip 是控制台程序，不加这个，用户在 windowed 版里
            #   每下一个文件就会看到一个黑框闪一下（一个 mod 十几个文件 = 满屏闪）
            p = subprocess.run([exe, "e", "-so", "-y", src], capture_output=True,
                               creationflags=mm.console_flags())
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError("解压失败（%s，输入 %d 字节）：%s"
                               % (os.path.basename(exe), len(data),
                                  (p.stderr or b"")[:160].decode("utf-8", "replace").strip()))
        return p.stdout
    finally:
        try:
            os.remove(src)
        except OSError:
            pass


def _clean_seg(s) -> str:
    """官方 Ol()：Windows 非法字符换成 -，去掉结尾的空格/点"""
    t = re.sub(r'[\x00-\x1f"<>|:*?\\/]', "-", str(s or ""))
    while t and t[-1] in " .":
        t = t[:-1]
    return t


def _clean_path(p) -> str:
    return "/".join(_clean_seg(x) for x in re.split(r"[\\/]", str(p or "")))


def _ext_of(p):
    i = str(p or "").rfind(".")
    if i == -1:
        return None
    e = str(p)[i:]
    return None if e == "." else e


def _with_ext(p, ext) -> str:
    ext = ext[1:] if ext.startswith(".") else ext
    i = str(p).rfind(".")
    return ("%s.%s" % (p, ext)) if i == -1 else ("%s.%s" % (str(p)[:i], ext))


def _archive_path(group, option, entry) -> str:
    """官方 El()/Dl()：包内 `files/` 下的路径（archive_path 优先，否则 组/选项/游戏路径）"""
    ap = entry.get("archive_path")
    if ap is None:
        i = "%s/%s/%s" % (_clean_seg(group or "_default"), _clean_seg(option or "_default"),
                          _clean_path(entry.get("game_path")))
    else:
        i = _clean_path(ap)
    if _ext_of(i) is None:
        e = _ext_of(entry.get("game_path"))
        if e is not None:
            i = _with_ext(i, e)
    return i


def _safe_int(v):
    """JsSafeBigInt（GraphQL 里是字符串）→ 数字（官方 meta.json 里也是数字）"""
    if v is None:
        return None
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return v


def _split_multis(groups):
    """官方 Bl()：Penumbra 每组上限 32 个选项 → 超了拆成 `名字, Part N`"""
    out = []
    for g in groups:
        ops = g.get("Options") or []
        if g.get("Type") != "Multi" or len(ops) <= 32:
            out.append(g)
            continue
        parts = []
        for n, op in enumerate(ops):
            i, a = divmod(n, 32)
            if a == 0:
                parts.append({"Name": "%s, Part %d" % (g.get("Name"), i + 1),
                              "DisplayName": "%s, Part %d" % (g.get("DisplayName"), i + 1),
                              "Description": g.get("Description"), "Priority": g.get("Priority"),
                              "Id": g.get("Id"), "ParentSetting": g.get("ParentSetting"),
                              "DefaultSettings": 0, "Layout": g.get("Layout"),
                              "Condition": g.get("Condition"), "Page": g.get("Page"),
                              "Type": g.get("Type"), "Options": [],
                              "HS_OriginalIndex": [(g.get("HS_OriginalIndex") or [0, 0])[0], i + 1]})
            parts[i]["Options"].append(op)
            if op.get("HS_IsDefault"):
                parts[i]["DefaultSettings"] = (parts[i]["DefaultSettings"] or 0) | (1 << a)
        out.extend(parts)
    return out


_SKIP_NULL = set(
    "Identifier.Author.Description.Website.ModTags.DefaultPreferredItems.RequiredFeatures"
    ".DefaultData.Groups.PageNames.DisplayName.Description.Priority.DefaultSettings.Page.Id"
    ".ParentSetting.Layout.Condition.DisplayName.Description.Priority.Id.Layout.Condition.Color"
    ".IsDisableSubMod.AttributeMask".split("."))


def _strip_nullish(o):
    """官方 jl() replacer：删掉 HS_* 与「值为 null 的白名单字段」（HS_* 是客户端用的）"""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if str(k).startswith("HS_"):
                continue
            if v is None and k in _SKIP_NULL:
                continue
            out[k] = _strip_nullish(v)
        return out
    if isinstance(o, list):
        return [_strip_nullish(x) for x in o]
    return o


def _type_first(o):
    """官方 replacer 的另一个行为：把 Type 键挪到最前（Penumbra 靠它先判类型）"""
    if isinstance(o, dict):
        if "Type" in o:
            return dict([("Type", o["Type"])] + [(k, _type_first(v)) for k, v in o.items() if k != "Type"])
        return {k: _type_first(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_type_first(x) for x in o]
    return o


def build_pmp(cfg, version: dict, version_id: str, dest, on_tick=None, should_cancel=None) -> dict:
    """照官方 worker 的规则把一条 version 打成 .pmp。

    version 是 GraphQL `getVersion` 的结果。返回 {ok, path, files, size, names...}
    """
    pkg = (version.get("variant") or {}).get("package") or {}
    nf = version.get("neededFiles") or {}
    base = str(nf.get("baseUri") or DATA_BASE)
    files = nf.get("files") or {}
    keys = list(files.keys())
    total_files = len(keys)
    if not total_files:
        raise RuntimeError("站点说这条 Mod 没有文件（neededFiles 为空）")

    tmp_dir = os.path.join(os.path.dirname(str(dest)) or ".", "_hszst")
    blobs = {}
    done_bytes = 0
    for i, key in enumerate(keys, 1):
        if should_cancel and should_cancel():
            raise mm.BackupCancelled()
        if on_tick:
            on_tick(0, total_files, "下载文件 %d/%d" % (i, total_files), done_bytes)
        raw = _get(base + key, timeout=180, retries=3, should_cancel=should_cancel)
        blobs[key] = unzstd(cfg, raw, tmp_dir)
        done_bytes += len(raw)
    if len(blobs) != total_files:
        raise RuntimeError("有文件没下全（%d/%d）" % (len(blobs), total_files))

    zip_data = {}
    # ---- heliosphere.json（官方 Sl） ----
    hmeta = {"MetaVersion": 3, "Id": pkg.get("id"), "Name": pkg.get("name"),
             "Tagline": pkg.get("tagline"), "Description": pkg.get("description"),
             "Author": (pkg.get("user") or {}).get("visibleName"), "AuthorId": (pkg.get("user") or {}).get("id"),
             "Variant": (version.get("variant") or {}).get("name"), "VariantId": (version.get("variant") or {}).get("id"),
             "Version": version.get("version"), "VersionId": version_id,
             "IncludeTags": True, "FileStorageMethod": 1}
    zip_data["heliosphere.json"] = json.dumps(hmeta, ensure_ascii=False, indent=4)

    # ---- cover.jpg（内容是 WebP，官方就这么叫） ----
    imgs = pkg.get("images") or []
    if imgs:
        try:
            zip_data["cover.jpg"] = _get(IMG_URL % (pkg.get("id"), (imgs[0] or {}).get("id")),
                                         timeout=90, retries=2)
        except Exception as e:
            mm.log("heliosphere 打包：封面没取到（不影响安装）：%s" % str(e)[:80])

    # ---- Groups（官方 zl） ----
    groups, containers = {}, {}
    gsrc = version.get("groups") or {}
    for g in ((gsrc.get("standard") or []) + (gsrc.get("imc") or []) + (gsrc.get("combining") or [])):
        gt = g.get("groupType")
        base_g = {"Name": g.get("name"), "DisplayName": g.get("displayName"),
                  "ParentSetting": g.get("parentSetting"), "Description": g.get("description"),
                  "Priority": g.get("priority"), "Id": g.get("penumbraId"),
                  "DefaultSettings": _safe_int(g.get("defaultSettings")), "Layout": g.get("layout"),
                  "Condition": g.get("condition"), "Page": g.get("page"),
                  "Type": (str(gt or "")[:1].upper() + str(gt or "")[1:].lower()),
                  "HS_OriginalIndex": [g.get("originalIndex"), 0]}
        if gt in ("SINGLE", "MULTI"):
            if "identifier" in g:
                continue
            base_g["Type"] = "Single" if gt == "SINGLE" else "Multi"
            base_g["Options"] = []
            for op in (g.get("options") or []):
                o = {"Name": op.get("name"), "DisplayName": op.get("displayName"),
                     "Description": op.get("description"), "Priority": op.get("priority"),
                     "Id": op.get("penumbraId"), "Layout": op.get("layout"),
                     "Condition": op.get("condition"), "Color": op.get("color"), "Files": {},
                     "FileSwaps": op.get("fileSwaps"), "Manipulations": op.get("manipulations"),
                     "HS_IsDefault": op.get("isDefault")}
                base_g["Options"].append(o)
                containers[op.get("hsId")] = {"type": "standard", "group": g.get("name"),
                                              "option": op.get("name"), "container": o}
        elif gt == "IMC":
            if "identifier" not in g:
                continue
            base_g.update({"Type": "Imc", "Identifier": g.get("identifier"),
                           "AllVariants": g.get("allVariants"), "OnlyAttributes": g.get("onlyAttributes"),
                           "DefaultEntry": g.get("defaultEntry"), "Options": []})
            for op in (g.get("options") or []):
                base_g["Options"].append({"Name": op.get("name"), "DisplayName": op.get("displayName"),
                                          "Description": op.get("description"), "Id": op.get("penumbraId"),
                                          "Layout": op.get("layout"), "Condition": op.get("condition"),
                                          "Color": op.get("color"), "IsDisableSubMod": op.get("isDisableSubMod"),
                                          "AttributeMask": op.get("attributeMask")})
        elif gt == "COMBINING":
            if "containers" not in g:
                continue
            base_g.update({"Type": "Combining", "Options": [], "Containers": []})
            for op in (g.get("options") or []):
                base_g["Options"].append({"Name": op.get("name"), "DisplayName": op.get("displayName"),
                                          "Description": op.get("description"), "Id": op.get("penumbraId"),
                                          "Layout": op.get("layout"), "Condition": op.get("condition"),
                                          "Color": op.get("color"), "HS_IsDefault": op.get("isDefault")})
            for i, c in enumerate(g.get("containers") or []):
                nm = c.get("name") if (c.get("name") and str(c["name"]).strip()) else "container-%d" % (i + 1)
                cont = {"Name": c.get("name"), "FileSwaps": c.get("fileSwaps"),
                        "Manipulations": c.get("manipulations"), "Files": {}}
                base_g["Containers"].append(cont)
                containers[c.get("hsId")] = {"type": "combining", "group": g.get("name"),
                                             "option": nm, "container": cont}
        else:
            continue
        groups[g.get("name")] = base_g

    group_list = sorted([g for g in groups.values() if g],
                        key=lambda g: g.get("HS_OriginalIndex") or [0, 0])
    group_list = _split_multis(group_list)

    # ---- 文件归属：DefaultData.xx + 各选项/容器（官方 Tl + zl 第二段） ----
    default_data = {"Files": {}, "FileSwaps": (version.get("defaultOption") or {}).get("fileSwaps") or {},
                    "Manipulations": nf.get("defaultManipulations") or []}
    lower_hashes, lower_normal = {}, {}
    ZERO = "00000000-0000-0000-0000-000000000000"
    for key, val in files.items():
        for uid, entries in (val or {}).items():
            c = containers.get(uid) if uid != ZERO else None
            for e in (entries or []):
                if uid == ZERO:
                    p = "files/" + _archive_path(None, None, e)
                    default_data["Files"][e.get("game_path")] = p
                elif c:
                    p = "files/" + _archive_path(c["group"], c["option"], e)
                    c["container"]["Files"][e.get("game_path")] = p
                else:
                    continue
                lower_hashes[p.lower()] = key
                lower_normal[p.lower()] = p

    # ---- 同一个 ui/ 文件被多处引用 → 改名 .1/.2（官方 Vl） ----
    dup = {}
    for g in group_list:
        for o in list(g.get("Options") or []) + list(g.get("Containers") or []):
            for path in list((o.get("Files") or {}).keys()):
                if not str(path).startswith("ui/"):
                    continue
                low = str(path).lower()
                dup.setdefault(low, [0, []])
                dup[low][1].append((o, path))
                dup[low][0] += 1
    for low, (cnt, refs) in list(dup.items()):
        if cnt < 2:
            continue
        orig = refs[0][1]
        for n in range(cnt):
            newp = "files/" + _with_ext(str(orig)[len("files/"):], ".%d%s" % (n + 1, _ext_of(orig) or ""))
            refs[n][0]["Files"][refs[n][1]] = newp
            lower_normal[newp.lower()] = newp
            if low in lower_hashes:
                lower_hashes[newp.lower()] = lower_hashes[low]
        lower_hashes.pop(low, None)
        lower_normal.pop(low, None)

    # ---- meta.json（官方 wl） ----
    vname = str((version.get("variant") or {}).get("name") or "")
    pname = str(pkg.get("name") or "").replace("/", "-")
    meta = {"FileVersion": 4, "Identifier": (version.get("metaInfo") or {}).get("identifier"),
            "Name": ("[HS] %s" % pname) if vname == "Default" else ("[HS] %s (%s)" % (pname, vname.replace("/", "-"))),
            "Author": (pkg.get("user") or {}).get("visibleName"),
            "Description": (version.get("metaInfo") or {}).get("description") or "",
            "Version": version.get("version"), "Website": (version.get("metaInfo") or {}).get("url") or "",
            "ModTags": [str((t or {}).get("slug") or "") for t in (pkg.get("tags") or [])],
            "DefaultPreferredItems": version.get("defaultPreferredItemIds"),
            "RequiredFeatures": (version.get("metaInfo") or {}).get("requiredFeatures"),
            "PageNames": (version.get("metaInfo") or {}).get("pageNames"),
            "DefaultData": default_data, "Groups": group_list}
    meta = _type_first(_strip_nullish(meta))
    zip_data["meta.json"] = json.dumps(meta, ensure_ascii=False, indent=4)

    # ---- 写 zip（官方 Hl + Ul） ----
    entries = dict(zip_data)
    for low, normal in lower_normal.items():
        k = lower_hashes.get(low)
        if k is not None:
            entries[normal] = blobs[k]
    dest = str(dest)
    tmp_out = dest + ".part"
    with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, data in entries.items():
            z.writestr(name, data if isinstance(data, bytes) else str(data).encode("utf-8"))
    os.replace(tmp_out, dest)
    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass
    return {"ok": True, "path": dest, "files": total_files, "entries": len(entries),
            "size": os.path.getsize(dest), "name": pkg.get("name"),
            "author": (pkg.get("user") or {}).get("visibleName"), "version": version.get("version"),
            "variant": vname}


def download(cfg, addr, dest, on_tick=None, should_cancel=None) -> dict:
    """从 heliosphere 下载这条 Mod 的最新文件，落成 dest（.pmp）。返回打包信息。"""
    info = fetch_page_info(addr)
    if not info.get("ok"):
        raise RuntimeError(info.get("error") or "读不到 heliosphere 页面信息")
    vid = str(info.get("version_id") or "")
    if not vid:
        raise RuntimeError("页面里没有版本号（这条 Mod 可能还没发布文件）")
    if on_tick:
        on_tick(0, 1, "读取文件清单…", 0)
    j = _gql(VERSION_QUERY, {"versionId": vid})
    ver = ((j.get("data") or {}).get("getVersion")) if isinstance(j, dict) else None
    if not ver:
        errs = json.dumps(j.get("errors") or [])[:160] if isinstance(j, dict) else ""
        raise RuntimeError("读不到文件清单：%s" % errs)
    out = build_pmp(cfg, ver, vid, dest, on_tick=on_tick, should_cancel=should_cancel)
    out.update({"info": info, "updated": info.get("updated") or "",
                "version_id": vid, "package_id": info.get("package_id") or ""})
    return out
