# -*- coding: utf-8 -*-
"""把编译好的 ModBridge 打成一个 release zip，并生成 Dalamud 自定义插件源 pluginmaster.json。

用法：
    python pack-release.py                       # 用默认路径
    python pack-release.py <bin/Release 目录> <仓库根目录>

生成：
    <仓库根>/plugin/release/ModBridge-<版本>.zip
    <仓库根>/pluginmaster.json          （用 raw.githubusercontent.com 的地址）
    <仓库根>/pluginmaster-cdn.json      （用 cdn.jsdelivr.net 的地址，国内更稳）
之后把改动提交到仓库，Dalamud 里把对应地址粘进 /xlsettings → Experimental →
Custom Plugin Repositories 就能安装与自动更新。
"""
import json, shutil, sys, time, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BIN = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "bin-release"
ROOT = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else ROOT

OWNER, REPO = "yomo1024", "FFXIV_XMA_Manager"
BRANCH = "main"
RAW = "https://raw.githubusercontent.com/%s/%s/%s" % (OWNER, REPO, BRANCH)
CDN = "https://cdn.jsdelivr.net/gh/%s/%s@%s" % (OWNER, REPO, BRANCH)

# 1) 读插件自带清单，拿到版本与描述
mf = BIN / "ModBridge.json"
if not mf.is_file():
    raise SystemExit("找不到 %s（先 dotnet build -c Release 生成）" % mf)
man = json.loads(mf.read_text(encoding="utf-8-sig"))
ver = str(man.get("AssemblyVersion") or "0.0.0.0")
print("插件: %s v%s" % (man.get("Name"), ver))

# 2) 打 zip：DLL/JSON 放在压缩包根目录（Dalamud 就是这么取的）
outdir = ROOT / "plugin" / "release"
outdir.mkdir(parents=True, exist_ok=True)
short = ver[:-2] if ver.endswith(".0") else ver        # 0.2.7.0 -> 0.2.7
zip_path = outdir / ("ModBridge-%s.zip" % short)
if zip_path.exists():
    zip_path.unlink()
n = 0
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(BIN.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".dll", ".json") or f.name.endswith(".pdb"):
            continue
        z.write(f, f.name)          # 注意：放根目录，不要套一层文件夹
        n += 1
print("已打 zip: %s（%d 个文件，%.1f MB）" % (zip_path.name, n, zip_path.stat().st_size / 1048576))

rel = "plugin/release/%s" % zip_path.name
entry = {
    "Author": man.get("Author") or OWNER,
    "Name": man.get("Name") or "ModBridge",
    "InternalName": man.get("InternalName") or "ModBridge",
    "AssemblyVersion": ver,
    "Punchline": man.get("Punchline") or "",
    "Description": (man.get("Description") or "").replace("\r\n", "\n"),
    "ApplicableVersion": man.get("ApplicableVersion") or "any",
    "Tags": man.get("Tags") or ["mods", "penumbra"],
    "CategoryTags": ["utility"],
    "DalamudApiLevel": int(man.get("DalamudApiLevel") or 15),
    "LoadRequiredState": int(man.get("LoadRequiredState") or 0),
    "LoadSync": bool(man.get("LoadSync") or False),
    "CanUnloadAsync": bool(man.get("CanUnloadAsync") or False),
    "LoadPriority": int(man.get("LoadPriority") or 0),
    "IsHide": False,
    "IsTestingExclusive": False,
    "DownloadCount": 0,
    "LastUpdate": int(time.time()),
    "RepoUrl": man.get("RepoUrl") or ("https://github.com/%s/%s" % (OWNER, REPO)),
    "IconUrl": "",
    "DownloadLinkInstall": "",
    "DownloadLinkTesting": "",
    "DownloadLinkUpdate": "",
}


def write_master(file_name, base):
    e = dict(entry)
    e["DownloadLinkInstall"] = "%s/%s" % (base, rel)
    e["DownloadLinkUpdate"] = e["DownloadLinkInstall"]
    (ROOT / file_name).write_text(json.dumps([e], ensure_ascii=False, indent=2), encoding="utf-8")
    print("已写 %s  ->  %s" % (file_name, e["DownloadLinkInstall"]))


write_master("pluginmaster.json", RAW)
write_master("pluginmaster-cdn.json", CDN)
print("\nDalamud 里填（二选一，国内一般选第二个更稳）:")
print("   %s/pluginmaster.json" % RAW)
print("   %s/pluginmaster-cdn.json" % CDN)
