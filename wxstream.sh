#!/system/bin/sh
# ==============================================================
# wxstream.sh -- 以 root 运行，把微信数据 tar 流直接推给电脑
#
# 不落手机存储：tar 输出直接走 adb reverse 建立的通道进电脑。
#
# 顺序：
#   1) 电脑上先跑   python wxdump_android.py stream
#   2) 手机上再跑   sh wxstream.sh          ← 本脚本
#
# 参数：
#   -p <端口>   目标端口，要和电脑端一致（默认 9000）
#   -a <hash>   指定账号目录（默认挑 EnMicroMsg.db 最大的）
#   -m          连图片/语音/视频一起传（会很慢）
#   -k          不 force-stop 微信（默认会先杀掉，保证快照一致）
#   -h          帮助
# ==============================================================

WX="${WX_DIR:-/data/data/com.tencent.mm}"
PORT=9000
ACC=""
MEDIA=0
KILL=1
SAVED="$@"

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        -p) PORT="$2"; shift 2 ;;
        -a) ACC="$2"; shift 2 ;;
        -m) MEDIA=1; shift ;;
        -k) KILL=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "[!] 未知参数: $1"; usage; exit 1 ;;
    esac
done

say() { echo "[*] $*"; }
err() { echo "[!] $*" >&2; }

# ---------- root ----------
SU_CANDIDATES="su /system/bin/su /system/xbin/su /sbin/su \
/data/adb/ksu/bin/su /data/adb/ap/bin/su /debug_ramdisk/su /data/local/tmp/su"

SU_CMD=""
try_root() {
    for c in $SU_CANDIDATES; do
        if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then
            r=$("$c" -c id 2>/dev/null)
            case "$r" in *uid=0*) SU_CMD="$c"; return 0 ;; esac
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
    err "拿不到 root。请在 MT 管理器 / KernelSU 管理器的终端里跑本脚本。"
    exit 1
fi

# ---------- 找账号 ----------
if [ ! -d "$WX/MicroMsg" ]; then
    err "没找到 $WX/MicroMsg"
    exit 1
fi

BEST=""
BEST_SZ=0
say "扫描账号目录..."
for d in "$WX"/MicroMsg/*; do
    [ -d "$d" ] || continue
    h=${d##*/}
    [ ${#h} -eq 32 ] || continue
    case "$h" in *[!0-9a-fA-F]*) continue ;; esac
    f="$d/EnMicroMsg.db"
    if [ -f "$f" ]; then sz=$(wc -c < "$f" 2>/dev/null || echo 0); else sz=0; fi
    if [ "$sz" -ge 1048576 ]; then human="$((sz / 1048576)) MB"
    elif [ "$sz" -ge 1024 ]; then human="$((sz / 1024)) KB"
    else human="$sz B"; fi
    echo "    $h   EnMicroMsg.db = $human"
    if [ "$sz" -gt "$BEST_SZ" ]; then BEST_SZ=$sz; BEST="$d"; fi
done

if [ -n "$ACC" ]; then
    BEST="$WX/MicroMsg/$ACC"
    [ -d "$BEST" ] || { err "账号目录不存在: $BEST"; exit 1; }
fi
[ -n "$BEST" ] || { err "没找到任何 32 位账号目录"; exit 1; }
HASH=${BEST##*/}
say "使用账号目录: $HASH"

# ---------- 停微信 ----------
if [ "$KILL" = "1" ]; then
    say "force-stop 微信（保证快照一致）"
    am force-stop com.tencent.mm 2>/dev/null
    sleep 2
fi

# ---------- 组装 tar 目标 ----------
if [ "$MEDIA" = "1" ]; then
    TARGETS="MicroMsg/$HASH shared_prefs"
else
    TARGETS="MicroMsg/$HASH/EnMicroMsg.db \
MicroMsg/$HASH/EnMicroMsg.db-wal \
MicroMsg/$HASH/EnMicroMsg.db-shm \
MicroMsg/$HASH/CompatibleInfo.cfg \
shared_prefs"
fi

say "待传内容:"
for t in $TARGETS; do
    if [ -e "$WX/$t" ]; then
        echo "    $t  ($(du -sh "$WX/$t" 2>/dev/null | cut -f1))"
    else
        echo "    $t  (不存在，跳过)"
    fi
done

# ---------- 等电脑端就绪 ----------
# 电脑端会一直 accept 到收到非空流为止，所以这里的预检（产生 0 字节连接）
# 不会把机会用掉，可以放心重试。
say "等待电脑端就绪 ..."
i=0
READY=0
while [ "$i" -lt 60 ]; do
    if nc -w 2 127.0.0.1 "$PORT" </dev/null >/dev/null 2>&1; then
        READY=1
        break
    fi
    i=$((i + 1))
    if [ $((i % 5)) = 0 ]; then
        echo "    还在等 ... (${i}s)"
    fi
    sleep 1
done

if [ "$READY" != "1" ]; then
    err "连不上 127.0.0.1:$PORT"
    err "电脑端跑起来了吗？:  python wxdump_android.py stream -p $PORT"
    exit 1
fi
say "通道就绪"

# ---------- 推流 ----------
say "开始传输（大库可能要几分钟）..."
cd "$WX" || exit 1

tar -cf - $TARGETS 2>/dev/null | nc 127.0.0.1 "$PORT"
RC=$?

if [ "$RC" = "0" ]; then
    say "传输完成，去电脑端看结果"
else
    err "传输返回码 $RC"
    exit 1
fi
