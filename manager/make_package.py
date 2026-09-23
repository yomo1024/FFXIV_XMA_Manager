# -*- coding: utf-8 -*-
"""
打包部署包（Web 版）· 版本号取自同目录 app_version.py
=====================================================================
把「Web 版整套」打成一个可以整包拷走的 zip：

    dist\\ModManagerWeb_部署包_v<版本>.zip
        └── ModManagerWeb_部署包_v<版本>\\
                部署说明.txt
                ModManagerWeb.exe      ← 双击即用（内置界面文件）
                启动Web版.bat / 停止Web版.bat
                使用说明-Web版.txt
                app.ico
                web\\                   ← 前端构建产物（备份/自助改）
                源码\\
                    mod_manager.py / mod_manager_web.py
                    build_web_exe.bat / build_exe.bat / make_package.py / 打包部署包.bat
                    requirements.txt
                    web-src\\          ← 前端源码（不含 node_modules）

用法： 双击 打包部署包.bat   （或 python make_package.py）
"""
from __future__ import annotations

import datetime
import sys
import zipfile
from pathlib import Path

from app_version import APP_VERSION          # 版本号唯一来源

APP_DIR = Path(__file__).resolve().parent
DIST = APP_DIR / "dist"
VERSION = APP_VERSION                         # 部署包版本跟管理器版本保持一致
PKG_NAME = "ModManagerWeb_部署包_v%s" % VERSION

ROOT_FILES = ["ModManagerWeb.exe", "启动Web版.bat", "停止Web版.bat",
              "使用说明-Web版.txt", "使用说明.txt", "app.ico"]
WEB_DIR = "web"                                  # 前端产物整目录
SRC_FILES = ["mod_manager.py", "mod_manager_web.py", "app_version.py", "build_web_exe.bat", "build_exe.bat",
             "make_package.py", "打包部署包.bat", "requirements.txt"]
SRC_WEB = "web-src"                              # 前端源码（跳过 node_modules/dist）
SKIP_DIRS = {"node_modules", "dist", ".vite", "__pycache__"}

DEPLOY_TEXT = """FFXIV Mod 管理工具 · Web 版   v{ver}   部署说明
======================================================================

【一、免安装使用（推荐）】
  1. 把整个文件夹解压到任意位置（别放 C:\\Program Files，其它盘都行，路径带中文也没关系）
  2. 双击  启动Web版.bat        （或直接双击 ModManagerWeb.exe）
  3. 浏览器会自动打开 http://127.0.0.1:8765
  4. 第一次会弹「首次使用」：填你的 Mod 根目录 → 点「保存并扫描」，完事。
  5. 关的时候点网页右上角「退出服务」，或双击 停止Web版.bat。

【二、运行环境】
  · Windows 10 / 11 64 位
  · 不需要装 Python —— 界面文件、openpyxl、Pillow、websocket-client 都已打进 exe
  · 「下载工作台」需要一个 Chromium 内核浏览器（Edge / Chrome / CentBrowser 都行），
    系统自带 Edge 通常就够；没有它也不影响其它功能
  · 服务只监听 127.0.0.1，局域网里别的机器访问不到，不需要放防火墙

【三、目录说明】
  ModManagerWeb.exe         主程序（双击运行，自带网页界面）
  启动Web版.bat              启动器（优先用 exe，没 exe 时用系统 Python 跑源码）
  停止Web版.bat              关闭后台服务
  使用说明-Web版.txt          完整功能说明（每个页面做什么、快捷键、常见问题）
  使用说明.txt               原来 tkinter 版的说明（备用）
  web\\                       前端构建产物（后端直接serve，改前端后重新打包会覆盖）
  browser-extension\\         浏览器拓展（Chrome/Edge「加载已解压的扩展程序」选它）
  docs\\                      说明文档（迁移到新电脑.md / 使用说明.md / 浏览器拓展-安装说明.md）
  源码\\                      源码 + 重新打包脚本 + scripts\\check_versions.py（版本校验）

【四、运行后会生成（都在程序目录里）】
  mod_manager.json          配置（Mod 根目录、Excel 路径、浏览器…）
  mod_manager.db            本地索引库（SQLite，删掉会自动重建）
  .thumb_cache\\             缩略图缓存
  backup\\                   备份目录（Excel 自动备份 + 打包备份的 zip）
  browser_profile\\          内置浏览器的独立配置（用过「下载工作台」才有）
  mod_manager.log           运行日志（出问题先看它）

【五、备份 / 迁移 / 重来】
  · 程序和数据是分开的：程序 = 这个文件夹；数据 = Mod 根目录 + 生成的汇总表
  · 工具栏「打包备份」：把 Mod 文件夹 + 索引库 + 汇总表 打成一个 zip（有进度、可取消）
  · 「备份 / 恢复」里可以恢复：跳过已存在 / 覆盖（旧的进回收站）/ 另存一份
  · 换电脑（迁机）：新机装本程序 → 「备份 / 恢复」恢复旧机导出的备份，
    勾「Mod 文件夹 + 索引库 + 汇总表」和「套用备份里的配置」→ 路径类项新机上不存在会自动
    保留新机当前设置（差异会列出）→ 插件点一次「测试连接 / 自动配对」即可。
    详见 docs\迁移到新电脑.md（备份包内也自带一份「迁移到新电脑.txt」）
  · 想重置：删掉 mod_manager.json / mod_manager.db / .thumb_cache / backup 即可

【六、从源码运行 / 重新打包（可选）】
      pip install -r 源码\\requirements.txt
      python 源码\\mod_manager_web.py            （起网页版）
      python 源码\\mod_manager.py                （起原来的窗口版）
  重新打包 exe：双击 源码\\build_web_exe.bat   （会先构建前端再打包）
  注意：构建前端需要 Node.js；打包时如果环境里有 NODE_ENV=production，
        要先用 set NODE_ENV= 清掉，否则 npm 会跳过 devDependencies。

【七、常见问题】
  · 浏览器说「拒绝连接」：服务没起来，重双击启动器；或看 mod_manager.log
  · 端口被占用：会自动往后找端口，看启动器/命令行打印的地址
  · 列表是空的：点「重新扫描」；或去「设置」确认 Mod 根目录
  · 下载工作台读不到页面：先在它打开的浏览器窗口里打开 Mod 页面，
    遇到人机验证就在那个窗口点一下，过几秒再点「读取当前页面」
  · 生成 Excel 失败：多半是 Excel/WPS 正开着那个文件，关掉再生成

  打包时间：{time}
"""


def add_tree(z, root: Path, arc_root: str, skip=None):
    """把一个目录树塞进 zip，返回文件数"""
    skip = skip or set()
    n = 0
    for p in sorted(root.rglob("*")):
        if any(part in skip for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            z.write(p, "%s/%s" % (arc_root, p.relative_to(root).as_posix()))
            n += 1
    return n


def pick_dir(name):
    """找目录：部署目录里在根下；仓库里 web-src/scripts 在 manager/ 下、browser-extension 在仓库根。"""
    for p in (APP_DIR / name, APP_DIR.parent / name):
        if p.is_dir():
            return p
    return None


def find_exe():
    """主程序位置：部署目录里摆在根下，仓库里 PyInstaller 默认扔 dist/ —— 两处都认。"""
    for p in (APP_DIR / "ModManagerWeb.exe", APP_DIR / "dist" / "ModManagerWeb.exe"):
        if p.is_file():
            return p
    return None


def main():
    exe = find_exe()
    if exe is None:
        sys.exit("找不到 ModManagerWeb.exe，请先双击 build_web_exe.bat 打包主程序。")

    DIST.mkdir(exist_ok=True)
    zip_path = DIST / (PKG_NAME + ".zip")
    if zip_path.exists():
        zip_path.unlink()

    written = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(PKG_NAME + "/部署说明.txt",
                   DEPLOY_TEXT.format(ver=VERSION,
                                      time=datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
        written.append("部署说明.txt")
        for f in ROOT_FILES:
            src = APP_DIR / f
            if f == "ModManagerWeb.exe":
                src = exe                       # 根下没有就用 dist/ 里那份
            if src.is_file():
                z.write(src, "%s/%s" % (PKG_NAME, f))
                written.append(f)
        n = add_tree(z, APP_DIR / WEB_DIR, "%s/%s" % (PKG_NAME, WEB_DIR))
        written.append("%s\\（%d 个文件）" % (WEB_DIR, n))
        for f in SRC_FILES:
            if (APP_DIR / f).is_file():
                z.write(APP_DIR / f, "%s/源码/%s" % (PKG_NAME, f))
                written.append("源码/" + f)
        n = add_tree(z, APP_DIR / SRC_WEB, "%s/源码/%s" % (PKG_NAME, SRC_WEB), SKIP_DIRS)
        written.append("源码/%s\\（%d 个文件，不含 node_modules）" % (SRC_WEB, n))
        d = pick_dir("scripts")                          # 版本校验脚本
        if d:
            n = add_tree(z, d, "%s/源码/scripts" % PKG_NAME)
            written.append("源码/scripts\\（%d 个文件：版本一致性校验）" % n)
        d = pick_dir("browser-extension")                # 浏览器拓展（整包带走才叫三件套）
        if d:
            n = add_tree(z, d, "%s/browser-extension" % PKG_NAME)
            written.append("browser-extension\\（%d 个文件）" % n)
        docs_dir = APP_DIR.parent / "docs"               # 说明文档（迁机指南等）
        if docs_dir.is_dir():
            got = 0
            for f in sorted(docs_dir.glob("*.md")):
                z.write(f, "%s/docs/%s" % (PKG_NAME, f.name))
                got += 1
            if got:
                written.append("docs\\（%d 个 md：迁移到新电脑 / 使用说明 / 浏览器拓展安装）" % got)

    size = zip_path.stat().st_size / 1048576
    print("部署包已生成：")
    print("  %s" % zip_path)
    print("  版本 v%s ｜ %.1f MB ｜ %d 个条目" % (VERSION, size, len(written)))
    for f in written:
        print("    - %s" % f)


if __name__ == "__main__":
    main()
