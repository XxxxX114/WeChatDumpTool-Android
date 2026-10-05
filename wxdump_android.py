#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wxdump_android.py -- Android 微信聊天记录提取 / 解密 / 导出

从一台已 root 的 Android 手机里取出微信的 SQLCipher 加密库，推导口令、
解密成明文 SQLite，再导出成可读的聊天记录（HTML / CSV / TXT / JSON）。

什么都不带直接跑，就是交互菜单（Windows 上双击 start.bat 即可）:
    python wxdump_android.py

一条龙:
    python wxdump_android.py all

分步:
    python wxdump_android.py doctor                # 环境自检：Python / 依赖 / adb / 设备
    python wxdump_android.py adb                   # 自动下载 platform-tools 到脚本旁
    python wxdump_android.py probe                 # 检查 adb / root / 列出账号目录
    python wxdump_android.py pull                  # 有 root：直接从 /data/data 拉
    python wxdump_android.py stream                # 手机 root 端推流直连电脑，不落手机存储
    python wxdump_android.py pull-sd               # 无 root 中转：从 /sdcard/wxdump 拉
    python wxdump_android.py local                 # 数据已在本地：crack -> decrypt -> export
    python wxdump_android.py crack                 # 从 shared_prefs 推 uin 并试出口令
    python wxdump_android.py decrypt               # 解出明文 sqlite
    python wxdump_android.py export --format html  # 导出 html / csv / txt / json

直连推流（推荐，手机端要有 root 终端）:
    电脑:  python wxdump_android.py stream
    手机:  sh /data/local/tmp/wxstream.sh

已经手动把数据拷到本地了？跳过 probe/pull，直接:
    python wxdump_android.py crack   --src ./dump
    python wxdump_android.py decrypt --src ./dump
    python wxdump_android.py export  --format html --src ./dump

换工作目录（所有拉取/解密/导出产物都落在这里，默认 = 脚本旁的 dump/）:
    python wxdump_android.py all --src "D:/wxwork"

依赖:
    pip install -r requirements.txt

仅限自有设备与自有账号。详见 README 的「合法边界」。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime

__version__ = "1.0.0"

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

PKG = "com.tencent.mm"
DEV_DATA = f"/data/data/{PKG}"

HERE = os.path.dirname(os.path.abspath(__file__))

# 工作目录：默认跟脚本放在一起（脚本在 WeChatdump-Android，产物就在 WeChatdump-Android/dump）
# 拉取 / 解密 / 导出的一切产物都落在这里，可用 --src 覆盖
WORK = os.path.join(HERE, "dump")

# 微信在拿不到真实 IMEI 时使用的回退常量（按命中概率排序）
IMEI_FALLBACKS = ["1234567890", "1234567890ABCDEF", "000000000000000"]

MEDIA_DIRS = ["image2", "voice2", "video", "sfs", "avatar", "emoji", "favorite"]

# 各种 root 方案下 su 的可能位置
# 最后两个是给「内核漏洞提权」用的：临时 root 通常把 su 丢在 /data/local/tmp
SU_CANDIDATES = [
    "su",
    "magisk su",
    "ksud su",
    "/system/bin/su",
    "/data/adb/ksu/bin/su",
    "/data/adb/ap/bin/su",
    "/debug_ramdisk/su",
    "/data/local/tmp/su",
    "/data/local/tmp/ksu/su",
]

# 无 root 中转：手机上把数据复制到这里的结构由 pull-sd 拉走
SD_STAGE = "/sdcard/wxdump"


# --------------------------------------------------------------------------
# adb 定位 —— 目标是「解压即用」：不用手动配 PATH
# --------------------------------------------------------------------------
PLATFORM_TOOLS_URL = {
    "nt": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}
PLATFORM_TOOLS_PAGE = "https://developer.android.com/tools/releases/platform-tools"

_ADB_BIN: str | None = None


def adb_names() -> list[str]:
    return ["adb.exe", "adb"] if os.name == "nt" else ["adb"]


def find_adb() -> str | None:
    """按优先级找 adb：$ADB -> PATH -> 脚本旁的 platform-tools/ -> 常见安装位置。"""
    env = os.environ.get("ADB")
    if env and os.path.isfile(env):
        return env
    hit = shutil.which("adb")
    if hit:
        return hit
    for root in (HERE, os.path.dirname(HERE)):
        for n in adb_names():
            p = os.path.join(root, "platform-tools", n)
            if os.path.isfile(p):
                return p
    home = os.path.expanduser("~")
    common = [
        r"D:\ADB\platform-tools", r"C:\ADB\platform-tools", r"C:\platform-tools",
        os.path.join(home, "AppData", "Local", "Android", "Sdk", "platform-tools"),
        os.path.join(home, "Android", "Sdk", "platform-tools"),
        os.path.join(home, "Library", "Android", "sdk", "platform-tools"),
        "/usr/lib/android-sdk/platform-tools",
        "/usr/local/share/android-sdk/platform-tools",
        "/opt/android-sdk/platform-tools",
    ]
    for d in common:
        for n in adb_names():
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    return None


def adb_bin() -> str:
    """全局唯一的 adb 可执行文件路径；找不到就退回裸名（让报错更直白）。"""
    global _ADB_BIN
    if _ADB_BIN is None:
        _ADB_BIN = find_adb() or "adb"
    return _ADB_BIN


def set_adb(path: str | None) -> None:
    global _ADB_BIN
    if path:
        _ADB_BIN = path


def download_platform_tools() -> str | None:
    """把官方 platform-tools 下载并解压到脚本旁，返回 adb 路径。"""
    import io
    import urllib.request
    import zipfile

    url = PLATFORM_TOOLS_URL.get(os.name) or PLATFORM_TOOLS_URL["linux"]
    log(f"下载 platform-tools: {url}")
    try:
        with urllib.request.urlopen(url, timeout=180) as r:
            data = r.read()
    except Exception as e:
        log(f"下载失败: {e}")
        return None
    log(f"下载完成 {human_size(len(data))}，解压中 ...")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(HERE)
    except Exception as e:
        log(f"解压失败: {e}")
        return None
    for n in adb_names():
        p = os.path.join(HERE, "platform-tools", n)
        if os.path.isfile(p):
            if os.name != "nt":
                os.chmod(p, 0o755)
            return p
    return None


# --------------------------------------------------------------------------
# 环境自检 —— 「一键」的前提是先把缺什么说清楚
# --------------------------------------------------------------------------
# (import 名, pip 安装名, 是否必需, 用途)
DEPS = [
    ("sqlcipher3", "sqlcipher3", True, "解密 EnMicroMsg.db"),
    ("lz4", "lz4", False, "解压 lvbuffer 里被 lz4 压缩的消息"),
    ("Crypto", "pycryptodome", False, "crack --brute 暴破口令时加速"),
]

MIN_PY = (3, 8)


def _dep_ok(mod: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def _pip_hint(names: list[str]) -> str:
    return f"{sys.executable} -m pip install " + " ".join(names)


def check_env() -> bool:
    """打印环境自检表。返回「跑主流程所需的东西是否齐全」。"""
    print()
    print("=" * 66)
    print("  环境自检")
    print("=" * 66)

    # --- Python ---------------------------------------------------------
    v = sys.version_info
    py_ok = (v.major, v.minor) >= MIN_PY
    print(f"  {'[ok]' if py_ok else '[!!]'}  Python {v.major}.{v.minor}.{v.micro}")
    print(f"        {sys.executable}")
    if not py_ok:
        print(f"        需要 Python {MIN_PY[0]}.{MIN_PY[1]} 或更高")

    # --- Python 依赖 ----------------------------------------------------
    missing_req, missing_opt = [], []
    for mod, pipname, req, why in DEPS:
        hit = _dep_ok(mod)
        mark = "[ok]" if hit else ("[!!]" if req else "[--]")
        print(f"  {mark}  {pipname:<14} {'必需' if req else '可选'}   {why}")
        if not hit:
            (missing_req if req else missing_opt).append(pipname)
    if missing_req:
        print()
        print("        缺必需依赖，先装：")
        print(f"          {_pip_hint(missing_req)}")
        print(f"        或一次性装全：{_pip_hint(['-r', 'requirements.txt'])}")
    if missing_opt:
        print()
        print(f"        可选依赖缺失（不影响主流程）：{_pip_hint(missing_opt)}")

    # --- adb ------------------------------------------------------------
    exe = find_adb()
    if exe:
        print(f"  [ok]  adb")
        print(f"        {exe}")
        try:
            r = subprocess.run([exe, "version"], capture_output=True, timeout=20)
            first = (r.stdout or b"").decode("utf-8", "replace").splitlines()
            if first:
                print(f"        {first[0].strip()}")
        except Exception:
            pass
        try:
            r = subprocess.run([exe, "devices"], capture_output=True, timeout=20)
            devs = [l.strip() for l in
                    (r.stdout or b"").decode("utf-8", "replace").splitlines()[1:]
                    if l.strip() and not l.startswith("*")]
            if devs:
                for d in devs:
                    print(f"        设备: {d}")
            else:
                print("        （当前没有已连接且已授权的设备）")
        except Exception:
            pass
    else:
        print("  [!!]  adb")
        print("        没找到。三种办法：")
        print(f"          1. 本工具里跑：python {os.path.basename(__file__)} adb"
              "   （自动下载到脚本旁）")
        print("          2. 手动下载 platform-tools 解压到脚本旁，或加进 PATH / 设 ADB 环境变量")
        print(f"             {PLATFORM_TOOLS_PAGE}")
        print("          3. 只用本地已有数据（crack/decrypt/export）的话，可以不装 adb")

    # --- 结论 -----------------------------------------------------------
    ready = py_ok and not missing_req
    print("=" * 66)
    if ready:
        print("  结论：核心环境 OK"
              + ("；adb 未就绪（仅影响拉取环节）" if not exe else "，可以开跑了"))
    else:
        print("  结论：还差点东西，按上面提示装完再跑 `doctor`")
    print()
    return ready


# MessageType -> 中文名（与留痕导出一致）
# 注意：真实库里的 type 高位会带标志位（如 0x11000031），必须先 & 0xFFFF
MSG_TYPE_NAMES = {
    -1: "未知类型", 1: "文本", 2: "文本", 3: "图片", 6: "文件/位置共享",
    34: "语音", 42: "名片", 43: "视频", 47: "动画表情", 48: "位置",
    49: "链接/文件/引用", 50: "音视频通话", 62: "小视频", 64: "音视频通话",
    66: "企业微信名片", 67: "企业微信消息", 10000: "系统消息", 10002: "系统消息",
}


def human_size(n: float) -> str:
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{int(n)} B"


def real_type(t) -> int:
    """微信 message.type 的高 16 位是标志位，真实类型在低 16 位。

    例：285212721(0x11000031) -> 49，268445456(0x10002710) -> 10000。
    """
    try:
        return int(t) & 0xFFFF
    except (TypeError, ValueError):
        return -1


def normalize_ts(v) -> int:
    """把 createTime 归一成秒。真机库里存的是 13 位毫秒时间戳。"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    while n > 10 ** 11:          # 毫秒 / 微秒 -> 秒
        n //= 1000
    return n


# 群聊消息 content 前缀就是发送者，但分隔符随消息类型变化：
#   文本/49:  "wxid_xxx:\n正文"
#   语音 34:  "wxid_xxx:4197:0\n"      冒号后是时长元数据
#   视频 43:  "wxid_xxx:0:0\n"
#   表情 47:  "wxid_xxx:0:1:<md5>:<md5>..."   连换行都没有
SENDER_ID = (
    r"(?:wxid_[A-Za-z0-9_]{4,}|[0-9]+@(?:openim|chatroom)|gh_[0-9a-f]{8,}"
    r"|newsapp|fmessage|medianote|floatbottle|qmessage|tmessage"
    r"|qqmail|weibo|notifymessage|voiceinputapp)"
)
SENDER_PREFIX_RE = re.compile(r"^(" + SENDER_ID + r"):\n")
SENDER_PREFIX_META_RE = re.compile(r"^(" + SENDER_ID + r"):")
# 这几类的正文是元数据，不是用户文本，所以冒号后不跟换行也可以直接切
SENDER_META_TYPES = {3, 34, 43, 47, 62}


def split_sender(talker: str, content: str, mtype: int | None = None) -> tuple[str, str]:
    """群聊消息剥离发送者前缀，返回 (发送者 wxid, 正文)。单聊原样返回。"""
    if not (talker and talker.endswith("@chatroom")):
        return "", content
    m = SENDER_PREFIX_RE.match(content)
    if m:
        return m.group(1), content[m.end():]
    if mtype in SENDER_META_TYPES:
        m = SENDER_PREFIX_META_RE.match(content)
        if m:
            return m.group(1), content[m.end():]
    return "", content


def log(msg: str) -> None:
    print(f"[*] {msg}", flush=True)


def die(msg: str, code: int = 1):
    print(f"[!] {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def dq(s: str) -> str:
    """把字符串包成设备端 shell 的单引号参数。"""
    return "'" + s.replace("'", "'\\''") + "'"


DEV_ANCHORS = ("/sdcard/", "/storage/", "/data/", "/mnt/", "/system/", "/debug_ramdisk/")


def fix_remote_path(p: str) -> str:
    """Git Bash(MSYS) 会把命令行里的 /data/... 自动改写成 C:/.../PortableGit/.../data/...
    这里把它还原成设备端路径，免得用户被这个坑绕进去。
    """
    if not p or p.startswith("/"):
        return p
    for anchor in DEV_ANCHORS:
        i = p.find(anchor)
        if i > 0:
            fixed = p[i:]
            log(f"路径被 Git Bash 改写，已还原: {p}  ->  {fixed}")
            return fixed
    return p


# --------------------------------------------------------------------------
# adb
# --------------------------------------------------------------------------
class Adb:
    def __init__(self, su_override: str | None = None):
        self.su = None
        self.su_override = su_override

    def _raw(self, args: list[str], binary: bool = False, timeout: int = 600,
             check: bool = True):
        try:
            p = subprocess.run([adb_bin()] + args, capture_output=True, timeout=timeout)
        except FileNotFoundError:
            die("找不到 adb。\n"
                "    · 装好 platform-tools 并加进 PATH，或设 ADB 环境变量\n"
                f"    · 或者让本工具自动下：python {os.path.basename(__file__)} adb\n"
                f"    · 手动下载：{PLATFORM_TOOLS_PAGE}")
        except subprocess.TimeoutExpired:
            die("adb 命令超时")
        if check and p.returncode != 0:
            err = p.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(err or f"adb 返回 {p.returncode}")
        return p.stdout

    def shell(self, cmd: str, check: bool = True) -> str:
        return self._raw(["shell", cmd], check=check).decode("utf-8", "replace")

    def su_shell(self, cmd: str) -> str:
        return self._raw(["shell", f"{self.su} -c {dq(cmd)}"]).decode("utf-8", "replace")

    def su_exec(self, cmd: str) -> bytes:
        return self._raw(["exec-out", f"{self.su} -c {dq(cmd)}"], binary=True)

    def su_tar(self, cmd: str, out_path: str, timeout: int = 7200) -> int:
        """把设备端的 tar 流直接落到本地文件，避免大目录占内存。"""
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as f:
            p = subprocess.run([adb_bin(), "exec-out", f"{self.su} -c {dq(cmd)}"],
                               stdout=f, stderr=subprocess.PIPE, timeout=timeout)
        size = os.path.getsize(out_path)
        if p.returncode != 0 or size < 512:
            return 0
        return size

    def detect_device(self) -> None:
        try:
            out = self.shell("echo ok")
        except RuntimeError:
            out = ""
        if "ok" not in out:
            self.diagnose_device()
        log("adb 连接正常")

    def diagnose_device(self) -> None:
        """手机没连上时的自解释提示 —— 新手最容易卡在这里。"""
        raw = ""
        try:
            r = subprocess.run([adb_bin(), "devices", "-l"],
                               capture_output=True, timeout=30)
            raw = (r.stdout or b"").decode("utf-8", "replace").strip()
        except Exception as e:
            raw = f"(跑 adb devices 也失败了: {e})"

        print("", file=sys.stderr)
        print("=" * 62, file=sys.stderr)
        print("  没有检测到已连接的手机", file=sys.stderr)
        print("=" * 62, file=sys.stderr)
        print(f"  adb: {adb_bin()}", file=sys.stderr)
        print("  adb devices -l 输出:", file=sys.stderr)
        for line in (raw or "(空)").splitlines():
            print(f"    {line}", file=sys.stderr)
        print("", file=sys.stderr)
        print("  按顺序检查：", file=sys.stderr)
        print("    1. 数据线插好了吗（要能传数据的线，不是只能充电的）", file=sys.stderr)
        print("    2. 手机上「开发者选项 → USB 调试」打开了吗", file=sys.stderr)
        print("       （设置 → 关于手机 → 连点「版本号」7 次才会出现开发者选项）", file=sys.stderr)
        print("    3. 插上后手机上会弹「允许 USB 调试吗？」→ 点允许", file=sys.stderr)
        print("       没弹窗就先把通知栏拉下来看看，或拔插一次数据线", file=sys.stderr)
        print("    4. 上面 devices 里显示 unauthorized = 没点允许；", file=sys.stderr)
        print("       offline = 换根线或重插；列表为空 = 驱动没装", file=sys.stderr)
        print("    5. Windows 驱动没装的话，装厂商的 USB 驱动，或用无线调试", file=sys.stderr)
        print("", file=sys.stderr)
        print("  想确认 adb 本身没问题（不接手机也能测）：", file=sys.stderr)
        print(f"    python {os.path.basename(__file__)} doctor", file=sys.stderr)
        print("", file=sys.stderr)
        print("  不想用 adb？只要你能把手机上的数据弄到电脑，就能继续：", file=sys.stderr)
        print("    · 菜单选 5) 无 root 中转拉取（数据先拷到 /sdcard/wxdump）", file=sys.stderr)
        print("    · 或者手动把 MicroMsg/ 和 shared_prefs/ 放进 dump/，", file=sys.stderr)
        print("      再跑 `python wxdump_android.py local`", file=sys.stderr)
        print("=" * 62, file=sys.stderr)
        die("没有可用设备")

    def detect(self) -> None:
        self.detect_device()
        cands = ([self.su_override] if self.su_override else []) + SU_CANDIDATES
        for cand in cands:
            try:
                out = self._raw(["shell", f"{cand} -c id"]).decode("utf-8", "replace")
            except Exception:
                continue
            if "uid=0" in out:
                self.su = cand
                log(f"root 可用，使用 `{cand}`")
                return
        self.diagnose_root()

    def diagnose_root(self) -> None:
        def q(cmd: str) -> str:
            try:
                return self.shell(cmd).strip()
            except Exception:
                return ""

        model = q("getprop ro.product.model")
        rel = q("getprop ro.build.version.release")
        sdk = q("getprop ro.build.version.sdk")
        status = q("getprop persist.sys.root.status")
        mgrs = q("pm list packages | grep -iE 'kernelsu|magisk|apatch|topjohnwu|weishu'")
        print("", file=sys.stderr)
        print("=" * 62, file=sys.stderr)
        print("诊断：adb shell 拿不到 root", file=sys.stderr)
        print(f"  设备        : {model}  Android {rel} (SDK {sdk})", file=sys.stderr)
        print(f"  adb shell   : {q('id')}", file=sys.stderr)
        print(f"  su 候选     : {', '.join(SU_CANDIDATES)}  全部失败", file=sys.stderr)
        if status:
            print(f"  系统 root 标记: persist.sys.root.status = {status}"
                  "（0 = 系统认为未 root）", file=sys.stderr)
        if mgrs:
            for line in mgrs.splitlines():
                print(f"  发现管理端  : {line.replace('package:', '')}", file=sys.stderr)
        else:
            print("  未发现 KernelSU / Magisk / APatch 管理端", file=sys.stderr)
        print("", file=sys.stderr)
        print("  装了管理端 ≠ root 生效。请打开管理端 App 看首页：", file=sys.stderr)
        print("    · 显示版本号 / Working  -> root 是活的，用它的内置终端跑 `su -c id` 验证", file=sys.stderr)
        print("    · 显示未安装 / Not installed -> 内核没打补丁，root 实际不可用", file=sys.stderr)
        print("", file=sys.stderr)
        print("  如果管理端里 root 是好的，但 adb shell 用不了，走 sdcard 中转（不需要 root）：", file=sys.stderr)
        print("    1) 手机上用 MT 管理器之类有 root 的文件管理器，把", file=sys.stderr)
        print("       /data/data/com.tencent.mm/MicroMsg/<hash>/EnMicroMsg.db*", file=sys.stderr)
        print("       和 /data/data/com.tencent.mm/shared_prefs/ 复制到 /sdcard/wxdump/", file=sys.stderr)
        print("       （目标结构：wxdump/MicroMsg/EnMicroMsg.db、wxdump/shared_prefs/）", file=sys.stderr)
        print("    2) python wxdump_android.py pull-sd     # 无 root 拉取", file=sys.stderr)
        print("    3) python wxdump_android.py crack && ... decrypt && ... export", file=sys.stderr)
        print("=" * 62, file=sys.stderr)
        die("root 不可用，见上方诊断")


# --------------------------------------------------------------------------
# 定位账号目录
# --------------------------------------------------------------------------
def find_accounts(adb: Adb) -> list[dict]:
    out = adb.su_shell(f"ls -1 {DEV_DATA}/MicroMsg")
    hashes = [x.strip() for x in out.splitlines() if re.fullmatch(r"[0-9a-fA-F]{32}", x.strip())]
    if not hashes:
        die(f"{DEV_DATA}/MicroMsg 下没有找到 32 位账号目录，微信是否装过/登录过？")

    accounts = []
    for h in hashes:
        base = f"{DEV_DATA}/MicroMsg/{h}"
        size = 0
        try:
            ls = adb.su_shell(f"ls -l {base}/EnMicroMsg.db")
            m = re.search(r"\s(\d+)\s+\S+\s+\S+\s+\S+\s+EnMicroMsg\.db", ls)
            if m:
                size = int(m.group(1))
        except Exception:
            pass
        accounts.append({"hash": h, "size": size, "path": base})
    accounts.sort(key=lambda a: a["size"], reverse=True)
    for a in accounts:
        log(f"账号目录 {a['hash']}  EnMicroMsg.db = {a['size'] / 1048576:.1f} MB")
    return accounts


# --------------------------------------------------------------------------
# 拉取
# --------------------------------------------------------------------------
def tar_extract_file(path: str, dest: str) -> int:
    n = 0
    with tarfile.open(path, mode="r:") as tf:
        for m in tf:
            if not (m.isfile() or m.isdir()):
                continue
            try:
                tf.extract(m, dest, filter="data")
                if m.isfile():
                    n += 1
            except Exception as e:
                log(f"解包跳过 {m.name}: {e}")
    return n


def pull_sd(adb: Adb, dest: str, remote: str = SD_STAGE) -> None:
    """无 root 中转：把手机上已经拷到 /sdcard 的数据拉下来。

    /sdcard 对 adb shell 可读，所以这条路不需要 su。
    """
    os.makedirs(dest, exist_ok=True)
    ls = adb.shell(f"ls -1 {remote} 2>/dev/null", check=False)
    if not ls.strip():
        die(f"设备上 {remote} 是空的。先在手机上用有 root 权限的文件管理器把\n"
            f"    /data/data/com.tencent.mm/MicroMsg/<hash>/EnMicroMsg.db*\n"
            f"    /data/data/com.tencent.mm/shared_prefs/\n"
            f"  复制到 {remote}/，保持 MicroMsg/ 和 shared_prefs/ 两层结构")
    log(f"设备上 {remote} 内容:\n" + "\n".join("      " + x for x in ls.split()))

    tmp = os.path.join(dest, "_pull.tar")
    with open(tmp, "wb") as f:
        p = subprocess.run([adb_bin(), "exec-out", f"cd {remote} && tar -cf - ."],
                           stdout=f, stderr=subprocess.PIPE, timeout=7200)
    if p.returncode != 0 or os.path.getsize(tmp) < 512:
        die("tar 失败，检查路径")
    n = tar_extract_file(tmp, dest)
    os.remove(tmp)
    log(f"无 root 拉取完成: {n} 个文件 -> {dest}")


def pull(adb: Adb, acc: dict, dest: str, media: bool) -> None:
    """有 root：直接从 /data/data/com.tencent.mm 拉。"""
    os.makedirs(dest, exist_ok=True)
    base = acc["path"]
    tmp = os.path.join(dest, "_pull.tar")

    log("拉取数据库 ...")
    targets = " ".join([
        "EnMicroMsg.db", "EnMicroMsg.db-wal", "EnMicroMsg.db-shm",
        "FTS5IndexMicroMsg.db", "public_msg.db", "biz_message.db",
    ])
    size = adb.su_tar(f"cd {base} 2>/dev/null && tar -cf - {targets} 2>/dev/null", tmp)
    if not size:
        die("数据库 tar 包为空，检查路径与 root 权限")
    n = tar_extract_file(tmp, os.path.join(dest, "MicroMsg"))
    log(f"数据库: {size / 1048576:.1f} MB，解出 {n} 个文件")

    log("拉取 shared_prefs ...")
    size = adb.su_tar(f"cd {DEV_DATA}/shared_prefs 2>/dev/null && tar -cf - . 2>/dev/null", tmp)
    if size:
        tar_extract_file(tmp, os.path.join(dest, "shared_prefs"))

    log("拉取 CompatibleInfo.cfg ...")
    try:
        blob = adb.su_exec(f"cat {base}/CompatibleInfo.cfg")
        if blob:
            p = os.path.join(dest, "MicroMsg", "CompatibleInfo.cfg")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(blob)
    except Exception:
        pass

    if media:
        log("拉取附件目录（可能很大，慢慢等）...")
        dirs = " ".join(MEDIA_DIRS)
        size = adb.su_tar(f"cd {base} 2>/dev/null && tar -cf - {dirs} 2>/dev/null", tmp)
        if size:
            tar_extract_file(tmp, os.path.join(dest, "MicroMsg"))
            log(f"附件: {size / 1048576:.1f} MB 拉取完成")
        else:
            log("附件目录为空，跳过")

    if os.path.exists(tmp):
        os.remove(tmp)
    log(f"已保存到 {dest}")


# --------------------------------------------------------------------------
# 流式直传：手机 root 端 tar 流 -> adb reverse -> 电脑（不落手机存储）
# --------------------------------------------------------------------------
DB_NAMES = {
    "EnMicroMsg.db", "EnMicroMsg.db-wal", "EnMicroMsg.db-shm",
    "FTS5IndexMicroMsg.db", "public_msg.db", "biz_message.db",
    "CompatibleInfo.cfg",
}


def flatten_into(src_root: str, dest: str) -> int:
    """手机端是按 MicroMsg/<hash>/... 打的包，这里摊平成 dest/MicroMsg/..."""
    os.makedirs(os.path.join(dest, "MicroMsg"), exist_ok=True)
    os.makedirs(os.path.join(dest, "shared_prefs"), exist_ok=True)
    n = 0
    for dp, _dirs, files in os.walk(src_root):
        rel = os.path.relpath(dp, src_root)
        parts = [] if rel == "." else rel.split(os.sep)
        if "shared_prefs" in parts:
            for f in files:
                shutil.copy2(os.path.join(dp, f), os.path.join(dest, "shared_prefs", f))
                n += 1
            continue
        for f in files:
            src = os.path.join(dp, f)
            if f in DB_NAMES:
                shutil.copy2(src, os.path.join(dest, "MicroMsg", f))
                n += 1
            elif parts and parts[0] in MEDIA_DIRS:
                sub = os.path.join(dest, "MicroMsg", parts[0])
                os.makedirs(sub, exist_ok=True)
                shutil.copy2(src, os.path.join(sub, f))
                n += 1
    return n


def stream(adb: Adb, dest: str, port: int = 9000, timeout: int = 3600) -> None:
    """手机上以 root 跑 wxstream.sh，tar 流经 adb reverse 直接进电脑。

    方向是「手机主动连电脑」：电脑先监听，手机上再跑脚本，避免时序问题。
    会一直 accept 到收到非空流为止 —— 这样手机端可以先做连通性预检
    （预检会产生一个 0 字节连接），也天然容忍重试。
    """
    import socket
    import time

    os.makedirs(dest, exist_ok=True)
    tmp = os.path.join(dest, "_stream.tar")

    adb._raw(["reverse", "--remove-all"], check=False)
    adb._raw(["reverse", f"tcp:{port}", f"tcp:{port}"])
    log(f"adb reverse tcp:{port} tcp:{port} 已建立")

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(8)

    print()
    print("  " + "=" * 58)
    print("   现在在手机上跑（root 终端）：")
    print(f"       sh /data/local/tmp/wxstream.sh -p {port}")
    print(f"   等待手机连过来 ...（最多 {timeout // 60} 分钟）")
    print("  " + "=" * 58)
    print()

    deadline = time.time() + timeout
    total = 0
    try:
        while time.time() < deadline:
            srv.settimeout(max(1.0, deadline - time.time()))
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                break
            log("手机已连接，接收中 ...")
            n = 0
            last = 0
            with open(tmp, "wb") as f:
                while True:
                    chunk = conn.recv(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    n += len(chunk)
                    if n - last >= (64 << 20):
                        last = n
                        print(f"\r    已接收 {human_size(n)}", end="", flush=True)
            try:
                conn.close()
            except OSError:
                pass
            if n > 512:
                total = n
                break
            log("收到一个空连接（多半是手机端的预检），继续等 ...")
    finally:
        srv.close()
        adb._raw(["reverse", "--remove-all"], check=False)

    print()
    if total == 0:
        die("没收到数据。手机上跑 wxstream.sh 了吗？端口对得上吗？")
    log(f"接收完成，共 {human_size(total)}")

    staging = os.path.join(dest, "_stream")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    n = tar_extract_file(tmp, staging)
    os.remove(tmp)
    log(f"解包 {n} 个文件")
    m = flatten_into(staging, dest)
    shutil.rmtree(staging, ignore_errors=True)
    log(f"整理 {m} 个文件 -> {dest}")


# --------------------------------------------------------------------------
# 推 uin / imei，试出口令
# --------------------------------------------------------------------------
def _add(cands: list[str], v: str, why: str = "") -> None:
    if v and v not in cands:
        cands.append(v)
        if why:
            log(f"  + 候选 {v!r}  <- {why}")


def read_uin(src: str) -> list[str]:
    """从 shared_prefs 里收集 uin 候选。

    微信存的是 32 位有符号整数，账号大了就是负数（例如 -1234567890）。
    口令里用的字符串形式在不同版本里可能是：
        有符号原值      -1234567890
        无符号 32 位     3082398406
        绝对值          1234567890
    三种都塞进去，代价几乎为零。
    """
    uins: list[str] = []
    pat = re.compile(
        r'name="([^"]*uin[^"]*)"\s*(?:value="(-?\d+)"|>(-?\d+)<)',
        re.I,
    )
    for root, _dirs, files in os.walk(src):
        for fn in sorted(files):
            if not fn.endswith(".xml"):
                continue
            p = os.path.join(root, fn)
            try:
                txt = open(p, "r", encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for m in pat.finditer(txt):
                key = m.group(1)
                val = m.group(2) if m.group(2) is not None else m.group(3)
                variants = [val]
                try:
                    n = int(val)
                except ValueError:
                    n = None
                if n is not None:
                    if n < 0:
                        variants.append(str(n + (1 << 32)))   # 无符号 32 位
                    variants.append(str(abs(n)))
                for v in variants:
                    if v not in uins:
                        uins.append(v)
                        log(f"  + uin 候选 {v}  <- {fn}:{key}")
    return uins


def _hex_to_ascii(s: str) -> str | None:
    """把 '41424344' 这种十六进制串还原成它编码的 ASCII（'ABCD'）。"""
    if len(s) < 8 or len(s) % 2 or not re.fullmatch(r"[0-9A-Fa-f]+", s):
        return None
    try:
        raw = bytes.fromhex(s)
    except ValueError:
        return None
    if not raw or not all(0x20 <= b < 0x7F for b in raw):
        return None
    return raw.decode("ascii")


def read_imei_candidates(src: str) -> list[str]:
    """收集 imei 候选，命中概率高的排前面。

    现代 Android（10+）拿不到真实 IMEI，微信会自己造一个存进
    shared_prefs/WLOGIN_DEVICE_INFO.xml，但值是十六进制编码过的
    （例：4142434445464748494a4b4c4d4e4f50 -> ABCDEFGHIJKLMNOP）。
    原始串和解码串都要试。
    """
    cands: list[str] = []

    # 1) shared_prefs 里所有名字带 imei / android_id / device_id 的字段
    #    Android 的 SharedPreferences XML 有两种写法，都要认：
    #      <string name="imei" value="ABC" />      （值在属性里）
    #      <string name="imei">ABC</string>        （值在标签体里）
    entry_re = re.compile(
        r'<(?:string|int|long|boolean)\s+name="([^"]*)"\s*'
        r'(?:value="([^"]*)"\s*/?>|>([^<]*)</)',
        re.I,
    )
    key_re = re.compile(r"imei|android_id|androidid|device_id|deviceid|serial", re.I)
    for root, _dirs, files in os.walk(src):
        for fn in sorted(files):
            if not fn.endswith(".xml"):
                continue
            p = os.path.join(root, fn)
            try:
                txt = open(p, "r", encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for m in entry_re.finditer(txt):
                key = m.group(1)
                val = m.group(2) if m.group(2) is not None else m.group(3)
                if not val or not key_re.search(key):
                    continue
                val = val.strip()
                if not (4 <= len(val) <= 64):
                    continue
                dec = _hex_to_ascii(val)
                if dec:
                    _add(cands, dec, f"{fn}:{key} (hex->ascii)")
                _add(cands, val, f"{fn}:{key}")

    # 2) CompatibleInfo.cfg（老版本才有，纯属捡漏）
    p = os.path.join(src, "MicroMsg", "CompatibleInfo.cfg")
    if os.path.exists(p):
        raw = open(p, "rb").read()
        for m in re.finditer(rb"[\x20-\x7e]{10,24}", raw):
            s = m.group(0).decode("ascii", "ignore")
            if re.fullmatch(r"[0-9A-Fa-f]{10,20}", s) and s not in cands:
                cands.insert(0, s)
                log(f"  + 候选 {s!r}  <- CompatibleInfo.cfg")

    # 3) 已知回退常量
    for f in IMEI_FALLBACKS:
        _add(cands, f, "内置回退常量")

    # 4) 兜底：微信在完全拿不到 imei 时可能用空串
    _add(cands, "", "")
    return cands


def try_open(db_path: str, key: str) -> bool:
    try:
        from sqlcipher3 import dbapi2 as sqlcipher
    except ImportError:
        die("缺少 sqlcipher3 依赖，装一下：\n"
            f"    {sys.executable} -m pip install -r requirements.txt\n"
            f"    完整自检：python {os.path.basename(__file__)} doctor")
    for order in ("key_first", "compat_first"):
        conn = None
        try:
            conn = sqlcipher.connect(db_path)
            conn.execute("PRAGMA cipher_log_level = NONE")
            if order == "key_first":
                conn.execute(f"PRAGMA key = '{key}'")
                conn.execute("PRAGMA cipher_compatibility = 1")
            else:
                conn.execute("PRAGMA cipher_compatibility = 1")
                conn.execute(f"PRAGMA key = '{key}'")
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            conn.close()
            return True
        except Exception:
            try:
                conn and conn.close()
            except Exception:
                pass
    return False


def crack(src: str, brute: bool = False) -> dict:
    db = os.path.join(src, "MicroMsg", "EnMicroMsg.db")
    if not os.path.exists(db):
        die(f"这里还没有数据：{db}\n"
            "\n"
            "  这一步要先把手机上的微信数据弄到电脑。三条路：\n"
            "    1) 手机已连上 adb、且有 root  → 菜单选 2) 一键全流程\n"
            "    2) 手机上有 root 终端          → 菜单选 4) 手机端推流直连（推荐）\n"
            "    3) 什么都没有                  → 菜单选 5) 无 root 中转拉取\n"
            "\n"
            "  已经手动拷过数据？把结构摆成下面这样就行：\n"
            f"    {src}\\MicroMsg\\EnMicroMsg.db  (+ -wal / -shm)\n"
            f"    {src}\\shared_prefs\\\n"
            "\n"
            "  想先确认工具本身能跑通（不需要手机）：\n"
            "    python selfcheck.py                                  # 造一份假数据\n"
            f"    python {os.path.basename(__file__)} local --src ./selfcheck_data   # 跑一遍\n")

    log(f"目标库 {db}（{human_size(os.path.getsize(db))}）")
    uins = read_uin(src)
    if not uins:
        die("没能从 shared_prefs 里读到 uin，检查是否漏拉了 shared_prefs 目录")
    imeis = read_imei_candidates(src)

    log(f"uin 候选 {len(uins)} 个，imei 候选 {len(imeis)} 个，"
        f"共 {len(uins) * len(imeis)} 种组合")

    tried = 0
    for imei in imeis:
        for uin in uins:
            key = hashlib.md5((imei + uin).encode()).hexdigest()[:7]
            tried += 1
            if try_open(db, key):
                log(f"命中！imei={imei!r}  uin={uin}  口令={key}  （第 {tried} 次尝试）")
                info = {"imei": imei, "uin": uin, "key": key, "db": db}
                with open(os.path.join(src, "key.json"), "w", encoding="utf-8") as f:
                    json.dump(info, f, ensure_ascii=False, indent=2)
                log(f"已写入 {os.path.join(src, 'key.json')}")
                return info

    if brute:
        key = brute_force_key(db)
        if key:
            info = {"imei": None, "uin": None, "key": key, "db": db, "method": "bruteforce"}
            with open(os.path.join(src, "key.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)
            log(f"暴破命中口令 {key}，已写入 key.json")
            return info

    die(f"试了 {tried} 种 imei/uin 组合都打不开。\n"
        "    常见原因：\n"
        "      1. 拉取时微信还在运行，wal 没合并（重新 force-stop 微信后再拉一次）\n"
        "      2. 这是一台换过设备的库，imei 与当前设备不符\n"
        "      3. 微信改了口令算法\n"
        "    可以加 --brute 直接暴破 7 位十六进制口令空间（16^7 ≈ 2.7 亿，"
        "多核大约几十分钟到几小时）")


# --------------------------------------------------------------------------
# 口令暴破（兜底）——直接用 pbkdf2 + AES 自己验，不走 sqlcipher 连接开销
# --------------------------------------------------------------------------
def _brute_worker(args):
    lo, hi, db, salt, page = args
    from hashlib import pbkdf2_hmac
    try:
        from Crypto.Cipher import AES          # pycryptodome
    except Exception:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            AES = None
        except Exception:
            return None
    want = b"SQLite format 3\x00"
    for n in range(lo, hi):
        key = f"{n:07x}"
        dk = pbkdf2_hmac("sha1", key.encode(), salt, 4000, 32)
        if AES is not None:
            from Crypto.Util import Counter
            ctr = Counter.new(128, initial_value=0)
            dec = AES.new(dk, AES.MODE_CBC, iv=b"\x00" * 16)
            head = dec.decrypt(page[:16])
        else:
            dec = Cipher(algorithms.AES(dk), modes.CBC(b"\x00" * 16)).decryptor()
            head = dec.update(page[:16])
        if head[:16] == want:
            return key
    return None


def brute_force_key(db: str) -> str | None:
    """SQLCipher compat=1: PBKDF2-SHA1(4000) -> AES-256-CBC，无 HMAC，需解密首页比对魔数。"""
    import struct
    with open(db, "rb") as f:
        page = f.read(4096)
    salt = page[:16]
    total = 16 ** 7
    try:
        import multiprocessing as mp
        nproc = max(1, (os.cpu_count() or 4))
        chunk = total // (nproc * 8) + 1
        tasks = [(i, min(i + chunk, total), db, salt, page) for i in range(0, total, chunk)]
        log(f"开始暴破：{total} 个口令，{nproc} 进程，分 {len(tasks)} 批")
        with mp.Pool(nproc) as pool:
            for i, r in enumerate(pool.imap_unordered(_brute_worker, tasks), 1):
                if r:
                    pool.terminate()
                    return r
                if i % 8 == 0:
                    log(f"  已扫 {i}/{len(tasks)} 批 ...")
    except Exception as e:
        log(f"暴破不可用（{e}）；可改用 pip install pycryptodome 后重试")
    return None


# --------------------------------------------------------------------------
# 解密
# --------------------------------------------------------------------------
def decrypt(src: str, key: str | None = None) -> str:
    try:
        from sqlcipher3 import dbapi2 as sqlcipher
    except ImportError:
        die("缺少 sqlcipher3 依赖，装一下：\n"
            f"    {sys.executable} -m pip install -r requirements.txt\n"
            f"    完整自检：python {os.path.basename(__file__)} doctor")

    if key is None:
        kp = os.path.join(src, "key.json")
        if not os.path.exists(kp):
            die("没有 key.json，先执行 crack，或用 --key 指定口令")
        key = json.load(open(kp, encoding="utf-8"))["key"]

    enc = os.path.join(src, "MicroMsg", "EnMicroMsg.db")
    out = os.path.join(src, "MicroMsg", "EnMicroMsg.plain.db")
    if os.path.exists(out):
        os.remove(out)

    conn = sqlcipher.connect(enc)
    conn.execute("PRAGMA cipher_log_level = NONE")
    conn.execute(f"PRAGMA key = '{key}'")
    conn.execute("PRAGMA cipher_compatibility = 1")
    conn.execute(f"ATTACH DATABASE '{out}' AS plain KEY ''")
    conn.execute("SELECT sqlcipher_export('plain')")
    conn.execute("DETACH DATABASE plain")
    conn.close()

    chk = sqlite3.connect(out)
    n = chk.execute("SELECT count(*) FROM message").fetchone()[0]
    chk.close()
    log(f"解密完成 -> {out}  （message 表 {n} 条）")
    return out


# --------------------------------------------------------------------------
# 读取 + 导出
# --------------------------------------------------------------------------
def xml_to_dict(node) -> dict:
    d: dict = {}
    for k, v in node.attrib.items():
        d["@" + k] = v
    kids = list(node)
    if kids:
        for c in kids:
            sub = xml_to_dict(c)
            if c.tag in d:
                if not isinstance(d[c.tag], list):
                    d[c.tag] = [d[c.tag]]
                d[c.tag].append(sub)
            else:
                d[c.tag] = sub
    text = (node.text or "").strip()
    if text:
        d["#text"] = text
    return d


def parse_xml(content: str) -> dict:
    import xml.etree.ElementTree as ET
    try:
        return {"msg": xml_to_dict(ET.fromstring(content))}
    except Exception:
        return {}


def decompress_lz4(blob) -> str:
    if not blob:
        return ""
    raw = bytes(blob)
    try:
        import lz4.block
    except ImportError:
        return ""
    for size in (int.from_bytes(raw[:4], "big"), len(raw) * 20, None):
        try:
            if size is None:
                return ""
            return lz4.block.decompress(raw[4:], uncompressed_size=size).decode("utf-8", "replace")
        except Exception:
            continue
    return ""


class Reader:
    def __init__(self, plain_db: str):
        self.conn = sqlite3.connect(plain_db)
        self.conn.row_factory = sqlite3.Row
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(message)")}
        self.cols = cols
        self.contacts = self._load_contacts()

    def _load_contacts(self) -> dict:
        out = {}
        try:
            for r in self.conn.execute("SELECT username, alias, conRemark, nickname FROM rcontact"):
                name = (r["conRemark"] or "").strip() or (r["nickname"] or "").strip() or r["username"]
                out[r["username"]] = {
                    "name": name,
                    "remark": (r["conRemark"] or "").strip(),
                    "nickname": (r["nickname"] or "").strip(),
                }
        except sqlite3.Error:
            pass
        return out

    def me(self) -> str:
        """userinfo id=2 存的是自己的 wxid（不是 JSON），拿它去 rcontact 换昵称。"""
        wxid = ""
        try:
            for r in self.conn.execute("SELECT value FROM userinfo WHERE id = 2"):
                v = (r["value"] or "").strip()
                try:
                    d = json.loads(v)
                    if isinstance(d, dict) and d.get("nickname"):
                        return d["nickname"]
                except Exception:
                    pass
                if v:
                    wxid = v
        except sqlite3.Error:
            pass
        if wxid:
            c = self.contacts.get(wxid, {})
            return c.get("remark") or c.get("nickname") or wxid
        return "我"

    def sender_name(self, m: dict, title: str) -> str:
        """解析一条消息的发送者显示名。"""
        if m.get("isSend"):
            return "我"
        wx = m.get("sender") or ""
        if wx:
            c = self.contacts.get(wx)
            if c:
                return c.get("remark") or c.get("nickname") or wx
            return wx
        return title

    def talkers(self) -> list[tuple[str, int]]:
        rows = self.conn.execute(
            "SELECT talker, count(*) c FROM message GROUP BY talker ORDER BY c DESC"
        ).fetchall()
        return [(r["talker"], r["c"]) for r in rows]

    def messages(self, talker: str) -> list[dict]:
        sel = ["msgId", "type", "isSend", "createTime", "talker", "content"]
        for extra in ("lvbuffer", "imgPath", "msgSvrId", "reserved"):
            if extra in self.cols:
                sel.append(extra)
        order = "msgId" if "msgId" in self.cols else "rowid"
        sql = f"SELECT {','.join(sel)} FROM message WHERE talker = ? ORDER BY {order}"
        out = []
        for r in self.conn.execute(sql, (talker,)):
            d = dict(r)
            raw_is_send = d.get("isSend")
            d["type"] = real_type(d.get("type"))          # 掩掉高位标志
            d["createTime"] = normalize_ts(d.get("createTime"))  # 毫秒 -> 秒
            d["isSend"] = 1 if raw_is_send == 1 else 0
            # isSend: 0=接收 1=发送 2=系统 None=系统（实测只有 64/10000 用 None）
            d["isSys"] = bool(raw_is_send not in (0, 1) or d["type"] in (10000, 10002))
            sender, body = split_sender(talker, d.get("content") or "", d["type"])
            d["sender"] = sender
            d["body"] = body
            out.append(d)
        return out


def xtext(v, default: str = "") -> str:
    """xml_to_dict 的产物里，纯文本节点会变成 {'#text': ...}，这里统一取出来。"""
    if isinstance(v, dict):
        t = v.get("#text")
        return t if isinstance(t, str) else default
    if isinstance(v, str):
        return v
    if isinstance(v, list) and v:
        return xtext(v[0], default)
    return default


def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]*>", "", s or "").strip()


def find_deep_text(node, keys=("text", "plain", "content"), depth: int = 0) -> str:
    """在嵌套的 xml_dict 里递归找第一个可读文本（用于未知结构的 sysmsg）。"""
    if depth > 6:
        return ""
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, list):
        for it in node:
            r = find_deep_text(it, keys, depth + 1)
            if r:
                return r
        return ""
    if isinstance(node, dict):
        for k in keys:
            if k in node:
                r = find_deep_text(node[k], keys, depth + 1)
                if r:
                    return r
        for k, v in node.items():
            if k.startswith("@"):
                continue
            r = find_deep_text(v, keys, depth + 1)
            if r:
                return r
    return ""


def sysmsg_text(xml: dict) -> str:
    """从 sysmsg（type=10002 / 部分 10000）里抽出可读文本。

    两种根节点都要认：<msg><sysmsg>...</sysmsg></msg> 和直接 <sysmsg>...</sysmsg>。
    结构：sysmsg > sysmsgtemplate > content_template > template，
    template 里的 $xxx$ 占位符要用 link_list 里同名 link 的 title 回填。
    """
    root = xml.get("msg", {})
    if not isinstance(root, dict):
        return ""
    sm = root.get("sysmsg")
    if not isinstance(sm, dict):
        # 根节点本身就是 <sysmsg>
        sm = root if ("@type" in root or "sysmsgtemplate" in root) else {}
    if not sm:
        return ""
    tpl = sm.get("sysmsgtemplate")
    if isinstance(tpl, dict):
        ct = tpl.get("content_template")
        if isinstance(ct, dict):
            t = xtext(ct.get("template"))
            if t:
                links = ct.get("link_list", {})
                if isinstance(links, dict):
                    links = links.get("link")
                if links is not None:
                    if not isinstance(links, list):
                        links = [links]
                    mapping = {}
                    for ln in links:
                        if isinstance(ln, dict):
                            nm, ti = xtext(ln.get("@name")), xtext(ln.get("title"))
                            if nm and ti:
                                mapping[nm] = ti
                    if mapping:
                        t = re.sub(r"\$(\w+)\$",
                                   lambda mm: mapping.get(mm.group(1), ""), t)
                return t.strip()
            p = xtext(ct.get("plain"))
            if p:
                return p.strip()
    txt = xtext(sm.get("text")).strip()
    if txt:
        return txt
    # 兜底：未知结构（如 reportbizlocation）递归找 text 节点
    return find_deep_text(sm)


def voip_text(raw: str) -> str:
    """type=50 的通话消息：可能是内部串，也可能是 VoIPBubbleMsg XML。"""
    m = re.search(r"<!\[CDATA\[(.*?)\]\]>", raw, re.S)
    if m and m.group(1).strip():
        return m.group(1).strip()
    low = raw.lower()
    if "voice" in low:
        return "[语音通话]"
    if "video" in low:
        return "[视频通话]"
    return f"[音视频通话] {raw}".strip()


def appmsg_text(xml: dict, raw: str) -> str:
    """type=49 的 appmsg 细分类型 -> 可读文本。"""
    app = xml.get("msg", {}).get("appmsg", {})
    if not isinstance(app, dict):
        return strip_tags(raw) or "[分享/卡片消息]"
    title = xtext(app.get("title"))
    des = xtext(app.get("des"))
    atype = xtext(app.get("type"))

    if atype == "57":                                   # 引用消息
        ref = xtext(app.get("refermsg", {}).get("content"))
        if ref.lstrip().startswith("<"):
            rxml = parse_xml(ref)
            ref = appmsg_text(rxml, ref) if rxml else strip_tags(ref)
        head = title or "[引用]"
        return f"{head}\n  ↳ 引用：{ref}" if ref else head
    if atype == "6":                                    # 文件
        name = xtext(app.get("appattach", {}).get("attachname"))
        return f"[文件] {name or title}".strip()
    if atype == "5":                                    # 链接
        return f"[链接] {title}" + (f"\n{des}" if des else "")
    if atype == "4":                                    # 视频 / 音乐分享
        return f"[视频] {title}".strip()
    if atype == "17":                                   # 位置共享
        return f"[位置共享] {title}".strip()
    if atype == "19":                                   # 合并转发的聊天记录
        return f"[聊天记录] {title}".strip()
    if atype in ("33", "36"):                           # 小程序
        return f"[小程序] {title}".strip()
    if atype in ("51", "62", "53"):                     # 视频号 / 直播
        return f"[视频号] {title}".strip()
    if atype == "87":                                   # 群公告
        return f"[群公告] {title}".strip()
    if atype == "2000":
        return f"[转账] {title}".strip()
    if atype == "2001":
        return f"[红包] {title}".strip()
    return title or des or "[分享/卡片消息]"


def content_of(m: dict) -> tuple[str, dict]:
    """返回 (可读文本, xml_dict)"""
    raw = m.get("body")
    if raw is None:
        raw = m.get("content") or ""
    raw = raw.strip().rstrip("\x00").strip()
    t = real_type(m.get("type"))

    # 49 号消息的 XML 偶尔被 lz4 压在 lvbuffer 里
    if t == 49 and "<" not in raw:
        lv = decompress_lz4(m.get("lvbuffer")).strip()
        if lv:
            raw = lv

    xml = parse_xml(raw) if raw.lstrip().startswith("<") else {}

    if t in (1, 2):
        return raw, xml
    if t == 3:
        return "[图片]", xml
    if t == 34:
        return "[语音]", xml
    if t == 43:
        return "[视频]", xml
    if t == 47:
        return "[动画表情]", xml
    if t == 62:
        return "[小视频]", xml
    if t == 42:
        node = xml.get("msg", {})
        nick = xtext(node.get("@nickname")) if isinstance(node, dict) else ""
        uname = xtext(node.get("@username")) if isinstance(node, dict) else ""
        return f"[名片] {nick or uname}".strip(), xml
    if t == 48:
        loc = xml.get("msg", {}).get("location", {})
        label = xtext(loc.get("@label")) or xtext(loc.get("@poiname"))
        return f"[位置] {label}".strip(), xml
    if t == 6:
        app = xml.get("msg", {}).get("appmsg", {})
        title = xtext(app.get("title")) if isinstance(app, dict) else ""
        return (f"[位置共享] {title}" if title else "[位置共享]"), xml
    if t == 50:
        return voip_text(raw), xml
    if t == 64:
        return (raw or "[音视频通话]"), xml
    if t == 67:
        node = xml.get("msg", {})
        if isinstance(node, dict):
            nick = xtext(node.get("@nickname"))
            desc = xtext(node.get("@openimdesc"))
            if nick or desc:
                return f"[企业微信] {desc} {nick}".strip(), xml
        return (strip_tags(raw) or "[企业微信消息]"), xml
    if t in (10000, 10002):
        return (sysmsg_text(xml) or strip_tags(raw) or raw), xml
    if t == 49:
        return appmsg_text(xml, raw), xml
    return raw or "[消息]", xml


def type_name(t: int) -> str:
    return MSG_TYPE_NAMES.get(t, f"其他({t})")


def fmt_time(ts: int) -> str:
    try:
        return datetime.fromtimestamp(normalize_ts(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n]+', "_", s).strip() or "unknown"


def unique_names(rd: Reader, talkers: list[str]) -> dict[str, str]:
    """给每个会话算出唯一文件名。

    真机数据里大量联系人昵称是 "." "。" "🐟" 这种，直接当文件名会互相覆盖
    （实测 8 个昵称为 "." 的联系人被压成一个）。重名时追加 talker 标识。
    """
    import collections
    raw = {}
    for tk in talkers:
        c = rd.contacts.get(tk, {})
        raw[tk] = safe_name(c.get("name") or tk)
    cnt = collections.Counter(raw.values())
    out = {}
    for tk, base in raw.items():
        if cnt[base] > 1:
            suffix = re.sub(r"[^0-9A-Za-z]+", "", tk)[-12:]
            if not suffix:
                suffix = hashlib.md5(tk.encode()).hexdigest()[:8]
            out[tk] = f"{base}_{suffix}"
        else:
            out[tk] = base
    return out


def export_html(rd: Reader, talker: str, msgs: list[dict], outdir: str,
                base: str | None = None) -> tuple[str, str]:
    c = rd.contacts.get(talker, {})
    title = c.get("name") or talker
    is_group = talker.endswith("@chatroom")
    data = []
    for m in msgs:
        text, xml = content_of(m)
        who = "系统消息" if m.get("isSys") else rd.sender_name(m, title)
        data.append({
            "type": str(m["type"]),
            "type_name": type_name(m["type"]),
            "is_send": bool(m["isSend"]),
            "is_system": bool(m.get("isSys")),
            "timestamp": m["createTime"],
            "server_id": str(m.get("msgSvrId") or m.get("msgId") or ""),
            "sender": who,
            "sender_id": m.get("sender") or ("self" if m["isSend"] else talker),
            "display_name": who,
            "avatar_src": "",
            "xml_dict": xml,
            "text": text,
        })
    os.makedirs(outdir, exist_ok=True)
    base = base or safe_name(title)
    hp = os.path.join(outdir, base + ".html")
    jp = os.path.join(outdir, base + ".html.json")
    payload = json.dumps(data, ensure_ascii=False)
    html = (
        "<!doctype html><meta charset='utf-8'>"
        f"<title>{title}</title>"
        "<style>body{font:14px/1.6 sans-serif;background:#f5f5f5;margin:0;padding:16px}"
        ".m{max-width:60%;margin:8px 0;padding:8px 12px;border-radius:8px;background:#fff;white-space:pre-wrap}"
        ".me{margin-left:auto;background:#95ec69}"
        ".sys{max-width:100%;margin:6px auto;background:#e8e8e8;color:#666;text-align:center;font-size:12px}"
        ".t{font-size:11px;color:#888;margin-bottom:2px}"
        "</style>"
        f"<h2>{title}</h2><div id='chat'></div>"
        f"<script>var dataList = {payload};"
        "var box=document.getElementById('chat');"
        "dataList.forEach(function(m){var d=document.createElement('div');"
        "d.className='m'+(m.is_system?' sys':(m.is_send?' me':''));"
        "var t=new Date(m.timestamp*1000);"
        "var who=m.is_system?'':('<div class=\"t\">'+m.display_name+' '+"
        "t.toLocaleString()+'</div>');"
        "d.innerHTML=who+String(m.text).replace(/[<>&]/g,function(s){"
        "return {'<':'&lt;','>':'&gt;','&':'&amp;'}[s]});box.appendChild(d);});"
        "</script>"
    )
    open(hp, "w", encoding="utf-8").write(html)
    open(jp, "w", encoding="utf-8").write(payload)
    return hp, jp


def export_csv(rd: Reader, talker: str, msgs: list[dict], outdir: str,
               base: str | None = None) -> str:
    import csv
    c = rd.contacts.get(talker, {})
    title = c.get("name") or talker
    me = rd.me()
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, (base or safe_name(title)) + ".csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        # 列名与顺序对齐留痕（MemoTrace）的 CSV，便于直接导入
        w.writerow(["消息ID", "类型", "发送人", "时间", "内容", "备注", "昵称", "更多信息"])
        for m in msgs:
            text, _ = content_of(m)
            if m.get("isSys"):
                w.writerow([m.get("msgId") or "", type_name(m["type"]),
                            "系统消息", fmt_time(m["createTime"]), text, "", "", ""])
                continue
            if m["isSend"]:
                # 本人侧三列都取 Me()，这样留痕的「备注==发送人==昵称」启发式能判定本人
                w.writerow([m.get("msgId") or "", type_name(m["type"]), me,
                            fmt_time(m["createTime"]), text, me, me, "self"])
                continue
            sid = m.get("sender") or talker
            cc = rd.contacts.get(sid, {})
            w.writerow([
                m.get("msgId") or "", type_name(m["type"]), rd.sender_name(m, title),
                fmt_time(m["createTime"]), text,
                cc.get("remark") or title, cc.get("nickname") or title, sid,
            ])
    return path


def export_txt(rd: Reader, talker: str, msgs: list[dict], outdir: str,
               base: str | None = None) -> str:
    c = rd.contacts.get(talker, {})
    title = c.get("name") or talker
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, (base or safe_name(title)) + ".txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 与 {title} 的聊天记录（{len(msgs)} 条）\n\n")
        for m in msgs:
            text, _ = content_of(m)
            if m.get("isSys"):
                f.write(f"{fmt_time(m['createTime'])}  [系统] {text}\n")
            else:
                f.write(f"{fmt_time(m['createTime'])} {rd.sender_name(m, title)}\n{text}\n\n")
    return path


def export_json(rd: Reader, talker: str, msgs: list[dict], outdir: str,
                base: str | None = None) -> str:
    c = rd.contacts.get(talker, {})
    title = c.get("name") or talker
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, (base or safe_name(title)) + ".json")
    data = []
    for m in msgs:
        text, xml = content_of(m)
        data.append({
            "msg_id": m.get("msgId"), "server_id": m.get("msgSvrId"),
            "type": m["type"], "type_name": type_name(m["type"]),
            "is_send": bool(m["isSend"]), "is_system": bool(m.get("isSys")),
            "timestamp": m["createTime"], "time": fmt_time(m["createTime"]),
            "sender": "系统消息" if m.get("isSys") else rd.sender_name(m, title),
            "sender_id": m.get("sender") or ("self" if m["isSend"] else talker),
            "talker": talker, "text": text, "xml": xml,
        })
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return path


EXPORTERS = {"html": export_html, "csv": export_csv, "txt": export_txt, "json": export_json}
EXPORT_EXT = {"html": ".html", "csv": ".csv", "txt": ".txt", "json": ".json"}


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;") \
                    .replace(">", "&gt;").replace('"', "&quot;")


def write_index(rows: list[tuple], outdir: str, fmt: str) -> str:
    """生成 index.html 总览：所有会话按消息数排序，点进去看详情。"""
    from urllib.parse import quote
    ext = EXPORT_EXT[fmt]
    total = sum(r[2] for r in rows)
    body = []
    for i, (tk, title, n, base, _) in enumerate(sorted(rows, key=lambda r: -r[2]), 1):
        kind = "群聊" if tk.endswith("@chatroom") else (
            "公众号" if tk.startswith("gh_") else (
                "企业微信" if tk.endswith("@openim") else "单聊"))
        body.append(
            f"<tr><td>{i}</td>"
            f"<td><a href=\"{quote(base + ext)}\">{esc(title)}</a></td>"
            f"<td>{kind}</td><td>{esc(tk)}</td><td class=n>{n}</td></tr>"
        )
    path = os.path.join(outdir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "<!doctype html><meta charset='utf-8'><title>微信聊天记录总览</title>"
            "<style>body{font:14px/1.6 sans-serif;margin:24px;background:#fafafa;color:#222}"
            "table{border-collapse:collapse;width:100%;background:#fff}"
            "th,td{border-bottom:1px solid #eee;padding:6px 10px;text-align:left}"
            "th{background:#f0f0f0;position:sticky;top:0}"
            "td.n{text-align:right;font-variant-numeric:tabular-nums}"
            "tr:hover{background:#f6fbff}a{color:#0a6cff;text-decoration:none}"
            "</style>"
            f"<h2>微信聊天记录总览</h2>"
            f"<p>共 <b>{len(rows)}</b> 个会话，<b>{total}</b> 条消息。"
            f"格式：{fmt}</p>"
            "<table><tr><th>#</th><th>会话</th><th>类型</th><th>talker</th>"
            "<th class=n>消息数</th></tr>" + "".join(body) + "</table>"
        )
    return path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        prog="wxdump_android.py",
        description="Android 微信聊天记录提取 / 解密 / 导出（需 root）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "常见用法:\n"
            "  %(prog)s                        交互菜单（Windows 双击 start.bat 就是它）\n"
            "  %(prog)s doctor                 环境自检：Python / 依赖 / adb / 设备\n"
            "  %(prog)s adb                    自动下载 platform-tools 到脚本旁\n"
            "  %(prog)s all                    一条龙：probe -> pull -> crack -> decrypt -> export\n"
            "  %(prog)s all --media            连图片/语音/视频一起拉\n"
            "  %(prog)s local                  数据已在 dump/：crack -> decrypt -> export\n"
            "  %(prog)s stream                 手机端推流直连电脑（推荐，不落手机存储）\n"
            "  %(prog)s crack --brute          候选口令全失败时暴破 7 位十六进制空间\n"
            "  %(prog)s export --format csv    换导出格式（html/csv/txt/json）\n"
            "\n"
            "工作目录默认是脚本旁的 dump/，所有产物都落在那里，用 --src 改。\n"
            "仅限自有设备与自有账号。\n"
        ),
    )
    ap.add_argument("-V", "--version", action="version",
                    version=f"%(prog)s {__version__}")
    ap.add_argument("step", nargs="?", default=None,
                    choices=["doctor", "adb", "probe", "pull", "pull-sd", "stream",
                             "crack", "decrypt", "export", "local", "all"],
                    help="要执行的步骤；不填就进交互菜单")
    ap.add_argument("--src", default=WORK, help=f"工作目录（默认 {WORK}）")
    ap.add_argument("--media", action="store_true", help="pull 时连图片/语音/视频一起拉")
    ap.add_argument("--from", dest="remote", default=SD_STAGE,
                    help=f"pull-sd 从设备哪个目录拉（默认 {SD_STAGE}）")
    ap.add_argument("--port", type=int, default=9000, help="stream 用哪个端口（默认 9000）")
    ap.add_argument("--timeout", type=int, default=3600, help="stream 等待手机连接的秒数")
    ap.add_argument("--key", help="decrypt 时直接指定口令")
    ap.add_argument("--su", dest="su_path", help="手动指定 su 路径（如 /data/local/tmp/su）")
    ap.add_argument("--format", default="html", choices=list(EXPORTERS), help="导出格式")
    ap.add_argument("--talker", action="append", help="只导指定 talker（可重复），默认全部")
    ap.add_argument("--min-msgs", type=int, default=2, help="少于该条数的会话跳过")
    ap.add_argument("--brute", action="store_true",
                    help="crack 时若候选组合全失败，直接暴破 7 位十六进制口令空间")
    args = ap.parse_args()

    if args.step is None:
        interactive(args)
    else:
        run(args.step, args)


def run(step: str, args) -> None:
    """执行一个步骤。CLI 和交互菜单都走这里，保证行为一致。"""
    # ---- 不需要工作目录的步骤 ------------------------------------------
    if step == "doctor":
        check_env()
        return

    if step == "adb":
        p = download_platform_tools()
        if not p:
            die(f"自动下载失败，请手动下载后解压到脚本旁：{PLATFORM_TOOLS_PAGE}")
        set_adb(p)
        log(f"adb 就绪: {p}")
        return

    src = os.path.abspath(args.src)
    os.makedirs(src, exist_ok=True)
    args.remote = fix_remote_path(args.remote)
    if args.su_path:
        args.su_path = fix_remote_path(args.su_path)
    log(f"工作目录: {src}")

    # ---- 依赖前置检查，别等跑到一半才炸 --------------------------------
    if step in ("crack", "decrypt", "export", "local", "all") and not _dep_ok("sqlcipher3"):
        die("缺少 sqlcipher3 依赖，无法解密。\n"
            f"    装一下：{_pip_hint(['-r', 'requirements.txt'])}\n"
            f"    完整自检：python {os.path.basename(__file__)} doctor")

    if args.media:
        free = shutil.disk_usage(src).free
        log(f"可用空间: {free / 1073741824:.1f} GB（--media 会拉全部图片/语音/视频，注意留够）")
        if free < 2 * 1073741824:
            die("可用空间不足 2GB，先清理或不用 --media")

    adb = None

    def get_adb(need_root: bool = True) -> Adb:
        nonlocal adb
        if adb is None:
            adb = Adb(su_override=args.su_path)
            adb.detect() if need_root else adb.detect_device()
        return adb

    if step == "pull-sd":
        pull_sd(get_adb(need_root=False), src, args.remote)
        return

    if step == "stream":
        stream(get_adb(need_root=False), src, args.port, args.timeout)
        return

    if step in ("probe", "pull", "all"):
        a = get_adb()
        accs = find_accounts(a)
        if step == "probe":
            return
        pull(a, accs[0], src, args.media)

    if step in ("crack", "local", "all"):
        crack(src, brute=args.brute)

    plain = None
    if step in ("decrypt", "local", "all"):
        plain = decrypt(src, args.key)

    if step in ("export", "local", "all"):
        if plain is None:
            plain = os.path.join(src, "MicroMsg", "EnMicroMsg.plain.db")
            if not os.path.exists(plain):
                die("没有明文数据库，先执行 decrypt")
        rd = Reader(plain)
        outdir = os.path.join(src, "export", args.format)
        os.makedirs(outdir, exist_ok=True)
        counts = dict(rd.talkers())
        talkers = args.talker or [t for t, c in rd.talkers() if c >= args.min_msgs]
        names = unique_names(rd, talkers)
        log(f"共 {len(talkers)} 个会话，导出为 {args.format}")
        rows = []
        for tk in talkers:
            msgs = rd.messages(tk)
            if not msgs:
                continue
            got = EXPORTERS[args.format](rd, tk, msgs, outdir, names[tk])
            for p in (got if isinstance(got, tuple) else (got,)):
                log(f"  {len(msgs):>6} 条 -> {os.path.relpath(p, src)}")
            c = rd.contacts.get(tk, {})
            rows.append((tk, c.get("name") or tk, len(msgs), names[tk],
                         counts.get(tk, len(msgs))))
        idx = write_index(rows, outdir, args.format)
        log(f"共 {len(rows)} 个会话 / {sum(r[2] for r in rows)} 条消息")
        log(f"总览: {idx}")
        log(f"全部完成，输出目录: {outdir}")


# --------------------------------------------------------------------------
# 交互菜单 —— 双击进来看到的就是它
# --------------------------------------------------------------------------
MENU = """
    1) 检查环境            Python / 依赖 / adb / 设备 一次看完
    2) 一键全流程          拉取 -> 解口令 -> 解密 -> 导出
    3) 处理本地已有数据    解口令 -> 解密 -> 导出（数据已经在 dump/ 里）
    4) 手机端推流直连      stream（推荐，不落手机存储）
    5) 无 root 中转拉取    pull-sd（数据先拷到 /sdcard/wxdump）
    6) 只导出              换格式 html / csv / txt / json
    7) 下载 adb            platform-tools 自动解压到脚本旁
    0) 退出
"""


def _ask(prompt: str, default: str = "") -> str:
    try:
        v = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return v or default


def _ask_format(cur: str) -> str:
    opts = "/".join(EXPORTERS)
    v = _ask(f"  导出格式 [{opts}]（回车 = {cur}）: ", cur).lower()
    if v not in EXPORTERS:
        log(f"没这个格式，用 {cur}")
        return cur
    return v


def interactive(args) -> None:
    src = os.path.abspath(args.src)
    print()
    print("  " + "=" * 60)
    print("   Android 微信聊天记录提取 / 解密 / 导出")
    print(f"   wxdump_android.py v{__version__}")
    print("  " + "=" * 60)
    print("   留住淌在记忆里的ta，挽住回忆里的我。")
    print()
    print(f"   工作目录: {src}")
    print("   仅限自有设备与自有账号；详见 README「合法边界」。")
    while True:
        print(MENU)
        c = _ask("  输入序号后回车: ")
        if c in ("", "0", "q", "Q", "quit", "exit"):
            print("  再见。")
            return
        try:
            if c == "1":
                check_env()
            elif c == "2":
                run("all", args)
                return
            elif c == "3":
                run("local", args)
                return
            elif c == "4":
                run("stream", args)
                return
            elif c == "5":
                run("pull-sd", args)
                return
            elif c == "6":
                args.format = _ask_format(args.format)
                run("export", args)
                return
            elif c == "7":
                p = download_platform_tools()
                if p:
                    set_adb(p)
                    log(f"adb 就绪: {p}")
                else:
                    print(f"  自动下载失败，手动下载后解压到脚本旁：{PLATFORM_TOOLS_PAGE}")
            else:
                print("  没有这个选项，重新选。")
        except SystemExit:
            # 各步骤内部用 die() 退出，菜单里不该把整个进程带走
            print("  （这一步没跑通，回到菜单）")
        except Exception as e:
            print(f"\n  [!] 出错了：{e}", file=sys.stderr)
            if os.environ.get("WXDUMP_DEBUG"):
                import traceback
                traceback.print_exc()
            else:
                print("      要看完整堆栈：先 set WXDUMP_DEBUG=1 再跑一次",
                      file=sys.stderr)
            print("  （回到菜单）\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[*] 已中断")
    except SystemExit:
        raise
    except Exception as e:
        if os.environ.get("WXDUMP_DEBUG"):
            raise
        die(f"出错了：{e}\n"
            "    要看完整堆栈：set WXDUMP_DEBUG=1（Linux/macOS 用 export）再跑一次")
