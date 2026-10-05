#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rootcheck.py -- 判断 adb shell 到底能不能拿到 root，以及是哪套 root 方案。

直接在 Python 里调 adb.exe，绕开 Git Bash 的路径转换（/data/... 会被 MSYS 改写）。

    python rootcheck.py

如果 KernelSU / Magisk 是活的，跑这个脚本时手机上应该会弹授权框 —— 记得点「允许」。
"""
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 各 root 方案的 su 落点
SU_PATHS = [
    "su",
    "/system/bin/su",
    "/system/xbin/su",
    "/sbin/su",
    "/debug_ramdisk/su",
    "/data/adb/ksu/bin/su",
    "/data/adb/ap/bin/su",
    "/data/adb/magisk/magisk su",
]

MANAGER_PKGS = ["me.weishu.kernelsu", "com.topjohnwu.magisk",
                "me.bmax.apatch", "me.weishu.kernelsu.next"]


def sh(cmd: str) -> tuple[int, str]:
    p = subprocess.run(["adb", "shell", cmd], capture_output=True)
    out = (p.stdout or b"").decode("utf-8", "replace").strip()
    err = (p.stderr or b"").decode("utf-8", "replace").strip()
    return p.returncode, (out or err)


def prop(name: str) -> str:
    return sh(f"getprop {name}")[1]


def main() -> None:
    rc, devs = sh("echo ok")
    if rc != 0 or "ok" not in devs:
        print("[!] adb 没有连上设备")
        sys.exit(1)

    print("=" * 66)
    print("设备")
    print("=" * 66)
    print(f"  型号      : {prop('ro.product.model')}")
    print(f"  厂商      : {prop('ro.product.brand')}")
    print(f"  Android   : {prop('ro.build.version.release')} (SDK {prop('ro.build.version.sdk')})")
    print(f"  内核      : {sh('cat /proc/version')[1][:80]}")
    print(f"  adb shell : {sh('id')[1]}")

    print()
    print("=" * 66)
    print("root 探测")
    print("=" * 66)
    print(f"  persist.sys.root.status = {prop('persist.sys.root.status') or '(空)'}"
          "   <- 0 表示系统认为未 root")
    print(f"  /data/adb 可遍历? {sh('ls -ld /data/adb')[1]}")

    print()
    print("  su 逐个试（手机上有弹窗就点允许）:")
    got = None
    for p in SU_PATHS:
        rc, out = sh(f"{p} -c id")
        ok = "uid=0" in out
        mark = "OK " if ok else "   "
        print(f"    {mark} {p:<28} -> {out[:60]}")
        if ok and not got:
            got = p

    print()
    print("=" * 66)
    print("痕迹扫描")
    print("=" * 66)
    for cmd in [
        "ls /system/bin /system/xbin 2>/dev/null | grep -iE '^(su|ksu|magisk|supersu)'",
        "getprop | grep -iE 'ksu|magisk|apatch|kernelsu'",
        "ls -d /data/app/*kernelsu* /data/app/*magisk* 2>/dev/null",
        "ls -d /data/adb/* 2>/dev/null",
        "ls /dev 2>/dev/null | grep -iE 'ksu|magisk|kernelsu'",
        "cat /proc/modules 2>/dev/null | grep -iE 'ksu|magisk|apatch'",
    ]:
        out = sh(cmd)[1]
        print(f"  $ {cmd}")
        print(f"      {out or '(空)'}")

    print()
    print("=" * 66)
    print("管理端 App")
    print("=" * 66)
    found = []
    for pkg in MANAGER_PKGS:
        rc, out = sh(f"pm list packages {pkg}")
        if pkg in out:
            print(f"  已安装  {pkg}")
            found.append(pkg)
    if not found:
        print("  没有发现 KernelSU / Magisk / APatch 管理端")

    print()
    print("=" * 66)
    if got:
        print(f"结论：root 可用，用 `{got}`")
        print(f"      python wxdump_android.py all")
    else:
        print("结论：adb shell 拿不到 root")
        if found:
            print(f"      管理端装着（{', '.join(found)}），但 root 没生效。")
            print("      打开管理端 App 看首页：")
            print("        · 显示版本号 / Working        -> root 是活的，问题在 adb 授权")
            print("          到「超级用户」里找 shell / adb，手动允许；再重跑本脚本")
            print("        · 显示未安装 / Not installed  -> 内核没打补丁，root 不可用")
            print("          需要重新刷入（GKI 打补丁或加载 LKM）")
        print()
        print("      临时绕过：走 /sdcard 中转，不需要 root")
        print("        手机上有 root 权限的文件管理器 -> 复制到 /sdcard/wxdump/")
        print("        python wxdump_android.py pull-sd")
    print("=" * 66)


if __name__ == "__main__":
    main()
