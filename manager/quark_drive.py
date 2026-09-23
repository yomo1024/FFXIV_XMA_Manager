# -*- coding: utf-8 -*-
"""夸克网盘适配器（独立模块，方便以后换网盘）—— 存档用，不是文件系统。

⚠️ 重要前提
    夸克没有公开的正式开放平台文档（open.quark.cn 仍在内测），这里用的是 PC 端接口
    （drive-pc.quark.cn/1/clouddrive），属于非官方接口：夸克一改版就可能失效。因此：

    · 凭据只从配置（mod_manager.json 的 cloud_cookie）读，绝不写死在代码里；
    · 所有端点集中在下面几个常量里，改版时只改这一处；
    · 所有失败抛 QuarkError，调用方负责给主人能看懂的中文提示；
    · 「上传成功 + 校验通过」才有资格删本地载荷 —— 这条硬规则由调用方（归档任务）执行。

用法
    q = QuarkDrive(cookie, root_path="/MOD")
    q.account()                      # 账号信息（顺便验证 Cookie 还有效）
    fid = q.ensure_dir("/MOD/衣服")   # 逐级建目录，返回末级 fid
    q.list_dir(fid)                  # 列目录
    q.download_url(fid)              # 取某个文件的下载直链
"""
import base64
import hashlib
import html
import json
import mimetypes
import re
from pathlib import Path
import time
import urllib.parse

__all__ = ["QuarkDrive", "QuarkError", "norm", "share_list"]

PC_HOST = "https://drive-pc.quark.cn"      # PC 端主接口
SHARE_HOST = "https://drive.quark.cn"      # 分享接口
ACCOUNT_HOST = "https://pan.quark.cn"      # 账号信息
PC = "/1/clouddrive"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# ★ 取直链 / 下载大文件必须用**客户端 UA**：用网页 UA 时夸克对大文件直接拒
#   （HTTP 400 / code 23018 "download file size limit"，实测 127MB 就超了）。
#   来源：netdisk-fast-download 的接口样例注释「解除文件大小限制需要UA」；
#   实测：网页 UA → 23018；客户端 UA → code=0 直链到手，127MB 能正常下。
#   注意直链签名跟「请求 /file/download 时的 UA + cookie」绑定，所以**下载时也必须用同一个 UA**。
CLIENT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "quark-cloud-drive/2.5.20 Chrome/100.0.4896.160 Electron/18.3.5.4-b478491100 "
             "Safari/537.36 Channel/pckk_other_ch")

BASE_PARAMS = {"pr": "ucpro", "fr": "pc", "uc_param_str": ""}


OSS_UA = "aliyun-sdk-js/6.6.1 Chrome 98.0.4758.80 on Windows 10 64-bit"


def _oss_date() -> str:
    """OSS 签名用的 HTTP 时间串（必须和请求头 x-oss-date 完全一致）。"""
    return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())


def file_hashes(path):
    """一次读完算 md5 + sha1（夸克靠这两个做秒传判定）。"""
    h1, h2 = hashlib.md5(), hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h1.update(chunk)
            h2.update(chunk)
    return h1.hexdigest(), h2.hexdigest()


def _oss_request(method, url, body, headers, timeout=300, want_etag=False):
    """直连 OSS 分片端点（不走夸克网关，签名头由 upload/auth 下发）。"""
    import urllib.error
    import urllib.request
    last = ""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                etag = r.headers.get("ETag") or r.headers.get("Etag") or ""
                r.read()
            return etag
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            if e.code in (500, 502, 503, 504) and attempt < 2:
                last = "HTTP %d %s" % (e.code, detail)
                time.sleep(2 * (attempt + 1))
                continue
            raise QuarkError("OSS 分片失败 HTTP %d：%s" % (e.code, detail))
        except Exception as e:
            last = str(e)[:120]
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise QuarkError("连不上 OSS（重试 3 次）：%s" % last)
    raise QuarkError("OSS 请求失败：%s" % last)


class QuarkError(Exception):
    """夸克接口/凭据相关的错误，message 直接给用户看。"""


def norm(s) -> str:
    """文件名/路径归一：**HTML 反转义** + 压空白 + 小写。

    夸克返回的文件名会把撇号等转义成 `&#39;`（实测：`Ruby&#39;s Ruptured Heart`），
    不反转义就会「目录明明在却找不到」。
    """
    t = html.unescape(str(s or ""))
    return re.sub(r"\s+", " ", t).strip().casefold()


def _default_params(extra=None) -> dict:
    p = dict(BASE_PARAMS)
    p["__dt"] = "1000"
    p["__t"] = str(int(time.time() * 1000))
    for k, v in (extra or {}).items():
        if v is not None:
            p[k] = str(v)
    return p


def _headers(cookie, ua=None) -> dict:
    return {
        "user-agent": ua or UA,
        "origin": "https://pan.quark.cn",
        "referer": "https://pan.quark.cn/",
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "content-type": "application/json",
        "cookie": str(cookie or ""),
    }


def _request(method, url_host, path, cookie, params=None, body=None, timeout=60, allow_anon=False, ua=None) -> dict:
    """纯标准库发请求（**不要引入 requests** —— 管理器跑在只有标准库的 python 上，
    打包出来的 exe 也一样；早期版本这里用了 requests，结果线上直接报
    No module named 'requests'）。"""
    import json as _json
    import urllib.error
    import urllib.request

    if not cookie and not allow_anon:
        raise QuarkError("还没填夸克 Cookie（设置 → 云存储）")
    url = url_host + path + "?" + urllib.parse.urlencode(_default_params(params))
    payload = None
    if body is not None and method.upper() != "GET":
        payload = _json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=_headers(cookie, ua), method=method.upper())
    # 网络抖动重试（本机到 drive-pc.quark.cn 偶尔 TLS 重置 —— 实测踩到过；
    # 上传大文件时更不能一次抖动就整个任务失败）
    last = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                code_http, raw = r.status, r.read().decode("utf-8", "replace")
            break
        except urllib.error.HTTPError as e:             # 报错体里也有 quark 的中文原因，要读出来
            code_http, raw = e.code, e.read().decode("utf-8", "replace")
            break
        except Exception as e:
            last = str(e)[:120]
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise QuarkError("连不上夸克（重试 3 次都失败）：%s" % last)

    try:
        j = _json.loads(raw or "{}")
    except Exception:
        raise QuarkError("返回不是 JSON（可能被风控拦了）HTTP %s：%s" % (code_http, (raw or "")[:140]))

    code, st = j.get("code"), j.get("status")
    ok_code = code in (0, "0", "OK", "ok", None)          # 夸克有的接口返回 code:"OK"
    if not ok_code or st not in (200, 2000000, None):
        msg = j.get("message") or j.get("msg") or j.get("error") or ""
        low = str(msg).lower()
        if "ciphertext" in low or "unknown_exception" in str(code).lower():
            raise QuarkError("夸克 Cookie 无效或已过期（浏览器里重新登录 pan.quark.cn 再复制一次）")
        if code in (31001, 31003, 31010) or "登录" in str(msg) or "cookie" in low:
            raise QuarkError("夸克登录态失效（Cookie 过期），去设置里重新粘贴一次。原始信息：%s %s"
                             % (code, msg))
        raise QuarkError("夸克接口报错 %s：%s" % (code, msg or ("HTTP %s" % code_http)))
    return j.get("data") or {}


def cookie_report(cookie) -> dict:
    """Cookie 体检：只报「有哪些关键字段 + 总长度」，绝不回显内容。

    夸克 PC 端认的关键字段：__kps / __pus / __puus / __uid / sign / vcode。
    主人粘错来源（从别的域名复制、只复制一半、带上了 "Cookie:" 前缀）时一眼能看出来。
    """
    raw = str(cookie or "").strip()
    had_prefix = raw.lower().startswith("cookie:")
    if had_prefix:
        raw = raw.split(":", 1)[1].strip()
    keys = {}
    for part in raw.split(";"):
        if "=" in part:
            k = part.split("=", 1)[0].strip()
            if k:
                keys[k] = keys.get(k, 0) + 1
    need = ["__kps", "__pus", "__puus", "__uid", "sign", "vcode"]
    return {
        "length": len(raw),
        "had_prefix": had_prefix,
        "present": [k for k in need if keys.get(k)],
        "missing": [k for k in need if not keys.get(k)],
        "total_keys": len(keys),
    }


class QuarkDrive:
    def __init__(self, cookie, root_path="/MOD", timeout=60):
        ck = str(cookie or "").strip()
        if ck.lower().startswith("cookie:"):          # 主人常把 "Cookie:" 前缀一起粘进来
            ck = ck.split(":", 1)[1].strip()
        self.cookie = ck
        self.root_path = "/" + str(root_path or "/MOD").strip().strip("/")
        self.timeout = int(timeout or 60)
        self._dir_cache = {}

    # ------------------------------------------------------------- 底层
    def _call(self, method, host, path, params=None, body=None, ua=None, timeout=None) -> dict:
        return _request(method, host, path, self.cookie, params, body,
                        timeout or self.timeout, ua=ua)

    # ------------------------------------------------------------- 账号
    def account(self) -> dict:
        """账号信息；顺带验证 Cookie 是否有效。"""
        return self._call("GET", ACCOUNT_HOST, "/account/info", {"fr": "pc", "platform": "pc"})

    # ------------------------------------------------------------- 目录
    def list_dir(self, fid="0") -> list:
        d = self._call("GET", PC_HOST, PC + "/file/sort", {
            "pdir_fid": str(fid), "_page": "1", "_size": "200", "_fetch_total": "1",
            "_sort": "file_type:asc,file_name:asc",
        })
        return d.get("list") or []

    def find_child(self, fid, name):
        want = norm(name)
        for it in self.list_dir(fid):
            if norm(it.get("file_name")) == want:
                return it
        return None

    def wait_child(self, parent_fid, name, tries=12, delay=0.8):
        """等一个新条目出现在列表里（夸克新建目录/刚上传完的文件不会立刻可见 —— 实测踩到）。"""
        for _ in range(max(1, tries)):
            it = self.find_child(parent_fid, name)
            if it:
                return it
            time.sleep(delay)
        return None

    def mkdir(self, parent_fid, name):
        """在 parent_fid 下建目录，返回目录项（已存在同名也当成功）。"""
        try:
            self._call("POST", PC_HOST, PC + "/file", None,
                       {"pdir_fid": str(parent_fid), "file_name": str(name), "dir_init_lock": False})
        except QuarkError as e:
            if "23008" not in str(e) and "同名冲突" not in str(e) and "exist" not in str(e).lower():
                raise
        self._dir_cache.clear()                    # 目录树变了，缓存作废
        it = self.wait_child(parent_fid, name)
        if not it:
            raise QuarkError("建了目录但列表里一直看不到：%s" % name)
        return it

    def resolve(self, path, create=False):
        """按路径找 fid（如 '/MOD/衣服/SFW'）。create=True 时逐级创建。找不到返回 None。"""
        key = (str(path), bool(create))
        if key in self._dir_cache:
            return self._dir_cache[key]
        parts = [p for p in str(path or "").strip("/").split("/") if p]
        fid = "0"
        for p in parts:
            it = self.find_child(fid, p)
            if it is None and create:
                it = self.mkdir(fid, p)
            if it is None:
                return None
            fid = it.get("fid")
        self._dir_cache[key] = fid
        return fid

    def ensure_dir(self, path) -> str:
        fid = self.resolve(path, create=True)
        if not fid:
            raise QuarkError("建不出云端目录：%s" % path)
        return fid

    # ------------------------------------------------------------- 文件
    def file_info(self, fid) -> dict:
        d = self._call("GET", PC_HOST, PC + "/file", {"fids": str(fid)})
        lst = d.get("list") or []
        return lst[0] if lst else {}

    def download_url(self, fid) -> str:
        """取下载直链（可能带时效；拿不到返回空串）。

        两个要点（都实测过）：
          · `/file/download` **只认 POST**（GET 会被拒：Request method 'GET' not supported）
          · **必须用客户端 UA**（`CLIENT_UA`）：用网页 UA 时大文件会被拒
            （400 / code 23018 "download file size limit"）
        返回可能是 list 也可能是 dict，两种都兼容。
        """
        d = self._call("POST", PC_HOST, PC + "/file/download", None, {"fids": [str(fid)]},
                       ua=CLIENT_UA, timeout=120)
        if isinstance(d, list):
            return str((d[0] or {}).get("download_url") or "")
        return str((d or {}).get("download_url") or "")

    # ------------------------------------------------------------- 上传
    def upload_file(self, local_path, pdir_fid, name=None, part_size=8 << 20, progress=None) -> dict:
        """把一个本地文件上传到夸克目录。返回 {finish(秒传), fid, md5, sha1, size, parts}。

        流程（照 alist 的 quark_uc 驱动实现，2026-09 核对）：
          1) POST /file/upload/pre          拿 task_id / bucket / obj_key / upload_id / auth_info
          2) POST /file/update/hash         {md5, sha1, task_id} → finish=true 就秒传（跳过传数据）
          3) POST /file/upload/auth         用 OSS 预签名字符串换 auth_key（每片一次）
          4) PUT  https://{bucket}.{host}/{obj_key}?partNumber&uploadId   ← OSS 分片，Authorization=auth_key
          5) POST /file/upload/auth（commit 版）+ POST 同一个 URL 提交 CompleteMultipartUpload XML
          6) POST /file/upload/finish       {obj_key, task_id} 让文件真正出现在目录里

        几个**必须一模一样**的东西（否则 OSS 签名不通过）：Content-Type、x-oss-date（同一个 HTTP 时间串）、
        x-oss-user-agent 那个固定字符串（它参与签名）。
        """
        p = Path(local_path)
        if not p.is_file():
            raise QuarkError("要上传的文件不存在：%s" % local_path)
        name = str(name or p.name)
        size = p.stat().st_size
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        md5, sha1 = file_hashes(p)

        pre = self._call("POST", PC_HOST, PC + "/file/upload/pre", None, {
            "ccp_hash_update": True, "dir_name": "", "file_name": name, "format_type": mime,
            "l_created_at": int(time.time() * 1000), "l_updated_at": int(time.time() * 1000),
            "pdir_fid": str(pdir_fid), "size": size,
        })
        task_id = str(pre.get("task_id") or "")
        if not task_id:
            raise QuarkError("upload/pre 没给 task_id：%s" % json.dumps(pre, ensure_ascii=False)[:200])

        # ② 秒传：库里已经有同样的文件 → 直接完成（几百 MB 也是瞬时的）
        try:
            if self._call("POST", PC_HOST, PC + "/file/update/hash", None,
                          {"md5": md5, "sha1": sha1, "task_id": task_id}).get("finish"):
                self._finish_upload(pre)
                return {"finish": True, "fid": str(pre.get("fid") or ""), "md5": md5,
                        "sha1": sha1, "size": size, "parts": 0, "name": name}
        except QuarkError:
            pass                                   # 秒传查询失败不影响正常上传

        # ③④ 分片上传
        bucket, obj_key = str(pre.get("bucket") or ""), str(pre.get("obj_key") or "")
        upload_id, upload_url = str(pre.get("upload_id") or ""), str(pre.get("upload_url") or "")
        if not (bucket and obj_key and upload_id and upload_url):
            raise QuarkError("upload/pre 没给全 bucket/obj_key/upload_id/upload_url")
        host = upload_url.split("://", 1)[-1]
        base_url = "https://%s.%s/%s" % (bucket, host.rstrip("/"), obj_key)
        n_parts = max(1, (size + part_size - 1) // part_size)
        etags = []
        with open(p, "rb") as fh:
            sent = 0
            for i in range(n_parts):
                chunk = fh.read(part_size)
                etag = self._put_part(pre, base_url, mime, i + 1, upload_id, chunk)
                etags.append(etag.strip('"'))
                sent += len(chunk)
                if progress:
                    progress(i + 1, n_parts, sent, size, name)
        self._commit_parts(pre, base_url, upload_id, etags)
        self._finish_upload(pre)
        landed = self.wait_child(pdir_fid, name)   # 落地确认（云端文件也可能慢一拍才可见）
        return {"finish": False, "fid": str((landed or {}).get("fid") or pre.get("fid") or ""),
                "md5": md5, "sha1": sha1, "size": size, "parts": n_parts, "name": name,
                "arrived": bool(landed), "cloud_size": (landed or {}).get("size")}

    # ---- 上传用到的小件 ----
    def _auth_key(self, pre, auth_meta) -> str:
        d = self._call("POST", PC_HOST, PC + "/file/upload/auth", None,
                       {"auth_info": pre.get("auth_info"), "auth_meta": auth_meta,
                        "task_id": pre.get("task_id")})
        key = str(d.get("auth_key") or "")
        if not key:
            raise QuarkError("upload/auth 没给 auth_key：%s" % json.dumps(d, ensure_ascii=False)[:200])
        return key

    def _put_part(self, pre, base_url, mime, part_number, upload_id, chunk) -> str:
        date = _oss_date()
        meta = ("PUT\n\n%s\n%s\nx-oss-date:%s\nx-oss-user-agent:%s\n/%s/%s?partNumber=%d&uploadId=%s"
                % (mime, date, date, OSS_UA, pre["bucket"], pre["obj_key"], part_number, upload_id))
        key = self._auth_key(pre, meta)
        url = "%s?partNumber=%d&uploadId=%s" % (base_url, part_number, upload_id)
        etag = _oss_request("PUT", url, chunk, {
            "Authorization": key, "Content-Type": mime, "Referer": "https://pan.quark.cn/",
            "x-oss-date": date, "x-oss-user-agent": OSS_UA,
        }, timeout=self.timeout, want_etag=True)
        return etag

    def _commit_parts(self, pre, base_url, upload_id, etags):
        xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<CompleteMultipartUpload>\n'
               + "".join("<Part>\n<PartNumber>%d</PartNumber>\n<ETag>\"%s\"</ETag>\n</Part>\n"
                         % (i + 1, e) for i, e in enumerate(etags))
               + "</CompleteMultipartUpload>")
        body = xml.encode("utf-8")
        content_md5 = base64.b64encode(hashlib.md5(body).digest()).decode()
        callback_b64 = base64.b64encode(json.dumps(pre.get("callback") or {}, ensure_ascii=False)
                                        .encode("utf-8")).decode()
        date = _oss_date()
        meta = ("POST\n%s\napplication/xml\n%s\nx-oss-callback:%s\nx-oss-date:%s\nx-oss-user-agent:%s\n/%s/%s?uploadId=%s"
                % (content_md5, date, callback_b64, date, OSS_UA,
                   pre["bucket"], pre["obj_key"], upload_id))
        key = self._auth_key(pre, meta)
        url = "%s?uploadId=%s" % (base_url, upload_id)
        _oss_request("POST", url, body, {
            "Authorization": key, "Content-MD5": content_md5, "Content-Type": "application/xml",
            "Referer": "https://pan.quark.cn/", "x-oss-callback": callback_b64,
            "x-oss-date": date, "x-oss-user-agent": OSS_UA,
        }, timeout=self.timeout)

    def _finish_upload(self, pre):
        self._call("POST", PC_HOST, PC + "/file/upload/finish", None,
                   {"obj_key": pre.get("obj_key"), "task_id": pre.get("task_id")})
        time.sleep(1)                              # alist 也是等 1 秒再列目录

    def delete(self, fids):
        """删文件/目录（进夸克回收站）"""
        if isinstance(fids, str):
            fids = [fids]
        return self._call("POST", PC_HOST, PC + "/file/delete", None,
                          {"action_type": 2, "filelist": [str(f) for f in fids], "exclude_fids": []})

    # ------------------------------------------------------------- 自检
    def selftest(self) -> dict:
        """连通性自检：Cookie 体检 → 列根目录（归档真正要用的接口）→ 账号昵称 → 取直链。

        给设置页「测试连接」用；只读，不改任何东西。
        """
        out = {"ok": False, "error": "", "user": "", "member": "", "root": self.root_path,
               "root_fid": "", "root_children": 0, "root_dirs": 0, "sample": [],
               "download_test": "", "root_ok": False, "top_dirs": [],
               "cookie": cookie_report(self.cookie)}
        try:                                          # ① 列根目录 = 归档真正要用的接口
            drive_items = self.list_dir("0")
            out["drive_root_children"] = len(drive_items)
        except QuarkError as e:
            out["error"] = str(e)
            return out
        try:                                          # ② 昵称/会员（读不到只影响显示）
            a = self.account()
            out["user"] = str(a.get("nickname") or "")
            out["member"] = str(a.get("member_type") or "")
        except QuarkError as e:
            out["user"] = "（昵称读不到，但列目录通：%s）" % str(e)[:50]
        try:
            fid = self.resolve(self.root_path)
            out["root_fid"] = fid or ""
            if fid:
                items = self.list_dir(fid)
                out["root_children"] = len(items)
                out["root_dirs"] = sum(1 for it in items if it.get("dir"))
                out["root_ok"] = True
                out["sample"] = [{"name": it.get("file_name"), "dir": bool(it.get("dir")),
                                  "size": it.get("size") or 0} for it in items[:8]]
                cand = next((it for it in items if not it.get("dir")), None)
                if cand is None:
                    sub = next((it for it in items if it.get("dir")), None)
                    if sub:
                        for it in self.list_dir(sub["fid"]):
                            if not it.get("dir") and str(it.get("file_name", "")).lower().endswith(
                                    (".pmp", ".zip", ".7z", ".rar")):
                                cand = it
                                break
                if cand:
                    u = self.download_url(cand.get("fid"))
                    out["download_test"] = "%s → %s" % (
                        cand.get("file_name"), ("取到直链（%d 字符）" % len(u)) if u else "直链为空")
            else:
                top = [it.get("file_name") for it in self.list_dir("0") if it.get("dir")]
                out["root_ok"] = False
                out["top_dirs"] = top[:12]
                out["error"] = ("云端根目录 %s 不存在。你网盘根下的目录有：%s"
                                % (self.root_path, "、".join(top[:12]) or "（一个都没有）"))
            out["ok"] = True
        except QuarkError as e:
            out["error"] = str(e)
        return out


# ------------------------------------------------------------------ 分享（只读）
def share_list(share_id, pwd_id=None, parent_fid="0", deep=True, max_nodes=900) -> list:
    """读一个**分享链接**的目录树（不需要登录，用来跟本地库对账/看别人传了什么）。

    参数 share_id = 链接最后那段，例如 https://pan.quark.cn/s/fb40848cdf77 → fb40848cdf77
    返回 [{path,dir,name,size,fid}]，path 形如 /MOD/衣服/SFW/xxx.pmp
    """
    sid = str(share_id or "").strip()
    if "/" in sid:
        sid = sid.rstrip("/").split("/")[-1]
    data = _request("POST", SHARE_HOST, PC + "/share/sharepage/token", "",
                    {"pwd_id": sid, "passcode": ""}, body={"pwd_id": sid, "passcode": ""},
                    allow_anon=True)
    stoken = str(data.get("stoken") or "")
    if not stoken:
        raise QuarkError("拿不到分享令牌（链接失效或需要提取码）")
    base = data.get("title") or "分享"

    def ls(fid):
        d = _request("GET", SHARE_HOST, PC + "/share/sharepage/detail", "", {
            "pwd_id": sid, "stoken": stoken, "pdir_fid": str(fid), "force": "0", "_page": "1",
            "_size": "200", "_fetch_banner": "0", "_fetch_share": "1", "_fetch_total": "1",
            "_sort": "file_name:asc",
        }, allow_anon=True)
        return d.get("list") or []

    out, stack = [], [("0", base)]
    while stack and len(out) < max_nodes:
        fid, path = stack.pop()
        for it in ls(fid):
            p = path + "/" + str(it.get("file_name") or "")
            node = {"path": p, "dir": bool(it.get("dir")), "name": it.get("file_name"),
                    "size": it.get("size") or 0, "fid": it.get("fid")}
            out.append(node)
            if node["dir"] and deep:
                stack.append((it["fid"], p))
    return out
