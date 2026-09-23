#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
FFXIV Mod 管理工具 —— 本地 Web 服务
=====================================================================
只监听 127.0.0.1，浏览器里操作。业务逻辑全部复用 mod_manager.py：
扫描解析、索引库、Excel 内嵌图、打包/导入备份、查重、安装检查、序号重排……

用法：
    python mod_manager_web.py                 启动并自动开浏览器
    python mod_manager_web.py --no-browser    只起服务
    python mod_manager_web.py --port 8800     换端口
    python mod_manager_web.py --root "D:\x"   临时用别的 Mod 根目录（不写回配置，方便测试）
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html as _html
import json
import mimetypes
import os
import re
import shutil
import socket
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
import mod_manager as mm                      # noqa: E402
import app_version                            # noqa: E402  版本号唯一来源

mm.sys.excepthook = sys.__excepthook__        # 服务端不要弹错误对话框


# --------------------------------------------------------------------- 版本监控
MANAGER_VERSION = app_version.APP_VERSION                    # 管理器自己的版本（界面/接口有改动就 +1）
MIN_PLUGIN_VERSION = app_version.MIN_PLUGIN_VERSION          # 游戏内插件的最低要求版本（低于它就没有封面/目录命名这些新功能）


def _build_stamp():
    """构建时间：打包成 exe 时看 exe 的时间，源码运行时看本文件的时间。"""
    try:
        target = Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(target.stat().st_mtime))
    except Exception:
        return ""


MANAGER_BUILD = _build_stamp()


def ver_tuple(s):
    try:
        return tuple(int(x) for x in re.findall(r"\d+", str(s or ""))[:4]) or (0,)
    except Exception:
        return (0,)


def ver_ge(a, b):
    """a >= b 吗（按数字段比较，"0.2.10" > "0.2.9"）。"""
    a2, b2 = ver_tuple(a), ver_tuple(b)
    n = max(len(a2), len(b2))
    a2 = a2 + (0,) * (n - len(a2))
    b2 = b2 + (0,) * (n - len(b2))
    return a2 >= b2


def plugin_version_info():
    """问游戏里的插件是哪个版本（版本监控用）。
    返回 {reachable, version, ok, message, min, features}；reachable=False 表示插件没在跑。"""
    try:
        ping = bridge_call("/ping", need_token=False, timeout=6) or {}
    except SystemExit as e:
        return {"reachable": False, "version": "", "ok": False, "message": str(e), "min": MIN_PLUGIN_VERSION}
    except Exception as e:
        return {"reachable": False, "version": "", "ok": False, "message": str(e), "min": MIN_PLUGIN_VERSION}

    v = str(ping.get("version") or "")
    ok = ver_ge(v, MIN_PLUGIN_VERSION)
    if ok:
        msg = "插件 v%s（要求 ≥ v%s）✓" % (v, MIN_PLUGIN_VERSION)
    else:
        msg = ("游戏里的 Mod Bridge 是 v%s，管理器要求 ≥ v%s —— 请按《手动部署-游戏插件.md》"
               "把插件换成最新版，然后**重启游戏**（插件是 DLL，没法热更）。" % (v or "未知", MIN_PLUGIN_VERSION))
    return {"reachable": True, "version": v, "ok": ok, "message": msg,
            "min": MIN_PLUGIN_VERSION, "features": ping.get("features") or []}


def require_plugin_version():
    """装 mod 之前先做版本监控：插件太旧就直接拦下来，别装出个半成品。"""
    info = plugin_version_info()
    if info.get("reachable") and not info.get("ok"):
        raise SystemExit(info["message"])
    return info

def _find_web_dir() -> Path:
    """界面文件位置：源码运行 / onedir / onefile 三种情况都能找到"""
    cands = [APP_DIR / "web", APP_DIR / "_internal" / "web"]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        cands.append(Path(meipass) / "web")
    for c in cands:
        if (c / "index.html").is_file():
            return c
    return cands[0]


WEB_DIR = _find_web_dir()
DEFAULT_PORT = 8765
THUMB_CACHE: dict = {}
_IDX = {"d": {}, "t": 0.0}
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/134.0 Safari/537.36")
_HASH = {}
# 从「你自己浏览器」送过来的页面信息（书签小工具用）
LAST_PAGE = {"data": None, "at": 0.0}


def file_hash(p) -> str:
    p = Path(p)
    st = p.stat()
    key = (str(p), int(st.st_mtime), st.st_size)
    v = _HASH.get(key)
    if not v:
        v = mm.md5_of(p)
        _HASH[key] = v
    return v
ROOT_OVERRIDE = ""                            # --root 临时覆盖（不写回配置）


# --------------------------------------------------------------------- 小工具
def override_cfg_path() -> Path:
    """--root 临时模式专用的配置文件（放在临时根目录旁边，和真实配置完全隔离）"""
    return Path(ROOT_OVERRIDE).resolve().parent / "mod_manager.root-override.json"


def load_cfg() -> dict:
    """读配置：临时模式读隔离配置（不存在就基于真实配置起步，但不写回）"""
    if ROOT_OVERRIDE:
        p = override_cfg_path()
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                mm.log("临时配置读不了（%s）：%s" % (p, e))
        base = dict(mm.load_config())
        return base
    return mm.load_config()


def save_cfg(cfg: dict):
    """保存配置；--root 临时模式写隔离配置，绝不碰真实配置（连 token 之类也不污染）。"""
    if ROOT_OVERRIDE:
        p = override_cfg_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            c = dict(cfg)
            c["root"] = ROOT_OVERRIDE          # 隔离配置里也写临时根目录，免得看的人误解
            p.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            mm.log("临时配置写不了（%s）：%s" % (p, e))
    else:
        mm.save_config(cfg)


def cfg_now() -> dict:
    """每次读取最新配置；--root 时用临时目录（也不写回）"""
    cfg = load_cfg()
    if ROOT_OVERRIDE:
        cfg["root"] = ROOT_OVERRIDE
        # 临时模式：汇总表也放临时目录，免得导出时把真实汇总表覆盖成测试数据
        cfg["excel"] = str(Path(ROOT_OVERRIDE).resolve().parent / "Mod信息汇总表.xlsx")
    return cfg


def tail_log(n=80):
    try:
        lines = mm.LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return []


def inside_root(path, root) -> bool:
    try:
        p, r = Path(path).resolve(), Path(root).resolve()
        return bool(str(root)) and (p == r or r in p.parents)
    except Exception:
        return False


def safe_rel(path, root) -> str:
    try:
        return os.path.relpath(str(path), str(root))
    except Exception:
        return str(path)


def mod_index(force=False):
    """folder -> mod 记录；2 秒内复用，避免每个请求都查库"""
    now = time.time()
    if not force and _IDX["t"] > now - 2:
        return _IDX["d"]
    d = {}
    try:
        for m in mm.Store().all():
            d[str(m["folder"])] = m
    except Exception:
        mm.log(traceback.format_exc())
    _IDX["d"], _IDX["t"] = d, now
    return d


def one_mod(cfg, folder):
    m = mod_index().get(str(folder))
    if not m or not inside_root(m["folder"], cfg.get("root") or ""):
        return None
    return m


# --------------------------------------------------------------------- 任务
class Job:
    def __init__(self, kind: str, params: dict | None = None):
        self.kind = kind
        self.params = params or {}
        self.lock = threading.Lock()
        self.state = "running"           # running / done / error / cancelled
        self.done = 0
        self.total = 0
        self.text = ""
        self.result = None
        self.error = ""
        self.t0 = time.time()
        self.t1 = None
        self._cancel = False

    def set(self, done, total, text=""):
        with self.lock:
            self.done, self.total = int(done or 0), int(total or 0)
            if text:
                self.text = str(text)

    def cancelled(self) -> bool:
        return self._cancel

    def cancel(self):
        self._cancel = True
        with self.lock:
            self.text = "正在取消…"

    def snap(self):
        with self.lock:
            pct = int(self.done * 100 / self.total) if self.total else 0
            if self.state == "done":
                pct = 100
            return {"kind": self.kind, "state": self.state, "done": self.done,
                    "total": self.total, "pct": max(0, min(100, pct)),
                    "text": self.text, "error": self.error, "result": self.result,
                    "elapsed": round((self.t1 or time.time()) - self.t0, 1)}


JOB_LOCK = threading.Lock()
JOBS = {"cur": None}
JOB_TITLES = {"scan": "扫描目录", "export": "生成 Excel", "run": "扫描并生成 Excel", "selfdownload": "在自己浏览器里下载 → 自动入库", "importfile": "入库（浏览器下好的文件）",
              "backup": "打包备份", "restore": "导入备份", "import": "导入下载",
              "renumber": "重排序号", "download": "从页面下载", "watch": "监视下载",
              "fetch": "解析并下载入库",
              "update_check": "检查更新", "mod_update": "更新 Mod（覆盖下载）"}


# --------------------------------------------------------------------- 各任务
def _job_scan(job: Job):
    cfg = cfg_now()
    root = Path(cfg["root"] or "")
    if not root.is_dir():
        raise RuntimeError("Mod 根目录不存在：%s" % root)
    mods = mm.scan_root_progress(root, progress=lambda d, t, n: job.set(d, t, n),
                                should_cancel=job.cancelled)
    if job.cancelled():
        raise mm.BackupCancelled()
    job.set(len(mods), len(mods), "写入索引库…")
    store = mm.Store()
    for m in mods:
        m["img_hash"] = store.upsert(m)
    store.commit()
    pruned = store.prune({m["folder"] for m in mods})
    store.commit()
    mod_index(force=True)
    return {"mods": len(mods), "pruned": pruned}


def _job_export(job: Job):
    cfg = cfg_now()
    mods = mm.Store().all()
    if not mods:
        _job_scan(job)
        mods = mm.Store().all()
    hashes = {m["folder"]: m.get("img_hash") or "" for m in mods}
    job.set(0, max(1, len(mods)), "开始生成…")
    out = Path(cfg["excel"])
    n_cat, n_mod, n_img = mm.write_excel(
        mods, cfg, out, hashes, progress=lambda d, t, txt: job.set(d, t, txt))
    mod_index(force=True)
    return {"sheets": n_cat, "mods": n_mod, "images": n_img, "path": str(out)}


def _job_run(job: Job):
    a = _job_scan(job)
    job.set(1, 1, "扫描完成，开始生成 Excel…")
    b = _job_export(job)
    return {**a, **b}


def _job_backup(job: Job):
    cfg = cfg_now()
    out = job.params.get("out") or str(mm.default_backup_path(cfg))

    def prog(n, tn, b, tb, name):
        job.set(n, tn, "%s ｜ %s / %s" % (name, mm.fmt_size(b), mm.fmt_size(tb)))

    st = mm.make_backup(cfg, out, True, True, bool(job.params.get("compress")),
                        progress=prog, should_cancel=job.cancelled)
    return {"path": st["path"], "mods": st["mods"], "files": st["files"],
            "size": st["zip_bytes"], "human": mm.fmt_size(st["zip_bytes"])}


def _job_restore(job: Job):
    cfg = cfg_now()
    src = job.params.get("file") or ""
    mode = job.params.get("mode") or "skip"
    inc_mods = bool(job.params.get("mods", True))
    inc_meta = bool(job.params.get("meta", False))
    if not Path(src).is_file():
        raise RuntimeError("找不到备份文件：%s" % src)
    job.set(0, 1, "解包中…")

    def prog(d, t, b, tb, name):
        job.set(d, t, "%s ｜ %s / %s" % (name, mm.fmt_size(b), mm.fmt_size(tb)))

    r = mm.restore_backup(cfg, src, inc_mods, inc_meta, mode, progress=prog,
                          should_cancel=job.cancelled)
    if inc_mods and not job.cancelled():
        job.set(1, 1, "重扫索引并重新生成 Excel…")
        _job_scan(job)
        _job_export(job)
    mod_index(force=True)
    return {k: v for k, v in r.items() if k != "renamed_list"} | {
        "renamed": [b for _a, b in r.get("renamed_list", [])]}


def _job_import(job: Job):
    cfg = cfg_now()
    files = job.params.get("files") or []
    cat = job.params.get("category") or ""
    zone = job.params.get("zone") or "SFW"
    subdir = job.params.get("subdir") or ""
    move = bool(job.params.get("move", True))
    if not files:
        raise RuntimeError("没有要导入的文件")
    if not cat:
        raise RuntimeError("请先选分类")
    done, errors = [], []
    for i, f in enumerate(files, 1):
        if job.cancelled():
            raise mm.BackupCancelled()
        job.set(i - 1, len(files), os.path.basename(str(f)))
        try:
            t = mm.import_mod(cfg, str(f), cat, zone, subdir, None, None, None, "", move)
            done.append(safe_rel(t, cfg["root"]))
        except Exception as e:
            errors.append("%s：%s" % (Path(str(f)).name, e))
    job.set(len(files), len(files), "重扫索引并重新生成 Excel…")
    if done:
        _job_scan(job)
        _job_export(job)
    return {"ok": done, "failed": errors}


def _job_renumber(job: Job):
    cfg = cfg_now()
    cat = job.params.get("category") or ""
    sub = job.params.get("subcat") or ""
    start = int(job.params.get("start") or 1)
    plan = mm.renumber_plan(cfg, cat, sub, start)
    if not plan:
        return {"changed": 0, "items": []}
    items = [{"folder": m["folder"], "name": m["name"], "old": m["seq"], "new": n}
             for m, n in plan]
    job.set(0, len(items), "改文件夹名…")
    applied = mm.renumber(cfg, cat, sub, start, dry_run=False, export=False)
    mod_index(force=True)
    _job_scan(job)
    return {"changed": len(applied), "items": items}


def _job_download(job: Job):
    cfg = cfg_now()
    dest = job.params.get("dest") or mm.resolve_dirs(cfg)[1]

    def tick(sec):
        job.set(sec, 0, "等待下载完成… 第 %ds" % sec)

    try:
        href, path = mm.browser_download(
            cfg, dest, timeout=int(job.params.get("timeout") or 900),
            on_tick=tick, should_cancel=job.cancelled)
    except SystemExit as e:                       # mod_manager 用 SystemExit 表达“可读的错误”
        raise RuntimeError(str(e))
    if job.cancelled():
        raise mm.BackupCancelled()
    if not path:
        raise RuntimeError("没等到下载完成的文件（可以试试点页面上的下载按钮）")
    return {"href": href, "file": str(path), "name": Path(path).name,
            "size": Path(path).stat().st_size,
            "human": mm.fmt_size(Path(path).stat().st_size), "dest": str(dest)}


def _job_watch(job: Job):
    """盯着下载目录，把下完的 Mod 文件自动搬进暂存目录"""
    cfg = cfg_now()
    dl, ib = mm.resolve_dirs(cfg)
    dld, ibd = Path(dl), Path(ib)
    ibd.mkdir(parents=True, exist_ok=True)
    secs = max(10, int(job.params.get("seconds") or 600))
    before = {f.name for f in dld.iterdir() if f.is_file()} if dld.is_dir() else set()
    moved, t0 = [], time.time()
    while time.time() - t0 < secs:
        if job.cancelled():
            raise mm.BackupCancelled()
        time.sleep(1.0)
        el = int(time.time() - t0)
        job.set(el, secs, "监视中… 已搬走 %d 个（%s）" % (len(moved), dld.name))
        if not dld.is_dir():
            continue
        for f in list(dld.iterdir()):
            try:
                if (not f.is_file() or f.name in before
                        or f.suffix.lower() in mm.PARTIAL_EXT
                        or f.suffix.lower() not in mm.ARCHIVE_EXT):
                    continue
                s1 = f.stat().st_size
                time.sleep(0.8)                    # 等它写稳，别搬半个
                if s1 == 0 or f.stat().st_size != s1:
                    continue
                tgt = ibd / f.name
                if tgt.exists():
                    tgt = ibd / ("%s_%d%s" % (f.stem, int(time.time()), f.suffix))
                shutil.move(str(f), str(tgt))
                before.add(f.name)
                moved.append(tgt.name)
            except OSError:
                continue
    return {"moved": moved, "inbox": str(ibd), "seconds": secs}


def _browser_cookie_header(cfg):
    """能拿到就用内置浏览器的 cookie（没开着就返回空串）"""
    try:
        if not mm.browser_running(cfg):
            return ""
        cdp = mm._cdp_get(cfg, True)
        try:
            cks = cdp.call("Network.getCookies",
                           urls=["https://www.xivmodarchive.com/",
                                 "https://static.xivmodarchive.com/"])["cookies"]
        except Exception:
            cdp.call("Network.enable")
            cks = cdp.call("Network.getCookies",
                           urls=["https://www.xivmodarchive.com/",
                                 "https://static.xivmodarchive.com/"])["cookies"]
        return "; ".join("%s=%s" % (c["name"], c["value"]) for c in cks)
    except Exception:
        return ""


def _stream_to(url, dest_dir, on_tick=None, should_cancel=None, cookies="", referer=""):
    """直链流式下载到 dest_dir，返回落地路径"""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    nm = urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name) or "download.bin"
    if "." not in nm:
        nm += ".zip"
    dest = dest_dir / nm
    i = 1
    while dest.exists():
        dest = dest_dir / ("%s_%d%s" % (Path(nm).stem, i, Path(nm).suffix))
        i += 1
    hdr = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/134.0 Safari/537.36",
           "Accept": "*/*"}
    if cookies:
        hdr["Cookie"] = cookies
    if referer:
        hdr["Referer"] = referer
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=90) as r, open(str(dest), "wb") as fh:
        try:
            total = int(r.headers.get("Content-Length") or 0)
        except Exception:
            total = 0
        done = 0
        while True:
            if should_cancel and should_cancel():
                raise mm.BackupCancelled()
            buf = r.read(1 << 20)
            if not buf:
                break
            fh.write(buf)
            done += len(buf)
            if on_tick:
                try:
                    on_tick(done, total)
                except Exception:
                    pass
    return dest


def _job_fetch(job: Job):
    """粘贴链接 -> 打开页面 -> 下载 -> 入库 -> 抓封面 -> 重扫/导出，全自动"""
    cfg = cfg_now()
    q = job.params
    url = mm.norm_addr(str(q.get("url") or ""))
    cat = str(q.get("category") or "").strip()
    if not url:
        raise RuntimeError("缺少 Mod 链接")
    if not cat:
        raise RuntimeError("请选择要导入的分类")

    inbox = mm.resolve_dirs(cfg)[1]
    from_browser = q.get("page") if isinstance(q.get("page"), dict) else None
    path = None

    if from_browser:
        # 页面信息是你自己的浏览器（书签小工具）送来的：直接用直链下，不用内置浏览器
        info = from_browser
        dl = (info.get("dl") or "").strip()
        if not dl:
            raise RuntimeError("这条信息里没有下载直链（可能要登录，或作者没上传文件）")
        job.set(1, 5, "开始下载（用你浏览器给的直链）…")
        ck = _browser_cookie_header(cfg)
        try:
            path = _stream_to(
                dl, inbox, cookies=ck,
                referer=("https://www.xivmodarchive.com/modid/%s" % info.get("modid"))
                if info.get("modid") else "https://www.xivmodarchive.com/",
                on_tick=lambda done, total: job.set(
                    1, 5, "下载中… %s%s" % (mm.fmt_size(done),
                                            (" / " + mm.fmt_size(total)) if total else "")),
                should_cancel=job.cancelled)
        except mm.BackupCancelled:
            raise
        except Exception as e:
            if not cfg.get("auto_open_browser"):
                raise RuntimeError("直链没下下来（%s）。常见原因：① XIVModArchive 的下载需要登录 —— "
                                   "在内置浏览器里登录一次就会记住（书签小工具推来的链接也是用它的登录态下载）；"
                                   "② 没开内置浏览器（默认不开）：可到「设置」或下载工作台勾选「需要时自动打开内置浏览器」；"
                                   "③ 也可以自己浏览器里下好，再用「监视下载目录」。"
                                   % str(e)[:80])
            job.set(1, 5, "直链下载没成功（%s），改用内置浏览器…" % str(e)[:60])
            try:
                mm.launch_browser(cfg, info.get("addr") or info.get("url") or url)
                mm.browser_wait_ready(cfg, timeout=60)
                href, path = mm.browser_download(
                    cfg, inbox, timeout=int(q.get("timeout") or 900),
                    on_tick=lambda sec: job.set(1, 5, "下载中… 第 %ds" % sec),
                    should_cancel=job.cancelled,
                    url=(info.get("addr") or info.get("url") or url))
            except SystemExit as e2:
                raise RuntimeError(str(e2))
        if job.cancelled():
            raise mm.BackupCancelled()
        if not path:
            raise RuntimeError("没等到下载完成的文件（可以在内置浏览器里手动点下载，再用「监视下载目录」）")
    else:
        job.set(0, 5, "打开页面…")
        try:
            mm.launch_browser(cfg, url)
        except SystemExit as e:
            raise RuntimeError(str(e))
        mm.browser_wait_ready(cfg, timeout=int(q.get("ready_timeout") or 60),
                              on_tick=lambda sec: job.set(0, 5, "等待页面就绪… %ds" % sec))
        if job.cancelled():
            raise mm.BackupCancelled()
        info = mm.browser_capture(cfg)
        if not info.get("is_mod"):
            raise RuntimeError("页面还不是 Mod 详情页（可能卡在人机验证，去内置浏览器窗口点一下再重试）")

        job.set(1, 5, "开始下载…")
        # 先试"用浏览器的登录态直接下直链"（最稳，不用点页面），不行再让页面自己下载
        href, path = (info.get("dl") or ""), None
        if href:
            try:
                path = _stream_to(
                    href, inbox, cookies=_browser_cookie_header(cfg),
                    referer=info.get("addr") or url,
                    on_tick=lambda done, total: job.set(
                        1, 5, "下载中… %s%s" % (mm.fmt_size(done),
                                                (" / " + mm.fmt_size(total)) if total else "")),
                    should_cancel=job.cancelled)
            except mm.BackupCancelled:
                raise
            except Exception as e1:
                job.set(1, 5, "直链没成功（%s），改让页面自己下载…" % str(e1)[:60])
                path = None
        if not path:
            try:
                href, path = mm.browser_download(
                    cfg, inbox, timeout=int(q.get("timeout") or 900),
                    on_tick=lambda sec: job.set(1, 5, "下载中… 第 %ds" % sec),
                    should_cancel=job.cancelled,
                    url=url)
            except SystemExit as e:
                raise RuntimeError(str(e))
        if job.cancelled():
            raise mm.BackupCancelled()
        if not path:
            raise RuntimeError("没等到下载完成的文件（可以在内置浏览器里手动点下载，再用「监视下载目录」）")

    try:                                   # 入库是“移动”，先量大小
        _size = Path(path).stat().st_size
    except OSError:
        _size = 0

    job.set(2, 5, "入库（写 地址.txt、自动编号）…")
    author = (q.get("author") or info.get("author") or "").strip()
    name = (q.get("name") or info.get("name") or "").strip()
    addr = (q.get("addr") or info.get("addr") or "").strip()
    if not addr and info.get("modid"):
        addr = "https://www.xivmodarchive.com/modid/%s" % info["modid"]
    seq = int(q["seq"]) if str(q.get("seq") or "").strip().isdigit() else None
    target, _exist, _removed = import_or_update(
        cfg, path, cat, str(q.get("zone") or "SFW"), str(q.get("subdir") or ""),
        author or None, name or None, seq, addr, info, job)

    got = ""
    if q.get("cover", True) and info.get("cover"):
        job.set(3, 5, "抓封面当预览图…")
        cu = info["cover"]
        ext = "." + (cu.rsplit(".", 1)[-1].split("?")[0].lower() if "." in cu else "jpg")
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            ext = ".jpg"
        tdir = Path(target)
        try:
            mm.browser_fetch(cfg, cu, tdir.parent / (tdir.name + ext))
            got = ext
        except Exception:
            got = ""

    job.set(4, 5, "重扫索引、写标签、生成 Excel…")
    mm.cmd_scan(cfg, quiet=True)
    mod_index(force=True)
    _meta = apply_meta_after_import(
        cfg, target,
        tags=info.get("tags") or q.get("tags") or [],
        affects=q.get("affects") if q.get("affects") is not None else info.get("affects"),
        addr=addr)
    _site = record_site_update(cfg, target, addr)
    if q.get("export", True):
        _job_export(job)
    return {"mod": Path(target).name, "rel": safe_rel(target, cfg.get("root") or ""),
            "updated_existing": bool(_exist), "removed": _removed,
            "tags": _meta.get("tags") or [], "affects": _meta.get("affects") or "",
            "file": Path(path).name, "cover": bool(got),
            "size": _size, "human": mm.fmt_size(_size),
            "addr": mm.norm_addr(addr), "target": str(target)}


def _job_selfdownload(job: Job):
    """让"你自己的浏览器"去下载，管理器在这边接住文件并入库。

    为什么这么做：管理器读不了你正开着的浏览器（浏览器安全限制），
    但文件下载根本不需要它读页面 —— 你在自己的浏览器里点一下（或用书签小工具
    推过来的直链），文件就带着你的登录态下到下载目录了；这里只负责：
    等文件出现 → 入库（写 地址.txt / 自动编号 / 抓封面）→ 重扫 → 导 Excel。
    全程只用你那一个浏览器，不碰内置浏览器。
    """
    cfg = cfg_now()
    q = job.params or {}
    info = q.get("page") if isinstance(q.get("page"), dict) else {}
    dl_dir = Path(str(q.get("dir") or "").strip() or str(mm.browser_download_dir(cfg)))
    dl_dir.mkdir(parents=True, exist_ok=True)
    cat = str(q.get("category") or "").strip()
    zone = str(q.get("zone") or "SFW")
    subdir = str(q.get("subdir") or "")
    name = str(q.get("name") or info.get("name") or "").strip()
    author = str(q.get("author") or info.get("author") or "").strip()
    addr = mm.norm_addr(str(q.get("addr") or info.get("addr") or ""))
    cover = str(q.get("cover_url") or info.get("cover") or "")
    secs = max(30, int(q.get("seconds") or 900))
    exts = tuple(mm.ARCHIVE_EXT)

    def norm1(x):
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (x or "").lower())

    def looks_like(f):
        if not name:
            return True
        a, b = norm1(f.stem), norm1(name)
        if not a or not b:
            return True
        return (a in b) or (b in a) or (len(b) >= 5 and b[:5] in a)

    def pick(files, since):
        for f in files:
            try:
                if not f.is_file() or f.suffix.lower() in mm.PARTIAL_EXT:
                    continue
                if f.suffix.lower() not in exts or f.stat().st_mtime < since:
                    continue
                if not looks_like(f):
                    continue
                s1 = f.stat().st_size
                time.sleep(1.0)
                if s1 == 0 or f.stat().st_size != s1:
                    continue                     # 还在写
                return f
            except OSError:
                continue
        return None

    hit = pick(sorted([f for f in dl_dir.iterdir() if f.is_file()],
                      key=lambda x: -x.stat().st_mtime), time.time() - 1800)
    if hit:
        job.set(1, 4, "发现刚下好的文件：%s" % hit.name)
    else:
        seen = {f.name for f in dl_dir.iterdir() if f.is_file()}
        t0 = time.time()
        loose_logged = False
        while time.time() - t0 < secs:
            if job.cancelled():
                raise mm.BackupCancelled()
            el = int(time.time() - t0)
            job.set(1, 4, "等你在自己的浏览器里下完… 第 %ds（目录 %s）" % (el, dl_dir))
            news = [f for f in dl_dir.iterdir() if f.is_file() and f.name not in seen]
            hit = pick(news, time.time() - 5)
            if not hit and news:
                # 名字对不上也别死等（文件名常是 名称-版本.pmp 之类）：
                # 过 20 秒就认"目录里新出现、且已写稳的压缩包"
                if el >= 20:
                    if not loose_logged:
                        mm.log("下载目录里出现新文件（名字没完全对上，放宽接受）：%s"
                               % ", ".join(f.name for f in news[:5]))
                        loose_logged = True
                    cands = [f for f in news if f.suffix.lower() in exts
                             and f.suffix.lower() not in mm.PARTIAL_EXT]
                    hit = pick(sorted(cands, key=lambda x: -x.stat().st_mtime), time.time() - 600)
            if hit:
                break
            time.sleep(1.0)
    if not hit:
        raise RuntimeError("没等到下载好的文件（在 %s 里找 %s）。"
                           "确认一下浏览器是不是下到这个目录，或自己下好后点「监视下载目录」"
                           % (dl_dir, "*.pmp/*.ttmp2/*.zip" ))

    job.set(2, 4, "入库（写 地址.txt、自动编号）…")
    if cat:
        target, _exist, _removed = import_or_update(cfg, hit, cat, zone, subdir,
                                                    author or None, name or None, None, addr, info, job)
        got = ""
        if q.get("cover", True) and cover.lower().startswith("http"):
            job.set(3, 4, "抓封面当预览图…")
            cu = cover
            ext = "." + (cu.rsplit(".", 1)[-1].split("?")[0].lower() if "." in cu else "jpg")
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                ext = ".jpg"
            tdir = Path(target)
            try:
                ok, _why = _save_url(cfg, cu, tdir.parent / (tdir.name + ext),
                                     use_browser=mm.browser_running(cfg))
                got = ext if ok else ""
            except Exception:
                got = ""
        job.set(3, 4, "重扫索引、写标签、生成 Excel…")
        mm.cmd_scan(cfg, quiet=True)
        mod_index(force=True)
        _meta = apply_meta_after_import(
            cfg, target,
            tags=info.get("tags") or q.get("tags") or [],
            affects=q.get("affects") if q.get("affects") is not None else info.get("affects"),
            addr=addr)
        record_site_update(cfg, target, addr)
        if q.get("export", True):
            _job_export(job)
        return {"mod": Path(target).name, "rel": safe_rel(target, cfg.get("root") or ""),
                "updated_existing": bool(_exist), "removed": _removed,
                "file": hit.name, "cover": bool(got), "tags": _meta.get("tags") or [],
                "affects": _meta.get("affects") or "",
                "target": str(target), "dir": str(dl_dir)}

    ib = Path(mm.resolve_dirs(cfg)[1])
    ib.mkdir(parents=True, exist_ok=True)
    tgt = ib / hit.name
    if tgt.exists():
        tgt = ib / ("%s_%d%s" % (hit.stem, int(time.time()), hit.suffix))
    shutil.move(str(hit), str(tgt))
    mm.cmd_scan(cfg, quiet=True)
    mod_index(force=True)
    return {"inbox": str(tgt), "file": hit.name, "dir": str(dl_dir), "no_category": True}


def find_mod_row(st, target):
    """按完整路径精确匹配索引库记录；路径对不上时只按唯一同名兜底（多个同名返回 None）。

    为什么要有兜底：rename/导入后的路径写法可能跟扫描写进库的不完全一致
    （大小写、结尾斜杠），但只按名字找又会在两个同名 Mod 之间写错行。
    """
    name = Path(str(target)).name
    want = str(target).rstrip("\\/").lower()
    rows = st.all()
    for m in rows:
        if str(m.get("folder") or "").rstrip("\\/").lower() == want:
            return m
    same = [m for m in rows if Path(str(m.get("folder") or "")).name == name]
    if len(same) == 1:
        return same[0]
    if len(same) > 1:
        mm.log("找记录：有 %d 个同名文件夹、路径又没匹配上，跳过 %s（免得写错行）" % (len(same), name))
    return None


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def parse_multipart(raw: bytes, ctype: str):
    """极简 multipart/form-data 解析 → (普通字段 dict, 文件 dict{字段: (文件名, 字节)})。

    只为自己用（浏览器上传一个文件 + 几个文本字段），不追求规范全覆盖。
    """
    m = re.search(r'boundary="?([^";]+)"?', ctype or "")
    if not m:
        raise ValueError("没有 boundary")
    bd = b"--" + m.group(1).encode("latin-1")
    fields, files = {}, {}
    parts = raw.split(bd)
    for part in parts[1:-1]:                 # 首尾是 preamble / epilogue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        hs = head.decode("utf-8", "replace")
        nm = re.search(r'name="([^"]*)"', hs)
        if not nm:
            continue
        fn = re.search(r'filename="([^"]*)"', hs)
        if fn and fn.group(1):
            files[nm.group(1)] = (fn.group(1), data)
        else:
            fields[nm.group(1)] = data.decode("utf-8", "replace")
    return fields, files


def save_upload(files) -> str:
    """把浏览器上传的那个文件落到「待导入」目录，返回路径"""
    name, data = next(iter(files.values()))
    safe = re.sub(r'[\\/:*?"<>|]+', "_", Path(str(name or "上传文件")).name) or "上传文件"
    dest = Path(mm.resolve_dirs(cfg_now())[1]) / safe
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.with_name("%s_%d%s" % (dest.stem, int(time.time()), dest.suffix))
    dest.write_bytes(data)
    mm.log("收到上传的新文件：%s（%.1f MB）" % (dest.name, len(data) / 1048576.0))
    return str(dest)


def _site_info(cfg, addr):
    """读站点更新信息：先直连；被挡（NSFW 未登录等）再借内置浏览器的登录态重试。"""
    info = mm.fetch_site_update(cfg, addr)
    if info.get("ok"):
        return info
    try:
        ck = _browser_cookie_header(cfg)
        if ck:
            info2 = mm.fetch_site_update(cfg, addr, cookies=ck)
            if info2.get("ok"):
                info2["source"] = (info2.get("source") or "") + "+cookie"
                return info2
    except Exception:
        pass
    return info


def record_site_update(cfg, target, addr):
    """下载/入库后把站点上的「最后更新时间」记成基线（这样以后才比得出有没有新版）。"""
    if not (str(addr or "").strip()):
        return {}
    try:
        info = _site_info(cfg, addr)
        if not info.get("ok"):
            mm.log("记站点更新时间：没读到（%s）%s" % (Path(str(target)).name[:40], info.get("error") or ""))
            return {}
        st = mm.Store()
        row = find_mod_row(st, target)
        if row is not None:
            st.set_site_info(row["folder"], updated=info["updated"], latest=info["updated"],
                             version=info.get("version") or "", checked=now_str(), avail=0)
        st.cx.close()
        return info
    except Exception as e:
        mm.log("记站点更新时间失败：%s" % e)
        return {}


def apply_meta_after_import(cfg, target, tags=None, affects=None, addr=None):
    """入库后给这个 Mod 写「标签」和「影响/替换」（folder 用索引库里的键，保证和前端一致）。

    两项都来自 Mod 站的页面信息（扩展 / 书签小工具 / 内置浏览器解析都会带过来）：
      tags    = 站点的 Tags 区
      affects = 站点的「Affects / Replaces」——它替换的是游戏里哪件装备/哪个部位
    None = 这项不动；"" = 明确清空。
    """
    addr = (addr or "").strip()
    want_tags = mm.norm_tags(list(tags or [])) if tags is not None else None
    want_aff = mm.norm_affects(affects) if affects is not None else None
    out = {"tags": [], "affects": ""}
    if not want_tags and want_aff is None:
        return out
    name = Path(target).name
    try:
        mm.cmd_scan(cfg, quiet=True)
        st = mm.Store()
        hit = find_mod_row(st, target)
        if hit is not None:
            m = hit
            if want_tags:
                out["tags"] = st.set_tags(m["folder"], want_tags)
            if want_aff is not None:
                out["affects"] = st.set_affects(m["folder"], want_aff)
            st.cx.close()
            return out
        st.cx.close()
        mm.log("写页面信息：索引里没找到 %s，先跳过" % name)
    except Exception as e:
        mm.log("写页面信息失败（%s）：%s" % (name, e))
    return out


def apply_tags_after_import(cfg, target, tags):
    """兼容旧名字：只打标签"""
    return apply_meta_after_import(cfg, target, tags=tags or []).get("tags") or []


# ------------------------------------------------------- 检查更新 / 更新 Mod
def find_existing_by_addr(addr, modid=""):
    """按站点地址找库里已有的 Mod（同一个 modid / shortId 就算同一条）。

    用它把「又下载了一次」认成「更新」，不再新建一条重复的。
    """
    key = mm.site_key(addr, modid)
    if not key:
        return None
    st = mm.Store()
    hit = None
    for m in st.all():
        if mm.site_key(m.get("addr") or "", "") == key:
            hit = m
            break
    st.cx.close()
    return hit


def import_or_update(cfg, src, cat, zone="SFW", subdir="", author=None, name=None,
                     seq=None, addr="", info=None, job=None):
    """入库：库里没有就新建一条；**同一站点地址已有**就覆盖那条（保留元数据）。

    返回 (target Path, 已有的那条记录 or None, 被换掉的旧文件名列表)
    """
    hit = find_existing_by_addr(addr, (info or {}).get("modid") or "")
    if hit is not None and Path(str(hit.get("folder") or "")).is_dir():
        if job:
            job.set(job.done, job.total, "识别为已有 Mod 的新版本 → 覆盖更新…")
        rep = mm.replace_mod_payload(cfg, hit["folder"], src, mode="auto")
        try:                          # 原语义是「把文件收进库里」→ 替换完不留来源副本
            p = Path(src)
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(str(p), ignore_errors=True)
        except OSError:
            pass
        mm.log("按站点地址认成已有 Mod：%s → 覆盖更新（换掉 %s，放入 %s）"
               % (str(hit.get("name"))[:40], "、".join(rep["removed"]) or "无同名旧文件",
                  "、".join(rep["added"])))
        return Path(hit["folder"]), hit, rep["removed"]
    return mm.import_mod(cfg, str(src), cat, zone, subdir, author, name, seq,
                         mm.norm_addr(addr), True), None, []


def _pick_download_link(html: str) -> str:
    """从 Mod 页 HTML 里挑主下载直链（#mod-download-link 优先，其次任意 /files/ 链接）"""
    m = (re.search(r'id="mod-download-link"[^>]*href="([^"]+)"', html)
         or re.search(r'href="([^"]+)"[^>]*id="mod-download-link"', html)
         or re.search(r'href="([^"]*/files/[^"]+)"', html))
    if not m:
        return ""
    u = _html.unescape(m.group(1))
    if u.startswith("/"):
        u = "https://www.xivmodarchive.com" + u
    return u if u.lower().startswith("http") else ""


def _site_download(cfg, addr, inbox, job=None):
    """从站点下这条 Mod 的最新文件。返回 (文件路径, 站点更新信息)。

    ① 借内置浏览器的登录态直接抓页面 → 取直链 → 下（最省事，不用开浏览器窗口）
    ② 不行才开内置浏览器，让页面自己下载（NSFW + 人机验证那种）
    """
    info = _site_info(cfg, addr)
    page = str(addr or "").strip()
    ck = _browser_cookie_header(cfg)
    inbox = Path(inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    dl = ""
    try:
        html = mm._site_get(page, ck).decode("utf-8", "replace")
        dl = _pick_download_link(html)
    except Exception as e:
        mm.log("找下载直链失败（%s），改用内置浏览器" % str(e)[:80])
    if dl:
        try:
            p = _stream_to(dl, inbox, cookies=ck, referer=page,
                           on_tick=(lambda d, t: job.set(job.done, job.total,
                                                         "下载中… %s%s" % (mm.fmt_size(d),
                                                                          (" / " + mm.fmt_size(t)) if t else ""))
                                    if job else None),
                           should_cancel=(job.cancelled if job else None))
            return Path(p), info
        except Exception as e:
            mm.log("直链下载失败（%s），改用内置浏览器" % str(e)[:80])
    try:
        mm.launch_browser(cfg, page)
        mm.browser_wait_ready(cfg, timeout=60)
        _href, path = mm.browser_download(cfg, inbox, timeout=900, url=page)
        return Path(path), info
    except Exception as e:
        raise RuntimeError("下载失败：%s" % str(e)[:140])


def _local_ref_time(folder) -> str:
    """本地这份 Mod 的文件时间（老数据没有站点基线时，拿它当参照比一比）"""
    try:
        ts = [f.stat().st_mtime for f in Path(folder).iterdir()
              if f.is_file() and f.suffix.lower() not in mm.PARTIAL_EXT]
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(max(ts))) if ts else ""
    except Exception:
        return ""


def _job_update_check(job: Job):
    """检查站点上有没有比本地新的版本（读站点的 Last Version Update 跟基线比）"""
    cfg = cfg_now()
    st = mm.Store()
    rows = st.all()
    st.cx.close()
    want = {str(f) for f in (job.params.get("folders") or [])}
    todo = [m for m in rows if ((not want) or m["folder"] in want) and (m.get("addr") or "").strip()]
    if not todo:
        raise RuntimeError("没有可检查的 Mod（选中的这些没有站点地址）")
    has, cur, unknown = [], 0, []
    for i, m in enumerate(todo, 1):
        if job.cancelled():
            raise mm.BackupCancelled()
        job.set(i - 1, len(todo), "%s ｜ %s" % (m["name"][:34], m["addr"]))
        info = _site_info(cfg, m["addr"])
        if not info.get("ok"):
            unknown.append({"folder": m["folder"], "name": m["name"],
                            "why": (info.get("error") or "读不到站点信息")[:120]})
            continue
        latest = info["updated"]
        base = m.get("site_updated") or ""
        ref = "站点基线"
        if not base:                       # 老数据：拿本地文件时间当参照
            base = _local_ref_time(m["folder"])
            ref = "本地文件时间"
        avail = 1 if (latest and base and latest > base) else 0
        st2 = mm.Store()
        st2.set_site_info(m["folder"], latest=latest, version=info.get("version") or "",
                          checked=now_str(), avail=avail)
        st2.cx.close()
        item = {"folder": m["folder"], "rel": m.get("rel") or "", "name": m["name"],
                "local": base, "latest": latest, "ref": ref,
                "version": info.get("version") or "", "patch": info.get("patch") or "",
                "avail": bool(avail)}
        if avail:
            has.append(item)
        else:
            cur += 1
    mod_index(force=True)
    mm.log("检查更新：%d 条里 %d 条有新版，%d 条最新，%d 条读不到"
           % (len(todo), len(has), cur, len(unknown)))
    return {"checked": len(todo), "has_update": has, "up_to_date": cur,
            "unknown": unknown, "total": len(todo)}


def _job_mod_update(job: Job):
    """从站点下载最新文件覆盖本地（保留 地址.txt / 预览图 / 编号，旧文件进回收站）"""
    cfg = cfg_now()
    mode = str(job.params.get("mode") or "same_name")
    folders = [str(f) for f in (job.params.get("folders") or [])]
    if not folders:
        raise RuntimeError("没选要更新的 Mod")
    inbox = mm.resolve_dirs(cfg)[1]
    st = mm.Store()
    rows = {str(m["folder"]): m for m in st.all()}
    st.cx.close()
    done, failed = [], []
    for i, folder in enumerate(folders, 1):
        if job.cancelled():
            raise mm.BackupCancelled()
        m = rows.get(folder)
        if m is None:
            failed.append("索引里找不到：%s" % folder)
            continue
        addr = (m.get("addr") or "").strip()
        if not addr:
            failed.append("%s：没有站点地址，无法从站点更新（可以手动上传替换）" % m["name"])
            continue
        if "heliosphere" in addr:
            failed.append("%s：heliosphere 的下载是页面上那个按钮（接口没公开）——"
                          "点「打开页面下载」，下好后用「上传新文件替换」" % m["name"])
            continue
        try:
            job.set(i - 1, len(folders), "下载最新版：%s" % m["name"][:34])
            path, info = _site_download(cfg, addr, inbox, job=job)
            job.set(i - 1, len(folders), "替换文件：%s" % m["name"][:34])
            rep = mm.replace_mod_payload(cfg, folder, path, mode=mode)
            try:
                path.unlink()               # 已经拷进 Mod 文件夹，暂存区不用留副本
            except OSError:
                pass
            st2 = mm.Store()
            st2.set_site_info(folder, updated=info.get("updated") or "",
                              latest=info.get("updated") or "",
                              version=info.get("version") or "",
                              checked=now_str(), avail=0)
            st2.cx.close()
            done.append({"folder": folder, "name": m["name"], "removed": rep["removed"],
                         "added": rep["added"], "kept": rep["kept"],
                         "updated": info.get("updated") or "", "version": info.get("version") or "",
                         "patch": info.get("patch") or ""})
        except Exception as e:
            mm.log("更新失败 %s：%s" % (m["name"][:40], e))
            failed.append("%s：%s" % (m["name"], str(e)[:140]))
    if done:
        job.set(len(folders), len(folders), "重扫索引…")
        _job_scan(job)
        if job.params.get("export", True):
            _job_export(job)
    return {"ok": done, "failed": failed}


def _job_import_file(job: Job):
    """浏览器已经下好了，直接把那个文件入库。

    为什么需要：让管理器去"下载目录里猜文件名"不可靠（名字/目录差一点就永远等不到）。
    扩展下载完会拿到确切的文件路径（chrome.downloads.search 的 filename），
    直接把路径送过来 —— 见 /api/push/downloaded。
    """
    cfg = cfg_now()
    q = job.params or {}
    info = q.get("page") if isinstance(q.get("page"), dict) else {}
    src = Path(str(q.get("file") or "").strip().strip('"'))
    if not src.is_file():
        raise RuntimeError("找不到这个文件：%s（可能被移动或删掉了）" % src)
    cat = str(q.get("category") or "").strip()
    zone = str(q.get("zone") or "SFW")
    subdir = str(q.get("subdir") or "")
    author = str(q.get("author") or info.get("author") or "").strip()
    name = bare_mod_name(q.get("name") or info.get("name") or "", author)
    addr = mm.norm_addr(str(q.get("addr") or info.get("addr") or ""))
    cover = str(q.get("cover_url") or info.get("cover") or "")
    try:
        size = src.stat().st_size
    except OSError:
        size = 0

    if cat:
        job.set(1, 3, "入库（写 地址.txt、自动编号）…")
        target, _exist, _removed = import_or_update(cfg, src, cat, zone, subdir,
                                                    author or None, name or None, None, addr, info, job)
        got = ""
        if q.get("cover", True) and cover.lower().startswith("http"):
            job.set(2, 3, "抓封面当预览图…")
            ext = "." + (cover.rsplit(".", 1)[-1].split("?")[0].lower() if "." in cover else "jpg")
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                ext = ".jpg"
            tdir = Path(target)
            try:
                ok, _why = _save_url(cfg, cover, tdir.parent / (tdir.name + ext),
                                     use_browser=mm.browser_running(cfg))
                got = ext if ok else ""
            except Exception:
                got = ""
        job.set(3, 3, "重扫索引、写标签、生成 Excel…")
        mm.cmd_scan(cfg, quiet=True)
        mod_index(force=True)
        _meta = apply_meta_after_import(
            cfg, target,
            tags=q.get("tags") or info.get("tags") or [],
            affects=q.get("affects") if q.get("affects") is not None else info.get("affects"),
            addr=addr)
        record_site_update(cfg, target, addr)
        if q.get("export", True):
            _job_export(job)
        return {"mod": Path(target).name, "rel": safe_rel(target, cfg.get("root") or ""),
                "updated_existing": bool(_exist), "removed": _removed,
                "file": src.name, "cover": bool(got), "tags": _meta.get("tags") or [],
                "affects": _meta.get("affects") or "", "size": size,
                "human": mm.fmt_size(size), "target": str(target)}

    job.set(1, 2, "放到「待导入」…")
    ib = Path(mm.resolve_dirs(cfg)[1])
    ib.mkdir(parents=True, exist_ok=True)
    tgt = ib / src.name
    if tgt.exists():
        tgt = ib / ("%s_%d%s" % (src.stem, int(time.time()), src.suffix))
    shutil.move(str(src), str(tgt))
    mm.cmd_scan(cfg, quiet=True)
    mod_index(force=True)
    return {"inbox": str(tgt), "file": src.name, "size": size, "human": mm.fmt_size(size),
            "no_category": True}


JOB_FUNCS = {"scan": _job_scan, "export": _job_export, "run": _job_run,
             "backup": _job_backup, "restore": _job_restore,
             "import": _job_import, "renumber": _job_renumber,
             "download": _job_download, "watch": _job_watch,
             "selfdownload": _job_selfdownload, "importfile": _job_import_file,
             "fetch": _job_fetch,
             "update_check": _job_update_check, "mod_update": _job_mod_update}


def start_job(kind: str, params: dict | None = None):
    if kind not in JOB_FUNCS:
        return None, "不认识的任务：%s" % kind
    with JOB_LOCK:
        cur = JOBS["cur"]
        if cur is not None and cur.state == "running":
            return None, "已经有一个任务在跑了，等它结束或点取消"
        job = Job(kind, params)
        JOBS["cur"] = job

    def run():
        try:
            job.result = JOB_FUNCS[kind](job)
            job.state = "cancelled" if job.cancelled() else "done"
        except mm.BackupCancelled:
            job.state = "cancelled"
        except Exception as e:
            job.state = "error"
            job.error = "%s" % e
            mm.log(traceback.format_exc())
        finally:
            job.t1 = time.time()
            mod_index(force=True)

    threading.Thread(target=run, daemon=True).start()
    return job, ""


# --------------------------------------------------------------------- 只读接口
def api_state():
    cfg = cfg_now()
    mods = mm.Store().all()
    by = {}
    for m in mods:
        by[m["category"]] = by.get(m["category"], 0) + 1
    order = cfg.get("category_order") or []
    cats = sorted(by, key=lambda c: (order.index(c) if c in order else 99, c))
    dl, ib = mm.resolve_dirs(cfg) if cfg.get("root") else ("", "")
    root_ok = bool(cfg.get("root")) and Path(cfg["root"]).is_dir()
    excel_ok = bool(cfg.get("excel")) and Path(cfg["excel"]).parent.is_dir()
    return {"version": mm.APP_VERSION, "root": cfg.get("root") or "",
            "manager_version": MANAGER_VERSION, "manager_build": MANAGER_BUILD,
            "min_plugin_version": MIN_PLUGIN_VERSION,
            "root_ok": root_ok, "excel_ok": excel_ok,
            "excel_suggest": str(Path(cfg["root"]).parent / "Mod信息汇总表.xlsx")
                             if cfg.get("root") else "",
            "excel": cfg.get("excel") or "", "backup_dir": str(mm.resolve_backup_dir(cfg)),
            "install_dir": mm.find_install_dir(cfg) or "",
            "download_dir": dl, "inbox_dir": ib,
            "total": len(mods), "cats": cats, "cat_counts": {c: by[c] for c in cats},
            "log": str(mm.LOG_PATH), "temp_root": bool(ROOT_OVERRIDE)}


def api_mods():
    cfg = cfg_now()
    _st = mm.Store()
    mods = _st.all()
    tag_map = _st.tags_map()
    _st.cx.close()
    inst_dir = mm.find_install_dir(cfg)
    inst = {}
    if inst_dir:
        try:
            names, raw, _ = mm.list_installed(cfg)
            inst = {m["folder"]: bool(mm.installed_match(m, names, raw)) for m in mods}
        except Exception:
            mm.log(traceback.format_exc())
    root = cfg.get("root") or ""
    out = []
    for m in mods:
        out.append({
            "folder": m["folder"], "rel": m.get("rel") or safe_rel(m["folder"], root),
            "category": m["category"], "subcat": m.get("subcat") or "",
            "seq": m["seq"], "author": m["author"], "nsfw": m["nsfw"], "name": m["name"],
            "addr": m.get("addr") or "",
            "img_name": Path(m["img"]).name if m.get("img") else "",
            "has_img": bool(m.get("img")) and Path(m["img"]).is_file(),
            "ih": (m.get("img_hash") or "")[:16],
            "tags": tag_map.get(m["folder"], []),
            "affects": m.get("affects") or "",
            "site_updated": m.get("site_updated") or "",     # 本地这份的站点更新时间（基线）
            "site_latest": m.get("site_latest") or "",       # 最近一次检查看到的站点值
            "site_version": m.get("site_version") or "",
            "site_checked": m.get("site_checked") or "",
            "update_avail": bool(m.get("update_avail")),
            "installed": inst.get(m["folder"]) if inst_dir else None,
        })
    return {"mods": out, "install_dir": inst_dir or ""}


# ---------------------------------------------------------------- 标签
def api_tags():
    st = mm.Store()
    tags = st.all_tags()
    st.cx.close()
    return {"tags": tags, "total": len(tags)}


def _tag_folders(b) -> list:
    fs = b.get("folders")
    if isinstance(fs, list) and fs:
        return [str(x) for x in fs]
    f = b.get("folder")
    return [str(f)] if f else []


def api_affects():
    """所有已录过的「影响/替换」取值 + 条数（界面做建议/筛选）"""
    st = mm.Store()
    items = st.affects_all()
    st.cx.close()
    return {"items": items, "total": len(items)}


def api_mod_set_affects(b):
    """设置某条 Mod 的「影响/替换」（空串 = 清空）"""
    folder = str(b.get("folder") or "")
    if not folder:
        raise SystemExit("缺少 folder")
    st = mm.Store()
    got = st.set_affects(folder, b.get("affects"))
    st.cx.close()
    mod_index(force=True)
    mm.log("设置影响/替换：%s -> %s" % (Path(folder).name, got or "（空）"))
    return {"ok": True, "folder": folder, "affects": got}


def api_mod_set_tags(b):
    """整条覆盖某条 Mod 的标签"""
    folder = str(b.get("folder") or "")
    if not folder:
        raise SystemExit("缺少 folder")
    st = mm.Store()
    got = st.set_tags(folder, b.get("tags") or [])
    st.cx.close()
    mod_index(force=True)
    mm.log("设置标签：%s -> %s" % (Path(folder).name, got or "（空）"))
    return {"ok": True, "folder": folder, "tags": got}


def api_mod_add_tags(b):
    folders = _tag_folders(b)
    tags = b.get("tags") or []
    if not folders or not tags:
        raise SystemExit("需要 folder/folders 与 tags")
    st = mm.Store()
    n = st.add_tags(folders, tags)
    st.cx.close()
    mod_index(force=True)
    want = mm.norm_tags(tags)
    mm.log("加标签：%d 条 Mod × %s（新增 %d）" % (len(folders), want, n))
    return {"ok": True, "added": n, "mods": len(folders), "tags": want}


def api_mod_remove_tags(b):
    folders = _tag_folders(b)
    tags = b.get("tags") or []
    if not folders or not tags:
        raise SystemExit("需要 folder/folders 与 tags")
    st = mm.Store()
    n = st.remove_tags(folders, tags)
    st.cx.close()
    mod_index(force=True)
    want = mm.norm_tags(tags)
    mm.log("去标签：%d 条 Mod × %s（删除 %d）" % (len(folders), want, n))
    return {"ok": True, "removed": n, "mods": len(folders), "tags": want}


def api_categories():
    cfg = cfg_now()
    root = Path(cfg["root"] or "")
    order = list(cfg.get("category_order") or [])
    on_disk = []
    if root.is_dir():
        on_disk = [d.name for d in sorted(root.iterdir()) if d.is_dir()]
    mods = mm.Store().all()
    counts, subs = {}, {}
    for m in mods:
        counts[m["category"]] = counts.get(m["category"], 0) + 1
        if m.get("subcat"):
            subs.setdefault(m["category"], {}).setdefault(m["subcat"], 0)
            subs[m["category"]][m["subcat"]] += 1
    names = []
    for c in sorted(set(order) | set(on_disk) | set(counts),
                    key=lambda c: (order.index(c) if c in order else 99, c)):
        names.append({"name": c, "count": counts.get(c, 0), "on_disk": c in on_disk,
                      "subcats": [{"name": s, "count": n}
                                  for s, n in sorted(subs.get(c, {}).items())]})
    # 磁盘上有、但库里/顺序里没有的子分类目录
    if root.is_dir():
        for c in names:
            for zone in ("SFW", "NSFW"):
                d = root / c["name"] / zone
                if not d.is_dir():
                    continue
                for e in sorted(d.iterdir()):
                    if e.is_dir() and not mm.MOD_RE.match(e.name):
                        c.setdefault("disk_subcats", [])
                        if e.name not in c["disk_subcats"]:
                            c["disk_subcats"].append(e.name)
    return {"cats": names, "order": order}


def api_dupes():
    groups = mm.find_duplicates(mm.Store().all())
    out = []
    for g in groups:
        # mod_manager.find_duplicates 返回 (原因, 说明, [记录...])
        if isinstance(g, (list, tuple)) and len(g) >= 3:
            reason, detail, items = str(g[0]), str(g[1]), list(g[2])
        elif isinstance(g, dict):
            reason = str(g.get("reason") or "")
            detail = str(g.get("key") or g.get("detail") or "")
            items = list(g.get("mods") or [])
        else:
            reason, detail, items = "", "", []
        out.append({"reason": reason, "detail": detail,
                    "mods": [{"folder": m["folder"], "name": m["name"],
                              "author": m["author"], "category": m["category"],
                              "seq": m["seq"], "rel": m.get("rel") or m["folder"],
                              "addr": m.get("addr") or ""} for m in items]})
    return {"groups": out, "total": len(out)}


def api_install():
    cfg = cfg_now()
    d = mm.find_install_dir(cfg)
    mods = mm.Store().all()
    ok = bool(d and Path(d).is_dir())
    names, raw, _ = mm.list_installed(cfg) if ok else (set(), [], "")
    missing = []
    if ok:
        for m in mods:
            if not mm.installed_match(m, names, raw):
                missing.append({"folder": m["folder"], "name": m["name"],
                                "author": m["author"], "category": m["category"],
                                "seq": m["seq"]})
    return {"dir": d or "", "ok": ok, "folders": len(raw),
            "installed": len(mods) - len(missing) if ok else 0,
            "missing": missing, "total": len(mods)}


def api_backups():
    cfg = cfg_now()
    d = mm.resolve_backup_dir(cfg)
    items = []
    if d.is_dir():
        for q in sorted(d.glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
            row = {"name": q.name, "path": str(q), "size": q.stat().st_size,
                   "mtime": q.stat().st_mtime, "human": mm.fmt_size(q.stat().st_size)}
            try:
                info = mm.inspect_backup(q)
                row.update({"mods": len(info["mods"]), "files": info["n_files"],
                            "raw": mm.fmt_size(info["raw_bytes"]),
                            "has_index": info["has_db"], "has_excel": info["has_excel"],
                            "cats": info["cats"],
                            "created": (info.get("manifest") or {}).get("备份时间", "")})
            except Exception:
                pass
            items.append(row)
    return {"dir": str(d), "items": items}


def api_inspect(q):
    f = (q.get("f") or [""])[0]
    if not Path(f).is_file():
        return {"ok": False, "error": "备份文件不存在"}
    d = mm.inspect_backup(f)
    mf = d.get("manifest") or {}
    return {"ok": d["ok"], "error": d["error"], "mods": len(d["mods"]),
            "files": d["n_files"], "raw": mm.fmt_size(d["raw_bytes"]),
            "zip": mm.fmt_size(d["bytes"]), "has_index": d["has_db"],
            "has_excel": d["has_excel"], "cats": d["cats"],
            "created": mf.get("备份时间", ""), "mod_list": d["mods"][:200]}


def api_images(q):
    """列出某条 Mod 相关的所有图片（文件夹内递归 + 同级同名的预览图）"""
    cfg = cfg_now()
    folder = (q.get("f") or [""])[0]
    m = one_mod(cfg, folder)
    if not m:
        return {"error": "找不到这条 Mod（或路径不在 Mod 目录里）"}
    root = Path(cfg.get("root") or "")
    fdir = Path(m["folder"])
    cur = str(m.get("img") or "")
    out, seen = [], set()

    def add(path, where):
        path = Path(path)
        if not path.is_file() or path.suffix.lower() not in mm.IMG_EXT:
            return
        k = str(path.resolve())
        if k in seen:
            return
        seen.add(k)
        try:
            sz = path.stat().st_size
        except OSError:
            sz = 0
        out.append({"path": k, "name": path.name, "rel": safe_rel(path, root),
                    "where": where, "size": sz, "human": mm.fmt_size(sz),
                    "is_current": (k == str(Path(cur).resolve())) if cur else False,
                    "thumb": "/api/img?p=%s&w=200" % urllib.parse.quote(k),
                    "raw": "/api/rawimg?p=%s" % urllib.parse.quote(k)})

    if cur:
        add(Path(cur), "当前预览图")
    for p2 in sorted(fdir.rglob("*")):
        add(p2, "文件夹内")
    for ext in mm.IMG_EXT:
        add(fdir.parent / (fdir.name + ext), "同级同名")
    return {"folder": str(fdir), "current": cur, "count": len(out), "images": out}


PAGE_IMAGES_JS = ("JSON.stringify((function(){var out=[];"
                  "[].slice.call(document.querySelectorAll('img')).forEach(function(e){"
                  "var s=e.src||e.getAttribute('data-src')||e.getAttribute('data-original')||'';"
                  "if(s.indexOf('/mod-images/')>-1){out.push(s);}});"
                  "return out;})())")


def page_images(cfg):
    """内置浏览器当前页面上的所有 Mod 图片（画廊）"""
    try:
        raw = mm.browser_eval(cfg, PAGE_IMAGES_JS, tries=2)
    except SystemExit:
        raise
    out, seen = [], set()
    try:
        for u in json.loads(raw or "[]"):
            if u and u not in seen:
                seen.add(u)
                out.append(u)
    except Exception:
        pass
    return out


def _save_url(cfg, u, dest, use_browser=True):
    """把网址图片存到 dest：先直连，失败再借内置浏览器 cookie。返回 (ok, 说明)"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    first = ""
    try:
        u = urllib.parse.quote(u, safe=":/?&=%~#[]@!$&'()*+,;")
    except Exception:
        pass
    for attempt in range(2):                      # 网络/TLS 偶发抽风，直连再试一次
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": BROWSER_UA,
                "Referer": "https://www.xivmodarchive.com/"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = r.read()
            if not data:
                raise ValueError("空响应")
            dest.write_bytes(data)
            return True, "直连"
        except Exception as e:
            first = str(e)
            if attempt == 0:
                time.sleep(0.8)
    if use_browser:
        try:
            mm.browser_fetch(cfg, u, dest)
            return True, "借浏览器"
        except (SystemExit, Exception) as e2:
            return False, "%s / %s" % (first, e2)
    return False, first


def _modid_of(url: str) -> str:
    m = re.search(r"/modid/(\d+)", url or "")
    if m:
        return m.group(1)
    t = (url or "").strip()
    return t if t.isdigit() else ""


def _clean_url(text: str) -> str:
    """支持：完整链接 / modid/12345 / 直接给编号 12345"""
    t = (text or "").strip()
    if not t:
        return ""
    if t.isdigit():
        return "https://www.xivmodarchive.com/modid/%s" % t
    return mm.norm_addr(t)


def api_inbox_page_get():
    d = LAST_PAGE["data"]
    return {"page": d, "at": LAST_PAGE["at"],
            "age": round(time.time() - LAST_PAGE["at"], 1) if d else None}


def bare_mod_name(name, author):
    """XMA 的 h1 常是 "[作者] 名称"，入库时要的是"名称"本身（作者单独一列）。"""
    nm = str(name or "").strip()
    au = str(author or "").strip()
    if au and nm.startswith("[" + au + "]"):
        nm = nm[len(au) + 2:].strip()
    return nm or str(name or "").strip()


def api_inbox_page_put(payload):
    """接收书签小工具送来的页面信息（也兼容 text/plain 的 JSON）"""
    if not isinstance(payload, dict):
        return {"error": "格式不对"}
    url = str(payload.get("url") or "")
    m = re.search(r"/modid/(\d+)", url)
    modid = str(payload.get("modid") or (m.group(1) if m else ""))
    imgs, seen = [], set()
    for u2 in (payload.get("imgs") or []):
        u2 = str(u2 or "").strip()
        if u2.lower().startswith("http") and u2 not in seen:
            seen.add(u2)
            imgs.append(u2)
        if len(imgs) >= 60:
            break
    dl_raw = str(payload.get("dl") or "").strip()
    # 坑：老书签小工具送来的是相对路径（/private/xxx/files/x.pmp），
    # 之前直接把这种值当下载地址，前端一 open 就被解析成 http://127.0.0.1:8765/private/... ✗
    if dl_raw.startswith("/"):
        dl_raw = "https://www.xivmodarchive.com" + dl_raw
    elif dl_raw and not dl_raw.lower().startswith(("http://", "https://", "file://")):
        dl_raw = "https://www.xivmodarchive.com/" + dl_raw.lstrip("/")
    _nm = str(payload.get("name") or payload.get("title") or "").strip()
    _au = str(payload.get("author") or "").strip()
    data = {
        "name": bare_mod_name(_nm, _au),
        "author": str(payload.get("author") or "").strip(),
        "cover": str(payload.get("cover") or "").strip(),
        "imgs": imgs,
        "dl": dl_raw,
        "url": url,
        "title": str(payload.get("title") or "").strip(),
        "modid": modid,
        "addr": ("https://www.xivmodarchive.com/modid/%s" % modid) if modid else url,
        "is_mod": bool(modid),
        "tags": mm.norm_tags(payload.get("tags") or []),
        "races": str(payload.get("races") or "").strip(),
        "genders": str(payload.get("genders") or "").strip(),
        "affects": mm.norm_affects(payload.get("affects")),
        "challenge": False,
        "from": "browser",
    }
    try:
        data["v"] = int(payload.get("v") or 0)      # 书签小工具版本：2 起才带画廊图片
    except (TypeError, ValueError):
        data["v"] = 0
    data["old_bookmarklet"] = data["v"] < 2
    LAST_PAGE["data"] = data
    LAST_PAGE["at"] = time.time()
    mm.log("收到浏览器送来的页面：%s（%s，书签小工具 v%s，画廊 %d 张）"
           % (data["name"][:40] or "?", data["addr"], data["v"], len(data.get("imgs") or [])))
    return {"ok": True, "page": data}


def api_fetch_parse(b):
    """解析 Mod 链接：打开页面、过 Cloudflare、读出 名称/作者/封面/下载直链"""
    cfg = cfg_now()
    url = _clean_url(str(b.get("url") or ""))
    if not url:
        return {"error": "先粘贴一个 Mod 链接，或直接填编号（例如 12345）"}

    def result_from_page(info, source):
        return {"ok": True, "page": info, "url": info.get("url") or url, "from": source,
                "has_download": bool(info.get("dl")), "warn": "",
                "suggest": {"name": info.get("name") or "", "author": info.get("author") or "",
                            "addr": info.get("addr") or "", "cover": info.get("cover") or "",
                            "affects": info.get("affects") or ""}}

    # ① 先看你自己浏览器（书签小工具）推过来的那条页面信息 —— 够用就绝不碰内置浏览器
    pushed = LAST_PAGE.get("data") or {}
    pushed_fresh = bool(pushed) and (time.time() - (LAST_PAGE.get("at") or 0)) < 900
    m_want = re.search(r"/modid/(\d+)", url or "")
    want_id = m_want.group(1) if m_want else ""
    same_mod = (not want_id) or (not pushed.get("modid")) or want_id == pushed.get("modid")
    if (pushed_fresh and pushed.get("is_mod") and same_mod and b.get("use_pushed", True)
            and (pushed.get("dl") or pushed.get("cover") or pushed.get("name"))):
        mm.log("用浏览器推来的页面信息解析：%s（不开内置浏览器）" % (pushed.get("addr") or ""))
        return result_from_page(pushed, "pushed")

    # ② 没开"自动打开内置浏览器"就先别开
    if not cfg.get("auto_open_browser"):
        return {"error": "没开内置浏览器（默认不开）。你可以："
                         "① 用书签小工具在**你自己的浏览器**里点一下，把页面信息推过来（不会开内置浏览器）；"
                         "② 或到「设置」勾选「需要时自动打开内置浏览器」再点解析；"
                         "③ 或直接点「打开内置浏览器」手动打开。",
                "page": pushed if pushed_fresh else None}

    try:
        mm.launch_browser(cfg, url)
    except SystemExit as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": "启动内置浏览器失败：%s" % e}
    try:
        mm.browser_wait_ready(cfg, timeout=int(b.get("wait") or 45))
    except Exception:
        pass
    try:
        info = mm.browser_capture(cfg)
    except Exception as e:
        return {"error": "读取页面失败：%s" % e}
    if not info.get("is_mod"):
        partial = {"name": info.get("name") or "", "author": info.get("author") or "",
                   "cover": info.get("cover") or "", "title": info.get("title") or "",
                   "addr": info.get("addr") or ""}
        if info.get("challenge"):
            return {"error": "页面还在过 Cloudflare 人机验证："
                             "去内置浏览器窗口点一下验证框，再点「解析链接」重试",
                    "page": info, "partial": partial}
        host = ""
        try:
            host = urllib.parse.urlsplit(info.get("url") or "").netloc
        except Exception:
            pass
        if host and "xivmodarchive" not in host:
            return {"error": "自动下载只支持 xivmodarchive.com 的 Mod 页"
                             "（当前是 %s）。可以把名称/作者/地址填好后用「添加 Mod」，"
                             "或者在内置浏览器里手动下载再用「监视下载目录」。" % host,
                    "page": info, "partial": partial}
        return {"error": "这个地址不是 Mod 详情页（网址里要有 /modid/）",
                "page": info, "partial": partial}
    # 有些 Mod 的文件只放在 Files 标签页里：主页面没链接就自动切过去再读一次
    if not info.get("dl") and info.get("filesTab"):
        try:
            # Files 是页内标签，点一下再读
            mm.browser_eval(cfg, 'var t=document.querySelector(\'a[data-toggle="tab"][href$="#files"],a[href="#files"]\');'
                                 '(t&&t.click&&t.click(),t?"clicked":"no-tab")')
            time.sleep(1.5)
            again = mm.browser_capture(cfg)
            if again.get("dl"):
                for k in ("name", "author", "cover", "addr", "modid", "is_mod"):
                    again[k] = again.get(k) or info.get(k)     # 标签页上可能没有这些，保留主页面的
                info = again
        except Exception:
            mm.log(traceback.format_exc())

    warn = ""
    if not info.get("dl"):
        why = []
        if info.get("login"):
            why.append("内置浏览器里看起来没登录 XIVModArchive（下载需要登录，登录一次就会记住）")
        if info.get("hidden"):
            why.append("页面提示内容被隐藏（NSFW 的 Mod 要在站点账号设置里打开成人内容）")
        why.append("也可能这条 Mod 的文件在 Files 标签页里 —— 在内置浏览器里点一下 Files 再重新解析")
        why.append("实在不行就在内置浏览器里手动点下载，再用「监视下载目录」")
        warn = "；".join(why)

    return {"ok": True, "page": info, "url": url,
            "has_download": bool(info.get("dl")),
            "warn": warn,
            "suggest": {"name": info.get("name") or "", "author": info.get("author") or "",
                        "addr": info.get("addr") or "", "cover": info.get("cover") or "",
                        "affects": info.get("affects") or ""}}


def api_pending():
    cfg = cfg_now()
    dl, ib = mm.resolve_dirs(cfg)
    items = []
    try:
        for it in mm.list_pending(cfg):
            items.append({**it, "size_h": mm.fmt_size(it["size"]),
                          "mtime_h": time.strftime("%m-%d %H:%M",
                                                   time.localtime(it["mtime"]))})
    except Exception:
        mm.log(traceback.format_exc())
    return {"download_dir": dl, "inbox_dir": ib, "items": items}


def api_check():
    cfg = cfg_now()
    root = cfg.get("root") or ""
    mods = mm.Store().all()
    problems = []
    for m in mods:
        issues = []
        if not Path(m["folder"]).is_dir():
            issues.append("文件夹不存在")
        if not m["addr"]:
            issues.append("缺 Mod 地址")
        elif m.get("addr_source") != "地址.txt":
            issues.append("地址来自子目录（%s）" % m.get("addr_source"))
        if not m.get("img"):
            issues.append("缺预览图")
        elif m.get("img_source") != "同级同名":
            issues.append("预览图取自%s" % m.get("img_source"))
        if issues:
            problems.append({"folder": m["folder"], "rel": safe_rel(m["folder"], root),
                             "name": m["name"], "author": m["author"],
                             "category": m["category"], "seq": m["seq"],
                             "issues": issues})
    dup = {}
    for m in mods:
        dup.setdefault((m["category"], m["seq"]), []).append(m)
    dups = [{"category": k[0], "seq": k[1],
             "mods": [{"folder": x["folder"], "name": x["name"]} for x in v]}
            for k, v in sorted(dup.items()) if len(v) > 1]
    return {"problems": problems, "dup_seqs": dups, "total": len(mods),
            "clean": not problems and not dups}


def api_settings():
    cfg = cfg_now()
    dl, ib = mm.resolve_dirs(cfg) if cfg.get("root") else ("", "")
    out = {k: v for k, v in cfg.items() if k != "category_order"}
    out["download_resolved"] = dl
    out["inbox_resolved"] = ib
    out["backup_resolved"] = str(mm.resolve_backup_dir(cfg))
    out["install_resolved"] = mm.find_install_dir(cfg) or ""
    out["logging"] = str(mm.LOG_PATH)
    out["db"] = str(mm.DB_PATH)
    out["temp_root"] = bool(ROOT_OVERRIDE)
    out.setdefault("auto_open_browser", False)      # 默认不开内置浏览器
    return out


# ------------------------------------------------------------------ 内置浏览器
def pid_on_port(port: int):
    """按端口找进程号（不依赖 psutil）"""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                             text=True, timeout=10).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].endswith(":%d" % port) \
                    and parts[3].upper() == "LISTENING":
                return int(parts[4])
    except Exception:
        pass
    return None


# ------------------------------------------------- Mod Bridge（游戏内插件）
DEFAULT_BRIDGE_URL = "http://127.0.0.1:42100"


def bridge_cfg(cfg=None):
    cfg = cfg or cfg_now()
    url = str(cfg.get("bridge_url") or DEFAULT_BRIDGE_URL).rstrip("/")
    return url, str(cfg.get("bridge_token") or "")


def bridge_call(path, body=None, method=None, timeout=20, need_token=True):
    """调游戏内插件的本地 HTTP 接口。失败抛 SystemExit（会变成 400 + 可读提示）。"""
    url, token = bridge_cfg()
    full = url + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if need_token and token:
        headers["X-ModBridge-Token"] = token
    req = urllib.request.Request(
        full, data=data, headers=headers,
        method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "ignore")
        return json.loads(raw or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        try:
            detail = json.loads(detail).get("error") or detail
        except Exception:
            pass
        if e.code == 401:
            raise SystemExit("插件说 token 不对（HTTP 401）——去游戏里 /modbridge 复制 token 填到「设置」里")
        raise SystemExit("插件拒绝了请求（HTTP %s）：%s" % (e.code, str(detail)[:200]))
    except Exception as e:
        raise SystemExit(
            "连不上游戏里的插件（%s）。请确认：① 游戏正在运行 ② 已装并启用 Mod Bridge 插件 "
            "③「设置」里的插件地址是 %s ④ token 填了。" % (e, url))


def _bridge_find_package(folder):
    """在 Mod 文件夹里找可安装的 mod 包"""
    p = Path(folder)
    if not p.is_dir():
        raise SystemExit("Mod 文件夹不存在：%s" % folder)
    for ext in (".pmp", ".pcp", ".ttmp", ".ttmp2"):
        hits = sorted((x for x in p.rglob("*") if x.suffix.lower() == ext),
                      key=lambda x: len(str(x)))
        if hits:
            return hits[0]
    raise SystemExit("「%s」里没有 .pmp/.pcp/.ttmp 包，插件没法自动装（已解开的目录要先打包成 .pmp）"
                     % p.name)


def _bridge_find_cover(folder):
    p = Path(folder)
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        sib = p.parent / (p.name + ext)
        if sib.is_file():
            return sib
    for x in sorted(p.rglob("*")):
        if x.is_file() and x.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            return x
    return None


def cover_to_decodable(src, quality=88, max_w=1920):
    """再转一份"游戏内插件自己画封面"能解码的图（真 JPEG）。
    原因：Dalamud 的贴图加载不认 WebP，而 Heliosphere 的包封面往往是 WebP。
    失败返回 None（插件会退回用原图）。"""
    try:
        src = Path(src)
        if not src.is_file():
            return None
        head = src.open("rb").read(12)
        is_jpeg = head[:3] == b"\xff\xd8\xff"
        if is_jpeg and src.suffix.lower() in (".jpg", ".jpeg"):
            return src                              # 本来就是能解码的 jpg
        from PIL import Image
        out_dir = Path(mm.LOG_PATH).parent / "cover_cache_draw"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = "%s_%d" % (re.sub(r"[^\w\-]+", "_", src.stem)[:60], int(src.stat().st_mtime))
        out = out_dir / (stamp + ".jpg")
        if out.is_file() and out.stat().st_size > 0:
            return out
        im = Image.open(src)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        if im.width > max_w:
            try:
                rs = Image.Resampling.LANCZOS
            except Exception:
                rs = Image.LANCZOS
            im = im.resize((max_w, max(1, round(im.height * max_w / im.width))), rs)
        im.save(out, "JPEG", quality=quality, optimize=True)
        return out if out.is_file() and out.stat().st_size > 0 else None
    except Exception as e:
        mm.log("封面转可解码图失败（%s）：%s" % (src, e))
        return None


def cover_to_webp(src, quality=88, max_w=1920):
    """把封面转成真 WebP（Heliosphere 用的就是 WebP），失败返回 None。
    插件拿到它会直接写 mod 根目录的 cover.webp；拿不到就退化成"复制字节改个名"。"""
    try:
        src = Path(src)
        if not src.is_file():
            return None
        head = src.open("rb").read(12)
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return src                      # 本来就是 WebP
        from PIL import Image
        out_dir = Path(mm.LOG_PATH).parent / "cover_cache_webp"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = "%s_%d" % (re.sub(r"[^\w\-]+", "_", src.stem)[:60], int(src.stat().st_mtime))
        out = out_dir / (stamp + ".webp")
        if out.is_file() and out.stat().st_size > 0:
            return out
        im = Image.open(src)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.mode else "RGB")
        if im.width > max_w:
            try:
                rs = Image.Resampling.LANCZOS
            except Exception:
                rs = Image.LANCZOS
            im = im.resize((max_w, max(1, round(im.height * max_w / im.width))), rs)
        im.save(out, "WEBP", quality=quality, method=4)
        return out if out.is_file() and out.stat().st_size > 0 else None
    except Exception as e:
        mm.log("封面转 WebP 失败（%s）：%s" % (src, e))
        return None


def _bridge_payload(folder):
    m = one_mod(cfg_now(), folder)
    if not m:
        raise SystemExit("找不到这条 Mod（先点一下「重新扫描」）")
    pkg = _bridge_find_package(m["folder"])
    cover = _bridge_find_cover(Path(m["folder"]))
    cover_webp = cover_to_webp(cover) if cover else None
    cover_draw = cover_to_decodable(cover) if cover else None
    sub = ("/" + m["subcat"]) if m.get("subcat") else ""
    return {
        "localPath": str(pkg),
        "name": m.get("name") or Path(m["folder"]).name,
        "author": m.get("author") or "",
        "description": "来自 Mod 管理器：%s%s" % (m.get("category") or "", sub),
        "coverPath": str(cover) if cover else "",
        "coverWebpPath": str(cover_webp) if cover_webp else "",
        "coverDrawPath": str(cover_draw) if cover_draw else "",
        "dirName": Path(m["folder"]).name,
        "enable": True,
        "origin": "ModManagerWeb",
    }


def api_bridge():
    """插件状态：/ping 不需要 token"""
    url, token = bridge_cfg()
    out = {"ok": False, "url": url, "has_token": bool(token), "running": mm.browser_running(cfg_now())}
    try:
        out["ping"] = bridge_call("/ping", need_token=False, timeout=6)
        out["ok"] = True
    except SystemExit as e:
        out["error"] = str(e)

    info = plugin_version_info()
    out["plugin_version"] = info.get("version") or ""
    out["plugin_ok"] = bool(info.get("ok"))
    out["min_plugin_version"] = MIN_PLUGIN_VERSION
    out["version_message"] = info.get("message") or ""
    out["manager_version"] = MANAGER_VERSION
    out["manager_build"] = MANAGER_BUILD
    return out


def api_bridge_propose(b):
    folder = str(b.get("folder") or "")
    if not folder:
        raise SystemExit("没指定要装哪条 Mod")
    require_plugin_version()          # 版本监控：插件太旧就别装了
    payload = _bridge_payload(folder)
    r = bridge_call("/propose", payload)
    mm.log("已把「%s」送到游戏内待确认（requestId=%s，包 %s，封面 %s）"
           % (payload["name"], r.get("requestId"), Path(payload["localPath"]).name,
              Path(payload["coverPath"]).name if payload.get("coverPath") else "**没有**"))
    return {"ok": True, "sent": payload, "plugin": r}


def api_bridge_install(b):
    folder = str(b.get("folder") or "")
    require_plugin_version()          # 版本监控：插件太旧就别装了
    payload = _bridge_payload(folder)
    r = bridge_call("/install", payload)
    mm.log("已直接让插件安装「%s」（jobId=%s）" % (payload["name"], r.get("jobId")))
    return {"ok": True, "sent": payload, "plugin": r}


PLUGIN_INTERNAL_NAME = "ModBridge"


def plugin_config_candidates():
    """Dalamud 把插件配置写成 pluginConfigs/<InternalName>.json，这里把可能的位置都列出来"""
    cands = []
    env = os.environ.get("XIVLAUNCHER_HOME") or os.environ.get("XIVLAUNCHER_CONFIG")
    bases = []
    if env:
        bases.append(Path(env))
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    for name in ("XIVLauncher", "XIVLauncherCN", "XIVLauncherCore"):
        bases.append(Path(roaming) / name)
    for base in bases:
        cands.append(base / "pluginConfigs" / (PLUGIN_INTERNAL_NAME + ".json"))
    # 兜底：把 pluginConfigs 下所有 json 都列上（万一插件内部名/目录变了）
    for base in bases:
        cfg_dir = base / "pluginConfigs"
        try:
            if cfg_dir.is_dir():
                for f in sorted(cfg_dir.glob("*.json")):
                    if f not in cands:
                        cands.append(f)
        except OSError:
            pass
    return cands


def api_bridge_autopair(b=None):
    """从插件自己写的配置文件里读端口 + token，自动填好并测试连接。

    找的是 Dalamud 的 pluginConfigs 目录（%APPDATA% 下的 XIVLauncher 系列）。
    """
    b = b or {}
    explicit = str(b.get("configPath") or "").strip()
    cands = ([Path(explicit)] if explicit else []) + plugin_config_candidates()

    found, used = None, None
    for c in cands:
        try:
            if not c.is_file():
                continue
            data = json.loads(c.read_text(encoding="utf-8", errors="ignore") or "{}")
            if not isinstance(data, dict):
                continue
            # 认准"有 Token 字段"的配置，避免误拿其它插件的配置
            if "Token" not in data and c.name != (PLUGIN_INTERNAL_NAME + ".json"):
                continue
            found = data
            used = c
            break
        except Exception as e:
            mm.log("读插件配置失败 %s：%s" % (c, e))

    if found is None:
        return {
            "ok": False,
            "error": "没找到插件配置（%s）。说明游戏里还没加载过 Mod Bridge 插件："
                     "先启动游戏、在 /xlplugins 里启用它（插件一加载就会把配置写出来），然后再点「自动配对」。"
                     % " 或 ".join(str(x) for x in cands[:3]),
            "tried": [str(x) for x in cands],
        }

    token = str(found.get("Token") or "").strip()
    port = int(found.get("Port") or 42100)
    if not token:
        return {"ok": False, "error": "插件配置里没有 token（%s），先在游戏里 /modbridge 打开一次窗口。" % used}

    cfg = mm.load_config()
    cfg["bridge_url"] = "http://127.0.0.1:%d" % port
    cfg["bridge_token"] = token
    save_cfg(cfg)
    mm.log("自动配对成功：读 %s，端口 %d" % (used, port))

    ping = None
    try:
        ping = bridge_call("/ping", need_token=False, timeout=6)
    except SystemExit as e:
        return {"ok": True, "paired": True, "configPath": str(used), "port": port,
                "tokenTail": token[-6:], "live": False,
                "warning": "已写入 token，但现在连不上插件（%s）。游戏没开或插件没启用时是正常的。" % e}

    pen = (ping or {}).get("penumbra") or {}
    return {
        "ok": True, "paired": True, "live": True,
        "configPath": str(used), "port": port, "tokenTail": token[-6:],
        "plugin_version": ping.get("version"),
        "version_ok": ver_ge(ping.get("version"), MIN_PLUGIN_VERSION),
        "min_plugin_version": MIN_PLUGIN_VERSION,
        "penumbra": {"available": bool(pen.get("available")), "apiMajor": pen.get("apiMajor"),
                     "apiMinor": pen.get("apiMinor"), "modCount": pen.get("modCount"),
                     "modDirectory": pen.get("modDirectory")},
        "message": "配对成功：插件已连上，Penumbra %s" % ("已就绪" if pen.get("available") else "未就绪"),
    }


def api_bridge_fix_cover(folder, dir_name=""):
    """把某一条 mod 的封面补进游戏（写进它在 Penumbra 里的那个 mod 文件夹）。
    folder 是管理器里的 mod 路径；dir_name 可选，直接指定 Penumbra 里的目录名。"""
    folder = str(folder or "")
    if not folder:
        raise SystemExit("没指定 Mod")
    payload = _bridge_payload(folder)                       # 会顺便校验 Mod 存在、找包/封面
    plug = bridge_call("/mods", timeout=25) or {}
    plist = plug.get("mods") or []
    libname = payload.get("name") or ""

    targets = []
    if dir_name:
        targets = [dir_name]
    else:
        want = _bridge_norm(libname)
        for p in plist:
            keys = _bridge_norm(p.get("name"), p.get("dir"))
            if any(_bridge_name_match(a, c) for a in want for c in keys):
                targets.append(p.get("dir"))
    if not targets:
        return {"ok": False, "error": "在游戏里没找到对应的已装 mod（名字对不上）。"
                                      "可以先把这条 mod 装进游戏，或在游戏里看看它的目录名。",
                "mod": libname, "installed": [p.get("name") for p in plist][:20]}

    results = []
    for d in targets:
        try:
            r = bridge_call("/fix-cover", {"dir": d, "coverPath": payload.get("coverPath") or "",
                                           "coverWebpPath": payload.get("coverWebpPath") or "",
                                           "coverDrawPath": payload.get("coverDrawPath") or ""}, timeout=40)
            results.append({"dir": d, "status": (r or {}).get("status") or ("written" if (r or {}).get("ok") else "error"),
                            "error": (r or {}).get("error"), "cover": (r or {}).get("relPath")})
        except SystemExit as e:
            results.append({"dir": d, "status": "error", "error": str(e)})
    written = sum(1 for x in results if x["status"] == "written")
    skipped = sum(1 for x in results if x["status"] == "skipped")
    mm.log("补封面「%s」→ %s" % (libname, results))
    return {"ok": written > 0 or skipped > 0, "mod": libname,
            "cover": Path(payload.get("coverDrawPath") or payload.get("coverPath") or "").name,
            "written": written, "skipped": skipped, "results": results}


def api_bridge_requests():
    return bridge_call("/requests", timeout=10)


def api_bridge_decide(b):
    rid = str(b.get("requestId") or "")
    if not rid:
        raise SystemExit("缺少 requestId")
    return bridge_call("/decide", {"requestId": rid, "approve": bool(b.get("approve", True))})


def _bridge_norm(*parts):
    """把 mod 名归一化，用于把管理器里的 Mod 和游戏里已装的 Mod 对上号。
    去掉 [作者]、前导序号、空格连字符下划线、大小写，尽量让两边相等。"""
    out = []
    for s in parts:
        s = re.sub(r"\[[^\]]*\]", " ", str(s or ""))
        s = re.sub(r"[\s\-_.·|,，。()（）]+", "", s)
        s = re.sub(r"^(?:hs|helio)+", "", s, flags=re.I)   # Heliosphere 的 hs- 前缀不算名字的一部分
        s = re.sub(r"^\d+", "", s)
        out.append(s.lower())
    return out


def _bridge_match_installed(plist):
    """把插件里的已装 mod 和管理器库对上号。返回 (tasks, nocover, unmatched, installed 数)"""
    lib = []
    for m in mod_index().values():
        folder = Path(m["folder"])
        lib.append({"key": _bridge_norm(m.get("name"), folder.name),
                    "name": m.get("name") or folder.name,
                    "cover": _bridge_find_cover(folder)})
    tasks, nocover, unmatched = [], [], []
    for p in plist:
        want = [k for k in _bridge_norm(p.get("name"), p.get("dir")) if k]
        hit = None
        best = 0.0
        for e in lib:
            for a in want:
                if len(a) < 4:
                    continue
                for c in e["key"]:
                    if len(c) < 4:
                        continue
                    if _bridge_name_match(a, c):
                        import difflib
                        score = difflib.SequenceMatcher(None, a, c).ratio()
                        if score > best:
                            best, hit = score, e
        if hit is None:
            unmatched.append({"dir": p.get("dir"), "name": p.get("name")})
            continue
        e = hit
        if not e["cover"]:
            nocover.append({"dir": p.get("dir"), "mod": e["name"]})
        else:
            w = cover_to_webp(e["cover"])
            d = cover_to_decodable(e["cover"])
            tasks.append({"dir": p.get("dir"), "mod": e["name"], "cover": str(e["cover"]),
                          "coverWebp": str(w) if w else "", "coverDraw": str(d) if d else ""})
    return tasks, nocover, unmatched, len(plist)


def _bridge_name_match(a, b):
    """判断两个 mod 名是不是同一条。
    先看归一化后互相包含；再兜底做一次模糊比对 ——
    因为作者/管理器那边的名字常有拼写差异（例如 Azrael vs Azreal）。"""
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 4 and long_.startswith(short):
        return True
    if len(a) >= 6 and len(b) >= 6:
        import difflib
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        if difflib.SequenceMatcher(None, short, long_).ratio() >= 0.82:
            return True
        # 名字后面挂了后缀的情况（如 Azreal (For Shiloh)、hs-…-1.0.0-EXXk）：
        # 拿短的跟长的**开头几段**逐段比，取最高分（容忍 azrael / azreal 这种少一个字母）
        for i in range(0, min(3, max(1, len(long_) - len(short) + 1))):
            window = long_[i:i + len(short)]
            if len(window) == len(short) \
                    and difflib.SequenceMatcher(None, short, window).ratio() >= 0.82:
                return True
    return False


def api_bridge_sync_covers(b=None):
    """把管理器里每条 Mod 的封面同步进游戏里已装的 Mod（写 cover.jpg + images\\_MetaImage）。
    body: {dryRun: true/false} —— 默认先预览，确认了再真同步。"""
    b = b or {}
    dry = bool(b.get("dryRun", True))
    plug = bridge_call("/mods", timeout=25)
    plist = (plug or {}).get("mods") or []
    tasks, nocover, unmatched, inst = _bridge_match_installed(plist)
    base = {"ok": True, "installed": inst, "willFix": len(tasks),
            "noCover": len(nocover), "unmatched": len(unmatched),
            "noCoverList": nocover[:30], "unmatchedList": unmatched[:30]}
    if dry:
        base.update(dryRun=True, tasks=tasks[:60])
        return base
    results = []
    for t in tasks:
        try:
            r = bridge_call("/fix-cover", {"dir": t["dir"], "coverPath": t["cover"],
                                           "coverWebpPath": t.get("coverWebp") or "",
                                           "coverDrawPath": t.get("coverDraw") or ""}, timeout=40)
            st = (r or {}).get("status") or ("written" if (r or {}).get("ok") else "error")
            results.append({"dir": t["dir"], "mod": t["mod"], "status": st,
                            "error": (r or {}).get("error")})
        except SystemExit as e:
            results.append({"dir": t["dir"], "mod": t["mod"], "status": "error", "error": str(e)})
    written = sum(1 for x in results if x["status"] == "written")
    skipped = sum(1 for x in results if x["status"] == "skipped")
    failed = [x for x in results if x["status"] == "error"]
    base.update(dryRun=False, written=written, skipped=skipped, failed=len(failed),
                results=results[:120])
    return base


def api_browser():
    cfg = cfg_now()
    exe = mm.find_browser(cfg) or ""
    port = mm.browser_port(cfg)
    running = mm.browser_running(cfg)
    page = None
    if running:
        try:
            page = mm.browser_capture(cfg)
        except Exception:
            page = None
    dl, ib = mm.resolve_dirs(cfg) if cfg.get("root") else ("", "")
    try:
        self_dl = mm.browser_download_dir(cfg)
    except Exception:
        self_dl = ""
    return {"exe": exe, "port": port, "running": running, "self_download_dir": self_dl,
            "home": getattr(mm, "BROWSER_HOME", ""),
            "hint": getattr(mm, "BROWSER_HINT", ""),
            "profile": str(mm.browser_profile(cfg)) if exe else "",
            "browsers": [{"name": n, "path": p} for n, p in mm.detect_browsers()],
            "page": page, "download_dir": dl, "inbox_dir": ib}


# -------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "ModManagerWeb/2.0"
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        pass

    # ---------- 基础 ----------
    def _cors(self):
        # 允许「你自己浏览器里的书签小工具」把页面信息送进来
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _file(self, path: Path, ctype=None):
        if not path.is_file():
            return self._json({"error": "找不到 %s" % path.name}, 404)
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    # ---------- GET ----------
    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path.startswith("/api/"):
                routes = {
                    "/api/state": api_state, "/api/mods": api_mods,
                    "/api/categories": api_categories, "/api/dupes": api_dupes,
                    "/api/install": api_install, "/api/backups": api_backups,
                    "/api/pending": api_pending, "/api/check": api_check,
                    "/api/settings": api_settings,
                }
                if u.path in routes:
                    return self._json(routes[u.path]())
                if u.path == "/api/job":
                    cur = JOBS["cur"]
                    return self._json({"state": "idle"} if cur is None else cur.snap())
                if u.path == "/api/thumb":
                    return self.api_thumb(q)
                if u.path == "/api/raw":
                    return self.api_raw(q)
                if u.path == "/api/log":
                    return self._json({"lines": tail_log(int((q.get("n") or ["80"])[0]))})
                if u.path == "/api/inspect":
                    return self._json(api_inspect(q))
                if u.path == "/api/browser":
                    return self._json(api_browser())
                if u.path == "/api/browser/login-state":
                    cfg = cfg_now()
                    s = mm.browser_login_state(cfg)
                    s["user_data"] = str(mm.user_data_dir_of(mm.find_browser(cfg)) or "")
                    s["profile"] = str(mm.browser_profile(cfg))
                    return self._json({"ok": True, "login": s})
                if u.path == "/api/bridge":
                    return self._json(api_bridge())
                if u.path == "/api/tags":
                    return self._json(api_tags())
                if u.path == "/api/affects":
                    return self._json(api_affects())
                if u.path == "/api/bridge/requests":
                    return self._json(api_bridge_requests())
                if u.path == "/api/images":
                    return self._json(api_images(q))
                if u.path == "/api/img":
                    return self.api_img(q)
                if u.path == "/api/fetch/cover":
                    return self.api_fetch_cover(q)
                if u.path == "/api/inbox/page":
                    return self._json(api_inbox_page_get())
                if u.path == "/api/rawimg":
                    return self.api_rawimg(q)
                return self._json({"error": "没有这个接口：%s" % u.path}, 404)

            if u.path == "/favicon.ico":
                fav = WEB_DIR / "favicon.ico"
                return self._file(fav) if fav.is_file() else self._send(204, b"")

            rel = urllib.parse.unquote(u.path).lstrip("/")
            if rel:
                try:
                    cand = (WEB_DIR / rel).resolve()
                    base = WEB_DIR.resolve()
                    if cand.is_file() and (cand == base or base in cand.parents):
                        return self._file(cand)
                except OSError:
                    pass
            return self._file(WEB_DIR / "index.html", "text/html; charset=utf-8")
        except BrokenPipeError:
            pass
        except SystemExit as e:              # mod_manager 用它表达可读的错误
            self._json({"error": str(e)}, 400)
        except Exception as e:
            mm.log(traceback.format_exc())
            self._json({"error": "%s" % e}, 500)

    # ---------- POST ----------
    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        ctype = self.headers.get("Content-Type") or ""
        body = {}
        if "multipart/form-data" in ctype:          # 「手动上传新文件」用浏览器选文件
            try:
                fields, files = parse_multipart(self.rfile.read(n) if n else b"", ctype)
                body = dict(fields)
                if files:
                    body["_upload"] = save_upload(files)
            except Exception as e:
                body = {"_upload_error": str(e)}
        else:
            try:
                raw = self.rfile.read(n).decode("utf-8") if n else "{}"
                body = json.loads(raw or "{}")
            except Exception:
                body = {}
        try:
            if u.path == "/api/job":
                kind = str(body.get("kind") or "")
                job, err = start_job(kind, body.get("params") or {})
                if job is None:
                    return self._json({"error": err}, 409)
                return self._json({"ok": True, "kind": kind,
                                   "title": JOB_TITLES.get(kind, kind)})
            if u.path == "/api/job/cancel":
                cur = JOBS["cur"]
                if cur is not None and cur.state == "running":
                    cur.cancel()
                    return self._json({"ok": True})
                return self._json({"ok": False, "error": "没有在跑的任务"})
            if u.path == "/api/open":
                return self.open_something(body)
            if u.path == "/api/mod/add":
                return self.mod_add(body)
            if u.path == "/api/mod/edit":
                return self.mod_edit(body)
            if u.path == "/api/mod/batch-edit":
                return self.mod_batch_edit(body)
            if u.path == "/api/mod/delete":
                return self.mod_delete(body)
            if u.path == "/api/mod/add-image":
                return self.mod_add_image(body)
            if u.path == "/api/mod/delete-image":
                return self.mod_delete_image(body)
            if u.path == "/api/mod/set-preview":
                return self.mod_set_preview(body)
            if u.path == "/api/mod/fix-cover":
                return self.mod_fix_cover(body)
            if u.path == "/api/mod/replace":
                return self.mod_replace(body)
            if u.path == "/api/mod/tags":
                return self._json(api_mod_set_tags(body))
            if u.path == "/api/mod/affects":
                return self._json(api_mod_set_affects(body))
            if u.path == "/api/mod/tags/add":
                return self._json(api_mod_add_tags(body))
            if u.path == "/api/mod/tags/remove":
                return self._json(api_mod_remove_tags(body))
            if u.path == "/api/category":
                return self.category_op(body)
            if u.path == "/api/renumber/preview":
                cfg = cfg_now()
                plan = mm.renumber_plan(cfg, body.get("category") or "",
                                        body.get("subcat") or "", int(body.get("start") or 1))
                return self._json({"plan": [
                    {"folder": m["folder"], "rel": m.get("rel") or m["folder"],
                     "name": m["name"], "old": m["seq"], "new": n2}
                    for m, n2 in plan]})
            if u.path == "/api/settings":
                return self.save_settings(body)
            if u.path == "/api/inbox/page":
                return self._json(api_inbox_page_put(body))
            if u.path == "/api/fetch/parse":
                return self._json(api_fetch_parse(body))
            if u.path == "/api/bridge/propose":
                return self._json(api_bridge_propose(body))
            if u.path == "/api/bridge/install":
                return self._json(api_bridge_install(body))
            if u.path == "/api/bridge/decide":
                return self._json(api_bridge_decide(body))
            if u.path == "/api/bridge/autopair":
                return self._json(api_bridge_autopair(body))
            if u.path == "/api/bridge/sync-covers":
                return self._json(api_bridge_sync_covers(body))
            if u.path == "/api/bridge/fix-cover":
                return self._json(api_bridge_fix_cover(body.get("folder"), body.get("dir") or body.get("dirName") or ""))
            if u.path == "/api/push/downloaded":
                job, err = start_job("importfile", body or {})
                if job is None:
                    return self._json({"error": err}, 409)
                return self._json({"ok": True, "kind": "importfile",
                                   "title": JOB_TITLES.get("importfile", "入库")})
            if u.path == "/api/browser/sync-login":
                cfg = cfg_now()
                r = mm.sync_login_from_user_browser(cfg)      # SystemExit 会被上层转成 400
                try:
                    mm.launch_browser(cfg, mm.BROWSER_HOME)
                except Exception:
                    pass
                try:
                    st = mm.browser_login_state(cfg)
                except Exception as e:
                    st = {"error": str(e)[:80]}
                return self._json({"ok": True, "synced": r, "login": st})
            if u.path == "/api/browser/open":
                return self.browser_open(body)
            if u.path == "/api/browser/close":
                return self.browser_close(body)
            if u.path == "/api/browser/capture":
                cfg = cfg_now()
                try:
                    return self._json({"ok": True, "page": mm.browser_capture(cfg)})
                except Exception as e:
                    return self._json({"error": "读不到浏览器页面：%s" % e}, 400)
            if u.path == "/api/browser/grab-cover":
                return self.browser_grab_cover(body)
            if u.path == "/api/quit":
                cur = JOBS["cur"]
                if cur is not None and cur.state == "running":
                    cur.cancel()

                    def _wait_and_die():
                        for _ in range(40):
                            if cur.state != "running":
                                break
                            time.sleep(0.1)
                        mm.clean_stale_parts(mm.load_config(), older_than=0)
                        os._exit(0)

                    self._json({"ok": True, "bye": "已取消在跑的任务，服务退出。页面可以关掉了。"})
                    threading.Thread(target=_wait_and_die, daemon=True).start()
                    return
                self._json({"ok": True, "bye": "服务已退出，页面可以关掉了。"})
                threading.Timer(0.4, lambda: os._exit(0)).start()
                return
            return self._json({"error": "没有这个接口：%s" % u.path}, 404)
        except BrokenPipeError:
            pass
        except SystemExit as e:              # mod_manager 用它表达可读的错误
            self._json({"error": str(e)}, 400)
        except Exception as e:
            mm.log(traceback.format_exc())
            self._json({"error": "%s" % e}, 500)

    # ---------- 写操作 ----------
    def mod_add(self, b):
        cfg = cfg_now()
        src = str(b.get("src") or "").strip()
        if not src or not Path(src).exists():
            return self._json({"error": "找不到要导入的文件夹/压缩包：%s" % src}, 400)
        cat = str(b.get("category") or "").strip()
        if not cat:
            return self._json({"error": "请选择分类"}, 400)
        t = mm.import_mod(cfg, src, cat, str(b.get("zone") or "SFW"),
                          str(b.get("subdir") or ""), b.get("author") or None,
                          b.get("name") or None,
                          int(b["seq"]) if b.get("seq") else None,
                          mm.norm_addr(b.get("addr") or ""), bool(b.get("move")))
        mm.cmd_scan(cfg, quiet=True)
        got_aff = ""
        if b.get("affects"):
            got_aff = apply_meta_after_import(cfg, t, affects=b.get("affects")).get("affects") or ""
        mod_index(force=True)
        return self._json({"ok": True, "target": str(t),
                           "rel": safe_rel(t, cfg["root"]), "affects": got_aff})

    def mod_edit(self, b):
        cfg = cfg_now()
        folder = str(b.get("folder") or "")
        m = one_mod(cfg, folder)
        if not m and not inside_root(folder, cfg.get("root") or ""):
            return self._json({"error": "找不到这条 Mod，或路径不在 Mod 目录里"}, 400)
        t = mm.rename_mod(cfg, folder, b.get("category") or None, b.get("zone") or None,
                          b.get("subdir") if b.get("subdir") is not None else None,
                          b.get("author") if b.get("author") is not None else None,
                          b.get("name") if b.get("name") is not None else None,
                          int(b["seq"]) if b.get("seq") not in (None, "") else None,
                          b.get("addr") if b.get("addr") is not None else None)
        mm.cmd_scan(cfg, quiet=True)
        # 「影响/替换」不在文件夹名里，改名/移动之后按新路径单独写一次
        got_aff = ""
        if b.get("affects") is not None:
            got_aff = apply_meta_after_import(cfg, t, affects=b.get("affects")).get("affects") or ""
        mod_index(force=True)
        return self._json({"ok": True, "target": str(t), "rel": safe_rel(t, cfg["root"]),
                           "affects": got_aff})

    def mod_batch_edit(self, b):
        """批量改分类/类型/子分类（一次扫描，不做 N 次）"""
        cfg = cfg_now()
        folders = [str(x) for x in (b.get("folders") or [])]
        f = b.get("fields") or {}
        if not folders:
            return self._json({"error": "没有选中的 Mod"}, 400)
        root = cfg.get("root") or ""
        done, bad = [], []
        for folder in folders:
            if not inside_root(folder, root) or not Path(folder).exists():
                bad.append("%s（路径不合法或不存在）" % folder)
                continue
            try:
                t = mm.rename_mod(
                    cfg, folder,
                    f.get("category") or None,
                    f.get("zone") or None,
                    f.get("subcat") if f.get("subcat") is not None else None,
                    None, None, None, None)
                done.append(safe_rel(t, root))
            except Exception as e:
                bad.append("%s：%s" % (Path(folder).name, e))
        if done:
            mm.cmd_scan(cfg, quiet=True)
            # 「影响/替换」：文件夹改名后路径变了，按重扫后的新记录来写
            if f.get("affects") is not None:
                wanted = mm.norm_affects(f.get("affects"))
                st = mm.Store()
                hit = 0
                for m in st.all():
                    if (m.get("rel") or "") in set(done) or Path(m["folder"]).name in \
                            {Path(d).name for d in done}:
                        st.cx.execute("UPDATE mods SET affects=? WHERE folder=?", (wanted, m["folder"]))
                        hit += 1
                st.cx.commit()
                st.cx.close()
                mm.log("批量设置影响/替换（%d 条）：%s" % (hit, wanted or "（清空）"))
            mod_index(force=True)
        return self._json({"ok": done, "failed": bad})

    def mod_delete(self, b):
        cfg = cfg_now()
        folder = str(b.get("folder") or "")
        if not inside_root(folder, cfg.get("root") or ""):
            return self._json({"error": "路径不在 Mod 目录里，拒绝删除"}, 403)
        if not Path(folder).exists():
            return self._json({"error": "文件夹不存在"}, 400)
        how = mm.delete_mod(folder, to_recycle=not bool(b.get("permanent")))
        mm.cmd_scan(cfg, quiet=True)
        mod_index(force=True)
        return self._json({"ok": True, "how": how})

    def mod_replace(self, b):
        """手动上传/指定一个新文件，替换掉这条 Mod 的旧文件（保留 地址.txt、预览图、编号）"""
        cfg = cfg_now()
        if b.get("_upload_error"):
            return self._json({"error": "上传失败：%s" % b["_upload_error"]}, 400)
        folder = str(b.get("folder") or "")
        src = str(b.get("_upload") or b.get("src") or "").strip().strip('"')
        mode = str(b.get("mode") or "same_name")
        if not folder or not inside_root(folder, cfg.get("root") or ""):
            return self._json({"error": "先选一条 Mod（要在 Mod 目录里）"}, 400)
        if not Path(folder).is_dir():
            return self._json({"error": "Mod 文件夹不存在：%s" % folder}, 400)
        if not src:
            return self._json({"error": "还没给新文件：可以在弹窗里直接选文件，"
                                        "或填本地路径，或从「待导入」里挑一个"}, 400)
        f = Path(src)
        if not f.exists():
            return self._json({"error": "新文件不存在：%s" % src}, 400)
        try:
            if f.is_dir() and f.resolve() == Path(folder).resolve():
                return self._json({"error": "新文件不能就是这条 Mod 自己的文件夹"}, 400)
        except OSError:
            pass
        try:
            rep = mm.replace_mod_payload(cfg, folder, f, mode=mode)
        except SystemExit as e:
            return self._json({"error": str(e)}, 400)
        mm.cmd_scan(cfg, quiet=True)
        mod_index(force=True)
        return self._json({"ok": True, **rep})

    def mod_fix_cover(self, b):
        """补预览图：已有的直接用；没有就按「推来的封面 → 内置浏览器」去抓，并如实回报结果"""
        cfg = cfg_now()
        folder = str(b.get("folder") or "")
        m = one_mod(cfg, folder)
        if not m:
            return self._json({"error": "找不到这条 Mod"}, 400)
        fd = Path(folder)
        tried = []

        found, how = mm.find_image(fd, fd.name, m.get("author") or "", m.get("name") or "")
        if found:
            return self._json({"ok": True, "img": str(found), "how": how,
                               "name": Path(found).name, "already": True})

        addr = m.get("addr") or ""
        modid = _modid_of(addr)
        dest = fd / (fd.name + ".jpg")
        local = str(b.get("local_cover") or "")

        # 1) 本机给的封面图
        if local and Path(local).is_file():
            try:
                shutil.copy2(local, dest)
                mm.cmd_scan(cfg, quiet=True)
                mod_index(force=True)
                return self._json({"ok": True, "img": str(dest), "how": "本机给的封面",
                                   "name": dest.name})
            except Exception as e:
                tried.append("本机封面：%s" % e)

        # 2) 用你自己浏览器推来的封面（不用开内置浏览器）
        pg = LAST_PAGE.get("data") or {}
        cover = str(pg.get("cover") or "")
        if cover:
            pm = _modid_of(pg.get("url") or "") or str(pg.get("modid") or "")
            if modid and pm and pm != modid:
                tried.append("浏览器推来的是另一个 Mod（modid %s），跳过" % pm)
            else:
                ok, why = _save_url(cfg, cover, dest, use_browser=mm.browser_running(cfg))
                if ok:
                    mm.cmd_scan(cfg, quiet=True)
                    mod_index(force=True)
                    return self._json({"ok": True, "img": str(dest), "how": "浏览器推来的封面（%s）" % why,
                                       "name": dest.name})

        if not modid:
            return self._json({"ok": True, "img": "", "tried": tried,
                               "reason": "这条 Mod 没有可用的 Mod 地址（地址.txt 里没有 /modid/ 编号），"
                                         "只能手动「添加图片…」或把封面拖进来"})

        # 3) 内置浏览器：没开就自动开
        url = addr or ("https://www.xivmodarchive.com/modid/%s" % modid)
        if not mm.browser_running(cfg):
            try:
                mm.log("补预览图：自动打开内置浏览器 %s" % url)
                mm.launch_browser(cfg, url)
            except SystemExit as e:
                return self._json({"ok": True, "img": "", "tried": tried,
                                   "reason": "内置浏览器没在跑，自动打开也失败：%s" % e})
            except Exception as e:
                return self._json({"ok": True, "img": "", "tried": tried,
                                   "reason": "自动打开内置浏览器失败：%s" % e})
        try:
            mm.browser_wait_ready(cfg, timeout=30)
            cur = mm.browser_eval(cfg, "location.href") or ""
            if modid not in cur:
                mm.browser_eval(cfg, "location.href=%s" % json.dumps(url))
                mm.browser_wait_ready(cfg, timeout=30)
            info = mm.browser_capture(cfg)
            gc = info.get("cover") or ""
            if gc:
                ok, why = _save_url(cfg, gc, dest, use_browser=True)
                if ok:
                    mm.cmd_scan(cfg, quiet=True)
                    mod_index(force=True)
                    return self._json({"ok": True, "img": str(dest),
                                       "how": "内置浏览器抓的封面（%s）" % why, "name": dest.name})
                tried.append("抓封面地址失败：%s" % why)
            else:
                tried.append("页面标题：%s（%s）" % ((info.get("title") or "?")[:40],
                                                 "疑似被反爬挡住" if info.get("challenge") else "页面上没读到封面"))
        except SystemExit as e:
            tried.append(str(e))
        except Exception as e:
            tried.append("读页面失败：%s" % e)

        return self._json({"ok": True, "img": "", "tried": tried,
                           "reason": "没抓到封面。可以：先在「下载工作台」用内置浏览器打开这条 Mod 的页面过一下验证，"
                                     "或者直接「添加图片…」把封面拖进来"})

    def category_op(self, b):
        cfg = cfg_now()
        root = Path(cfg["root"] or "")
        if not root.is_dir():
            return self._json({"error": "Mod 根目录不存在"}, 400)
        act = str(b.get("action") or "")
        order = list(cfg.get("category_order") or [])

        def add_order(name, before=None):
            if name in order:
                order.remove(name)
            if before and before in order:
                order.insert(order.index(before), name)
            else:
                order.append(name)
            cfg["category_order"] = order
            save_cfg(cfg)

        if act == "create":
            name = str(b.get("name") or "").strip()
            if not name or "/" in name or "\\" in name:
                return self._json({"error": "分类名不合法"}, 400)
            if (root / name).exists():
                return self._json({"error": "这个分类已经存在了"}, 400)
            (root / name / "SFW").mkdir(parents=True, exist_ok=True)
            (root / name / "NSFW").mkdir(parents=True, exist_ok=True)
            add_order(name)
            return self._json({"ok": True, "name": name})

        if act == "rename":
            old = str(b.get("name") or "").strip()
            new = str(b.get("new_name") or "").strip()
            if not old or not new or "/" in new or "\\" in new:
                return self._json({"error": "名字不合法"}, 400)
            if not (root / old).is_dir():
                return self._json({"error": "原分类不存在"}, 400)
            if (root / new).exists():
                return self._json({"error": "新名字已经被占了"}, 400)
            os.rename(str(root / old), str(root / new))
            try:                                     # 整目录改名：这一批 Mod 的标签跟着走
                st = mm.Store()
                moved = st.remap_folder_prefix(str(root / old), str(root / new))
                st.cx.close()
                if moved:
                    mm.log("分类改名：带过 %d 个标签" % moved)
            except Exception as e:
                mm.log("标签迁移失败（分类改名）：%s" % e)
            if old in order:
                order[order.index(old)] = new
                cfg["category_order"] = order
                save_cfg(cfg)
            mm.cmd_scan(cfg, quiet=True)
            mod_index(force=True)
            return self._json({"ok": True, "name": new})

        if act == "delete":
            name = str(b.get("name") or "").strip()
            d = root / name
            if not d.is_dir():
                return self._json({"error": "分类不存在"}, 400)
            left = [p for p in d.rglob("*") if p.is_file()]
            if left and not b.get("force"):
                return self._json({"error": "这个分类里还有 %d 个文件，"
                                            "确认要一起删吗？" % len(left)}, 409)
            if not mm.send_to_recycle_bin(d):
                shutil.rmtree(d, ignore_errors=True)
            if name in order:
                order.remove(name)
                cfg["category_order"] = order
                save_cfg(cfg)
            mm.cmd_scan(cfg, quiet=True)
            mod_index(force=True)
            return self._json({"ok": True})

        if act == "order":
            names = [str(x) for x in (b.get("order") or []) if str(x).strip()]
            cfg["category_order"] = names
            save_cfg(cfg)
            return self._json({"ok": True, "order": names})

        if act == "subdir":
            cat = str(b.get("category") or "").strip()
            zone = str(b.get("zone") or "").strip().upper()
            name = str(b.get("name") or "").strip()
            if not cat or not name or "/" in name or "\\" in name:
                return self._json({"error": "名字不合法"}, 400)
            base = root / cat / zone if zone in ("SFW", "NSFW") else root / cat
            (base / name).mkdir(parents=True, exist_ok=True)
            return self._json({"ok": True, "path": str(base / name)})

        return self._json({"error": "不认识的操作：%s" % act}, 400)

    def save_settings(self, b):
        cfg = mm.load_config()
        if ROOT_OVERRIDE and "root" in b:
            return self._json({"error": "当前是临时根目录模式（--root），不能改 Mod 根目录"}, 400)
        allow = ("root", "excel", "download_dir", "inbox_dir", "install_dir", "backup_dir",
                 "browser_path", "browser_dir", "browser_port", "thumb_width",
                 "embed_images", "autofilter", "bridge_url", "bridge_token",
                 "auto_open_browser")
        changed = {}
        for k in allow:
            if k in b:
                changed[k] = b[k]
        if "thumb_width" in changed:
            try:
                changed["thumb_width"] = max(120, min(2400, int(changed["thumb_width"])))
            except Exception:
                changed.pop("thumb_width")
        if "browser_port" in changed:
            try:
                changed["browser_port"] = int(changed["browser_port"])
            except Exception:
                changed.pop("browser_port")
        for k in ("embed_images", "autofilter"):
            if k in changed:
                changed[k] = bool(changed[k])
        for k in ("root", "excel"):
            if k in changed and changed[k]:
                p = Path(str(changed[k]))
                if k == "root" and not p.is_dir():
                    return self._json({"error": "Mod 根目录不存在：%s" % p}, 400)
        cfg.update(changed)
        if not cfg.get("excel") and cfg.get("root"):
            cfg["excel"] = str(Path(cfg["root"]).parent / "Mod信息汇总表.xlsx")
        save_cfg(cfg)
        mod_index(force=True)
        return self._json({"ok": True, "changed": sorted(changed)})

    def _img_path(self, q):
        cfg = cfg_now()
        p = (q.get("p") or [""])[0]
        if not p or not Path(p).is_file():
            return None, "图片不存在"
        if not inside_root(p, cfg.get("root") or ""):
            return None, "路径不在 Mod 目录里"
        if Path(p).suffix.lower() not in mm.IMG_EXT:
            return None, "不是图片文件"
        return Path(p), ""

    def api_img(self, q):
        """任意图片的缩略图（带缓存）"""
        path, err = self._img_path(q)
        if err:
            return self._json({"error": err}, 403 if "不在" in err else 404)
        try:
            width = int((q.get("w") or ["200"])[0])
        except ValueError:
            width = 200
        width = max(48, min(1600, width))
        h = file_hash(path)
        src = mm.ensure_thumb(str(path), width, h, THUMB_CACHE)
        etag = '"%s-%d"' % (h[:16], width)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        ctype = mimetypes.guess_type(src)[0] or "image/jpeg"
        self._send(200, Path(src).read_bytes(), ctype,
                   {"Cache-Control": "public, max-age=604800", "ETag": etag})

    def api_rawimg(self, q):
        path, err = self._img_path(q)
        if err:
            return self._json({"error": err}, 403 if "不在" in err else 404)
        self._file(path)

    def mod_add_image(self, b):
        """给某条 Mod 追加图片：本机上传 / 网址 / 内置浏览器当前页面的全部图片"""
        cfg = cfg_now()
        m = one_mod(cfg, b.get("folder"))
        if not m:
            return self._json({"error": "找不到这条 Mod"}, 400)
        fdir = Path(m["folder"])
        fdir.mkdir(parents=True, exist_ok=True)
        saved, failed, notes = [], [], []

        def dest_for(ext, hint=""):
            ext = ext if ext in mm.IMG_EXT else ".jpg"
            for i in range(1, 999):
                cand = fdir / ("%s_%d%s" % (fdir.name, i, ext))
                if not cand.exists():
                    return cand
            return fdir / ("%s_extra%s" % (fdir.name, ext))

        # 2.1 本机上传（base64）
        for f in (b.get("files") or []):
            try:
                name = str(f.get("name") or "image.jpg")
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ".jpg"
                raw = base64.b64decode(f.get("data") or "")
                if not raw:
                    raise ValueError("空文件")
                dst = dest_for(ext)
                dst.write_bytes(raw)
                saved.append(dst.name)
            except Exception as e:
                failed.append("%s：%s" % (f.get("name"), e))

        # 2.2 网址列表
        urls = []
        if b.get("url"):
            urls.append(str(b["url"]).strip())
        if b.get("page"):
            try:
                urls += page_images(cfg)
            except Exception as e:
                failed.append("读内置浏览器页面失败：%s" % e)
        if b.get("use_inbox"):
            pg = LAST_PAGE.get("data") or {}
            got = [str(x) for x in (pg.get("imgs") or []) if str(x).lower().startswith("http")]
            if pg.get("cover"):
                got.append(str(pg["cover"]))
            if got:
                mm.log("用浏览器推来的信息加图：%d 张（%s）"
                       % (len(got), pg.get("name") or pg.get("url") or ""))
                if pg.get("old_bookmarklet"):
                    notes.append("你推来的信息是旧版书签小工具发的（只有封面，没有画廊图）；"
                                 "想一次把画廊都拿过来，请重新拖一次书签小工具")
            else:
                # 旧版书签小工具 + 没读到图 → 借内置浏览器直接去那条页面抓画廊
                pgurl = str(pg.get("url") or "")
                if pgurl.lower().startswith("http") and not cfg.get("auto_open_browser"):
                    notes.append("推来的信息里没有图片地址（书签小工具是旧版）；"
                                 "默认不开内置浏览器，想让它现抓画廊请在「设置」里"
                                 "勾选「需要时自动打开内置浏览器」，或者重新拖一次书签小工具")
                elif pgurl.lower().startswith("http"):
                    notes.append("推来的信息里没有图片地址（书签小工具是旧版），已改用内置浏览器"
                                 "打开那条页面现抓画廊")
                    try:
                        if not mm.browser_running(cfg):
                            mm.log("按推来的地址打开内置浏览器：%s" % pgurl)
                            mm.launch_browser(cfg, pgurl)
                        mm.browser_wait_ready(cfg, timeout=30)
                        cur = mm.browser_eval(cfg, "location.href") or ""
                        want = str(pg.get("modid") or "")
                        if want and want not in cur:
                            mm.browser_eval(cfg, "location.href=%s" % json.dumps(pgurl))
                            mm.browser_wait_ready(cfg, timeout=30)
                        got = page_images(cfg)
                        mm.log("内置浏览器现抓画廊：%d 张" % len(got))
                    except SystemExit as e:
                        failed.append("内置浏览器打不开：%s" % e)
                    except Exception as e:
                        failed.append("用内置浏览器抓画廊失败：%s" % e)
                else:
                    failed.append("你浏览器推来的那条信息里没有图片地址，也没有页面网址——"
                                  "请在 Mod 页面重新拖一次书签小工具")
            for u2 in got:
                if u2 not in urls:
                    urls.append(u2)
        for u in urls:
            if not u.lower().startswith("http"):
                failed.append("%s（不是网址）" % u[:40])
                continue
            ext = "." + (u.rsplit(".", 1)[-1].split("?")[0].lower() if "." in u else "jpg")
            dst = dest_for(ext)
            try:                                   # 先直接下（大多数公开图片都行，不需要浏览器）
                req = urllib.request.Request(
                    u, headers={"User-Agent": BROWSER_UA,
                                "Referer": "https://www.xivmodarchive.com/"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
                if not data:
                    raise ValueError("空响应")
                dst.write_bytes(data)
                saved.append(dst.name)
                continue
            except Exception:
                pass
            try:                                   # 兜底：借浏览器 cookie（需要内置浏览器在跑）
                mm.browser_fetch(cfg, u, dst)
                saved.append(dst.name)
            except (SystemExit, Exception) as e:
                failed.append("%s：%s" % (u[-36:], e))

        if saved:
            mm.cmd_scan(cfg, quiet=True)
            mod_index(force=True)
        return self._json({"ok": saved, "failed": failed, "notes": notes,
                           "count": len(saved)})

    def mod_delete_image(self, b):
        """删掉某条 Mod 的一张图（进回收站）。只允许删这条 Mod 自己的图。"""
        cfg = cfg_now()
        m = one_mod(cfg, b.get("folder"))
        if not m:
            return self._json({"error": "找不到这条 Mod"}, 400)
        p = Path(str(b.get("path") or ""))
        if not inside_root(p, cfg.get("root") or ""):
            return self._json({"error": "图片不在 Mod 目录里"}, 403)
        if not p.is_file():
            return self._json({"error": "图片不存在（可能已经被删了）"}, 400)
        if p.suffix.lower() not in mm.IMG_EXT:
            return self._json({"error": "不是图片文件"}, 400)
        fdir = Path(m["folder"])
        in_folder = fdir == p.parent or fdir in p.parents
        is_sibling = (p.parent == fdir.parent and p.stem == fdir.name)
        if not (in_folder or is_sibling):
            return self._json({"error": "只能删这条 Mod 自己的图片"}, 403)
        name = p.name
        how = "已移入回收站" if mm.send_to_recycle_bin(str(p)) else ""
        if not how:
            try:
                p.unlink()
                how = "已删除"
            except OSError as e:
                return self._json({"error": "删不掉：%s" % e}, 500)
        mm.cmd_scan(cfg, quiet=True)
        mod_index(force=True)
        return self._json({"ok": True, "how": how, "name": name})

    def mod_set_preview(self, b):
        """把某张图存成这条 Mod 的预览图（按工具的命名约定：同级同名图片）"""
        cfg = cfg_now()
        m = one_mod(cfg, b.get("folder"))
        if not m:
            return self._json({"error": "找不到这条 Mod"}, 400)
        src = Path(str(b.get("path") or ""))
        if not inside_root(src, cfg.get("root") or ""):
            return self._json({"error": "图片不在 Mod 目录里"}, 403)
        if not src.is_file() or src.suffix.lower() not in mm.IMG_EXT:
            return self._json({"error": "图片不存在或不是图片"}, 400)
        fdir = Path(m["folder"])
        dest = fdir.parent / (fdir.name + src.suffix.lower())
        try:
            if src.resolve() != dest.resolve():
                for ext in mm.IMG_EXT:          # 旧的其他后缀同名图清掉，避免两张并存
                    old = fdir.parent / (fdir.name + ext)
                    if old.is_file() and old.resolve() != dest.resolve():
                        try:
                            old.unlink()
                        except OSError:
                            pass
                shutil.copy2(str(src), str(dest))
        except OSError as e:
            return self._json({"error": "写入失败：%s" % e}, 500)
        mm.cmd_scan(cfg, quiet=True)
        mod_index(force=True)
        return self._json({"ok": True, "saved": str(dest), "name": dest.name})

    def api_fetch_cover(self, q):
        """封面代理：先直连（带 UA/Referer），直连不行再借内置浏览器的 cookie。
        以前只走浏览器，浏览器没开就直接失败，界面就是个白框。"""
        cfg = cfg_now()
        u = (q.get("u") or [""])[0]
        if not u.lower().startswith("http"):
            return self._json({"error": "封面地址不对"}, 400)
        try:
            width = int((q.get("w") or ["400"])[0])
        except ValueError:
            width = 400
        key = hashlib.md5(u.encode("utf-8")).hexdigest()[:16]
        cache = APP_DIR / ".cover_cache"
        cache.mkdir(parents=True, exist_ok=True)
        raw = cache / ("fetch_%s.bin" % key)
        if not raw.is_file() or raw.stat().st_size < 1024:
            running = mm.browser_running(cfg)
            ok, why = _save_url(cfg, u, raw, use_browser=running)
            if not ok:
                return self._json({"error": "封面抓不到：直连失败（%s）；内置浏览器%s。"
                                            "点「打开内置浏览器」打开这条 Mod 页面过一下验证后再重试。"
                                            % (why, "在跑但也没抓到" if running else "没在运行")}, 400)
        try:
            src = mm.ensure_thumb(str(raw), max(120, min(1200, width)),
                                  key, THUMB_CACHE)
        except Exception:
            src = str(raw)
        ctype = mimetypes.guess_type(src)[0] or "image/jpeg"
        self._send(200, Path(src).read_bytes(), ctype,
                   {"Cache-Control": "public, max-age=86400", "ETag": '"%s-%d"' % (key, width)})

    def browser_open(self, b):
        cfg = cfg_now()
        url = (b.get("url") or "").strip() or getattr(mm, "BROWSER_HOME", "")
        try:
            port = mm.launch_browser(cfg, url)
        except SystemExit as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:
            return self._json({"error": "启动浏览器失败：%s" % e}, 500)
        return self._json({"ok": True, "port": port, "url": url,
                           "running": mm.browser_running(cfg)})

    def browser_close(self, b):
        cfg = cfg_now()
        if not mm.browser_running(cfg):
            return self._json({"ok": True, "running": False, "note": "本来就没在跑"})
        try:
            mm._cdp_get(cfg, page_only=False).call("Browser.close")
        except Exception:
            pass
        time.sleep(0.8)
        if mm.browser_running(cfg):               # 兜底：直接结束监听端口的进程
            pid = pid_on_port(mm.browser_port(cfg))
            if pid:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True)
        time.sleep(0.5)
        return self._json({"ok": True, "running": mm.browser_running(cfg)})

    def browser_grab_cover(self, b):
        cfg = cfg_now()
        m = one_mod(cfg, b.get("folder"))
        if not m:
            return self._json({"error": "先在「Mod 列表」里选一条"}, 400)
        try:
            cap = mm.browser_capture(cfg)
        except Exception as e:
            return self._json({"error": "读不到浏览器页面（先点「打开内置浏览器」）：%s" % e}, 400)
        img = (cap.get("img") or "").strip()
        if not img:
            return self._json({"error": "当前页面上没找到封面图，先把这条 Mod 的页面打开"}, 400)
        ext = "." + (img.rsplit(".", 1)[-1].split("?")[0].lower() if "." in img else "jpg")
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            ext = ".jpg"
        folder = Path(m["folder"])
        dest = folder.parent / (folder.name + ext)
        try:
            n = mm.browser_fetch(cfg, img, dest)
        except Exception as e:
            return self._json({"error": "抓封面失败：%s" % e}, 400)
        mm.cmd_scan(cfg, quiet=True)
        mod_index(force=True)
        return self._json({"ok": True, "saved": str(dest), "bytes": n})

    # ---------- 图片 / 打开 ----------
    def api_thumb(self, q):
        folder = (q.get("f") or [""])[0]
        try:
            width = int((q.get("w") or ["900"])[0])
        except ValueError:
            width = 900
        cfg = cfg_now()
        if not inside_root(folder, cfg.get("root") or ""):
            return self._json({"error": "路径不在 Mod 目录里"}, 403)
        m = mod_index().get(folder)
        if not m or not m.get("img") or not Path(m["img"]).is_file():
            return self._json({"error": "没有预览图"}, 404)
        width = max(48, min(1600, width))
        src = mm.ensure_thumb(m["img"], width, m.get("img_hash") or "", THUMB_CACHE)
        etag = '"%s-%d"' % ((m.get("img_hash") or "x")[:16], width)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        ctype = mimetypes.guess_type(src)[0] or "image/jpeg"
        self._send(200, Path(src).read_bytes(), ctype,
                   {"Cache-Control": "public, max-age=604800", "ETag": etag})

    def api_raw(self, q):
        folder = (q.get("f") or [""])[0]
        cfg = cfg_now()
        if not inside_root(folder, cfg.get("root") or ""):
            return self._json({"error": "路径不在 Mod 目录里"}, 403)
        m = mod_index().get(folder)
        if not m or not m.get("img") or not Path(m["img"]).is_file():
            return self._json({"error": "没有预览图"}, 404)
        self._file(Path(m["img"]))

    def open_something(self, body):
        cfg = cfg_now()
        kind = str(body.get("kind") or "")
        folder = str(body.get("f") or "")
        if kind == "folder":
            if not inside_root(folder, cfg.get("root") or ""):
                return self._json({"error": "路径不在 Mod 目录里"}, 403)
            mm.open_path(Path(folder))
            return self._json({"ok": True})
        if kind == "addr":
            m = mod_index().get(folder)
            if not m or not m.get("addr"):
                return self._json({"error": "这条没有 Mod 地址"}, 400)
            mm.open_path(m["addr"])
            return self._json({"ok": True})
        dl, ib = mm.resolve_dirs(cfg) if cfg.get("root") else ("", "")
        table = {"root": cfg.get("root"), "excel": cfg.get("excel"),
                 "backup": str(mm.resolve_backup_dir(cfg)),
                 "downloads": dl, "inbox": ib,
                 "install": mm.find_install_dir(cfg), "log": str(mm.LOG_PATH)}
        if kind in table:
            if not table[kind]:
                return self._json({"error": "这个目录还没设置"}, 400)
            mm.open_path(table[kind])
            return self._json({"ok": True})
        return self._json({"error": "不认识的类型：%s" % kind}, 400)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def port_busy(port) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def port_is_ours(port) -> bool:
    """这个端口上跑的是不是本工具自己（而不是别的程序）"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/state" % port, timeout=2) as r:
            d = json.loads(r.read().decode("utf-8"))
        return isinstance(d, dict) and "root" in d and "total" in d
    except Exception:
        return False


def say(title, text):
    """无控制台的 exe 里，用消息框把话说清楚，别静默退出"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    except Exception:
        pass


def pick_port(prefer):
    for p in range(prefer, prefer + 12):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
    return None


def main(argv=None):
    global ROOT_OVERRIDE
    ap = argparse.ArgumentParser(description="FFXIV Mod 管理工具 · 本地 Web 服务")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--root", default="", help="临时 Mod 根目录（不写回配置，测试用）")
    a = ap.parse_args(argv)
    ROOT_OVERRIDE = a.root
    if ROOT_OVERRIDE:
        # 临时根目录：索引库也换成独立的，绝不动真实索引
        mm.DB_PATH = Path(ROOT_OVERRIDE).resolve().parent / "mod_manager.root-override.db"

    if not (WEB_DIR / "index.html").is_file():
        print("  ! 缺少界面文件：%s（先到 web-src 里 npm run build）" % (WEB_DIR / "index.html"))

    # 默认端口上如果是本工具的另一个实例：直接用它，别再起一个抢同一个索引库
    if port_is_ours(a.port):
        url = "http://127.0.0.1:%d" % a.port
        print("  已经有一个在 %s 跑着了，直接打开它（不重复启动）。" % url)
        if not a.no_browser:
            webbrowser.open(url)
            say("FFXIV Mod 管理工具",
                "已经有一个在跑了，已直接打开：\n%s\n\n（不会重复启动第二个）" % url)
        return 0

    port = pick_port(a.port)
    if port is None:
        msg = ("端口 %d~%d 都被别的程序占用了，起不来。\n"
               "关掉占用端口的程序，或换端口启动：ModManagerWeb.exe --port 8800"
               % (a.port, a.port + 11))
        print("  " + msg.replace("\n", "\n  "))
        say("FFXIV Mod 管理工具", msg)
        return 1
    if port != a.port:
        print("  端口 %d 被别的程序占用了，改用 %d（要指定端口请加 --port）" % (a.port, port))

    cfg = cfg_now()
    mm.clean_stale_parts(cfg)
    url = "http://127.0.0.1:%d" % port
    print("=" * 62)
    print("  FFXIV Mod 管理工具 · Web 版")
    print("  界面地址： %s" % url)
    print("  Mod 目录： %s%s" % (cfg.get("root") or "(还没设置)",
                                 "   [临时模式 --root]" if ROOT_OVERRIDE else ""))
    if ROOT_OVERRIDE:
        print("  索引库　： %s（临时的，不动真库）" % mm.DB_PATH)
    print("  汇总表　： %s" % (cfg.get("excel") or ""))
    print("  只监听本机 127.0.0.1，关掉这个窗口或用页面上的「退出服务」即退出")
    print("=" * 62)

    httpd = Server(("127.0.0.1", port), Handler)
    if not a.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
