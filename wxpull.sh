#!/system/bin/sh
# ==============================================================
# wxpull.sh -- 在手机上把微信聊天数据搬到中转目录，供电脑端拉取
#
# 在 Termux / KernelSU 终端 / MT 管理器的终端里跑：
#     sh wxpull.sh
#
# 参数：
#     -o <目录>   输出目录（默认自动探测 /sdcard/wxdump）
#     -a <hash>   指定账号目录（默认挑 EnMicroMsg.db 最大的那个）
#     -m          连图片/语音/视频一起搬（会很慢、很占空间）
#     -k          不 force-stop 微信（默认会先杀掉，保证数据一致）
#     -t          额外打一个 tar 包，方便走 MTP 直接拖走
#     -h          帮助
#
# 跑完在电脑上执行：
#     python wxdump_android.py pull-sd
# ==============================================================

WX="${WX_DIR:-/data/data/com.tencent.mm}"
SAVED="$@"
OUT=""
ACC=""
MEDIA=0
KILL=1
TARBALL=0

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        -o) OUT="$2"; shift 2 ;;
        -a) ACC="$2"; shift 2 ;;
        -m) MEDIA=1; shift ;;
        -k) KILL=0; shift ;;
        -t) TARBALL=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "[!] 未知参数: $1"; usage; exit 1 ;;
    esac
done

say() { echo "[*] $*"; }
err() { echo "[!] $*" >&2; }

# ---------- 0. root ----------
# adb shell 通常够不到 su（/data/adb 是 0700），所以在终端里跑这个脚本时
# 逐个候选路径试一遍，谁能出 uid=0 就用谁。
SU_CANDIDATES="su /system/bin/su /system/xbin/su /sbin/su \
/data/adb/ksu/bin/su /data/adb/ap/bin/su /debug_ramdisk/su /data/local/tmp/su"

SU_CMD=""
try_root() {
    for c in $SU_CANDIDATES; do
        if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then
            r=$("$c" -c id 2>/dev/null)
            case "$r" in
                *uid=0*)
                    SU_CMD="$c"
                    return 0
                    ;;
            esac
        fi
    done
    return 1
}

if [ "$(id -u)" = "0" ]; then
    say "已经是 root"
elif try_root; then
    say "用 $SU_CMD 提权（手机上弹窗就点允许）"
    SELF="$0"
    case "$SELF" in /*) ;; *) SELF="$(pwd)/$SELF" ;; esac
    exec "$SU_CMD" -c "sh '$SELF' $SAVED"
else
    err "拿不到 root。已试过:"
    for c in $SU_CANDIDATES; do err "    $c"; done
    echo
    err "从 adb shell 够不到 su 是正常的（/data/adb 权限 0700）。"
    err "请在下面这些地方跑本脚本，它们能向 KernelSU/Magisk 申请授权："
    err "  · MT 管理器的 root 终端 / 文件管理"
    err "  · KernelSU 管理器自带的终端"
    err "  · 你的提权脚本拿到的 root shell"
    exit 1
fi

# ---------- 1. 选输出目录 ----------
if [ -z "$OUT" ]; then
    if [ -d /sdcard ]; then
        OUT=/sdcard/wxdump
    elif [ -d "$HOME/storage/shared" ]; then
        OUT="$HOME/storage/shared/wxdump"
    else
        OUT=/data/local/tmp/wxdump
    fi
fi
say "输出目录: $OUT"

# ---------- 2. 找账号目录 ----------
if [ ! -d "$WX/MicroMsg" ]; then
    err "没找到 $WX/MicroMsg，微信装过并登录过吗？"
    exit 1
fi

say "扫描账号目录..."
BEST=""
BEST_SZ=0
for d in "$WX"/MicroMsg/*; do
    [ -d "$d" ] || continue
    h=${d##*/}
    [ ${#h} -eq 32 ] || continue
    case "$h" in *[!0-9a-fA-F]*) continue ;; esac
    f="$d/EnMicroMsg.db"
    if [ -f "$f" ]; then
        sz=$(wc -c < "$f" 2>/dev/null || echo 0)
    else
        sz=0
    fi
    if [ "$sz" -ge 1048576 ]; then
        human="$((sz / 1048576)) MB"
    elif [ "$sz" -ge 1024 ]; then
        human="$((sz / 1024)) KB"
    else
        human="$sz B"
    fi
    echo "    $h   EnMicroMsg.db = $human"
    if [ "$sz" -gt "$BEST_SZ" ]; then
        BEST_SZ=$sz
        BEST="$d"
    fi
done

if [ -n "$ACC" ]; then
    BEST="$WX/MicroMsg/$ACC"
    if [ ! -d "$BEST" ]; then
        err "指定的账号目录不存在: $BEST"
        exit 1
    fi
fi

if [ -z "$BEST" ]; then
    err "没找到任何 32 位账号目录"
    exit 1
fi
SRC="$BEST"
say "使用账号目录: ${SRC##*/}"

# ---------- 3. 停微信，保证快照一致 ----------
if [ "$KILL" = "1" ]; then
    say "force-stop 微信（避免复制到一半数据库还在写）"
    am force-stop com.tencent.mm 2>/dev/null
    sleep 2
fi

# ---------- 4. 建目录 ----------
mkdir -p "$OUT/MicroMsg" "$OUT/shared_prefs" || {
    err "无法创建 $OUT，换个 -o 路径试试"
    exit 1
}

cpf() {
    # 复制并校验大小
    s="$1"; t="$2"
    [ -f "$s" ] || return 0
    if cp -f "$s" "$t" 2>/dev/null; then
        a=$(wc -c < "$s" 2>/dev/null || echo 0)
        b=$(wc -c < "$t" 2>/dev/null || echo 0)
        if [ "$a" = "$b" ]; then
            echo "    OK   ${s##*/}  ($a bytes)"
        else
            err "大小不一致 ${s##*/}: $a -> $b"
        fi
    else
        err "复制失败: ${s##*/}"
    fi
}

# ---------- 5. 数据库 ----------
say "复制数据库..."
for f in EnMicroMsg.db EnMicroMsg.db-wal EnMicroMsg.db-shm \
         FTS5IndexMicroMsg.db public_msg.db biz_message.db; do
    cpf "$SRC/$f" "$OUT/MicroMsg/$f"
done
cpf "$SRC/CompatibleInfo.cfg" "$OUT/MicroMsg/CompatibleInfo.cfg"

# ---------- 6. shared_prefs（读 uin 用）----------
say "复制 shared_prefs..."
for f in "$WX"/shared_prefs/*.xml; do
    [ -f "$f" ] || continue
    cpf "$f" "$OUT/shared_prefs/${f##*/}"
done

# ---------- 7. 附件（可选）----------
if [ "$MEDIA" = "1" ]; then
    say "复制附件目录（慢，耐心等）..."
    for d in image2 voice2 video sfs avatar favorite; do
        [ -d "$SRC/$d" ] || continue
        say "  $d ..."
        rm -rf "$OUT/MicroMsg/$d" 2>/dev/null
        cp -r "$SRC/$d" "$OUT/MicroMsg/" 2>/dev/null || err "  $d 复制出错"
    done
    if [ -d "$WX/f/public" ]; then
        say "  emoji (f/public) ..."
        rm -rf "$OUT/MicroMsg/emoji" 2>/dev/null
        mkdir -p "$OUT/MicroMsg/emoji"
        cp -r "$WX/f/public/." "$OUT/MicroMsg/emoji/" 2>/dev/null
    fi
fi

# ---------- 8. 让 adb shell 读得到 ----------
chmod -R a+rX "$OUT" 2>/dev/null

# ---------- 9. 可选打包 ----------
if [ "$TARBALL" = "1" ]; then
    T="${OUT}.tar"
    say "打包 -> $T"
    rm -f "$T" 2>/dev/null
    ( cd "$OUT" && tar -cf "$T" . ) || err "打包失败"
    [ -f "$T" ] && echo "    OK   $T  ($(wc -c < "$T") bytes)"
fi

# ---------- 10. 汇总 ----------
echo
echo "=============================================================="
echo "完成。$OUT 结构："
echo "=============================================================="
find "$OUT" -maxdepth 2 | sed 's|^|  |'
echo
echo "占用: $(du -sh "$OUT" 2>/dev/null | cut -f1)"
echo
echo "下一步（电脑上）："
echo "  python wxdump_android.py pull-sd"
if [ "$OUT" != "/sdcard/wxdump" ]; then
    echo "  注意：输出目录不是默认的，要加 --from"
    echo "  python wxdump_android.py pull-sd --from $OUT"
fi
echo "  python wxdump_android.py crack"
echo "  python wxdump_android.py decrypt"
echo "  python wxdump_android.py export --format html"
echo "=============================================================="
