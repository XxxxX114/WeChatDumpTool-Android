# wxdump-android

> ### 留住淌在记忆里的ta，挽住回忆里的我。

从一台**已 root 的 Android 手机**里取出微信聊天记录：拉取 → 推导口令 → 解密 SQLCipher → 导出成可读格式。

输出格式与 [留痕 / MemoTrace](https://github.com/CosilC/WeChatMsgArchive) 对齐，可直接被其下游工具解析。

> ⚠️ **仅限你自己的设备和你自己的账号。** 详见文末「合法边界」。

## 最快路径

```bash
pip install -r requirements.txt      # 一次性
python wxdump_android.py doctor      # 看看还缺什么
python wxdump_android.py             # 进菜单，按提示选
```

Windows 用户可以直接**双击 `start.bat`**，它会自动找 Python、检查依赖、定位 adb，然后进同一个菜单。

没有手机、只想先确认工具本身能跑通？`python selfcheck.py` 会造一份假加密库，
把 解密 → 导出 整条链路走一遍。

---

## 特性

- **不落手机存储**：`stream` 模式让手机端把 tar 流经 `adb reverse` 直推电脑
- **一键可用**：双击 `start.bat`（Windows）/ `sh start.sh`（Linux/macOS）进交互菜单，
  自动找 Python、检查依赖、定位 adb；`python wxdump_android.py adb` 还能自动下载 platform-tools
- **口令自动推导**：从 `shared_prefs` 里挖 uin / imei，覆盖负数 uin、十六进制编码的 imei 等真实场景
- **真机调通**：所有解码逻辑都在一份 28 万条的实盘数据上验证过（见 [实测记录](#实测记录message-表解码的坑)）
- **四种导出**：HTML / CSV / TXT / JSON，另附 `index.html` 总览
- **无手机自检**：`selfcheck.py` 能造一份假加密库，把整条链路跑一遍，不碰真机；
  假数据复刻了真机形态，所以它同时是回归测试

---

## 环境要求

| 项      | 说明                                                    |
| ------ | ----------------------------------------------------- |
| Python | 3.8+（开发与实测用 3.13 / 3.14）                              |
| adb    | 可选但推荐。加进 `PATH`、设 `ADB` 环境变量，或直接放到脚本旁 `platform-tools/` |
| 手机     | 需要 root；或在手机上用有 root 权限的文件管理器手动拷数据                     |
| 依赖     | `sqlcipher3`（必需）、`lz4`（可选）                            |

不想手动配 adb？跑一次 `python wxdump_android.py adb`，会把官方 platform-tools 下载并解压到脚本旁边。
只用本地已有数据（`local` / `crack` / `decrypt` / `export`）的话，**可以不装 adb**。

---

## 安装

```bash
git clone https://github.com/<you>/wxdump-android.git
cd wxdump-android
pip install -r requirements.txt
```

Windows 上 `sqlcipher3` 编译困难时，可以改用预编译包：

```bash
pip install sqlcipher3-binary
```

> 懒得记命令？直接双击 `start.bat`（Windows）或 `sh start.sh`（Linux/macOS）。
> 启动器会自动找 Python、检查依赖（缺了会问你要不要装）、找不到 adb 时给出提示，然后进交互菜单。

---

## 文件结构

```
wxdump-android/
├── wxdump_android.py     主程序：拉取 / 解口令 / 解密 / 导出，也是交互菜单
├── start.bat             Windows 双击入口（找 Python -> 查依赖 -> 进菜单）
├── start.sh              Linux / macOS 入口
├── selfcheck.py          造假加密库，不用手机就能验证整条链路
├── rootcheck.py          单独诊断 root 状态（adb shell 拿不到 su 时用）
├── wxstream.sh           手机端脚本：stream 模式的推流端
├── wxpull.sh             手机端脚本：把数据拷到 /sdcard/wxdump（pull-sd 用）
├── requirements.txt
├── PROMO.md              作者自用的推广素材（各平台文案模板，跟使用无关）
└── dump/                 运行后生成，所有产物都在这里（已 gitignore）
```

`wxstream.sh` / `wxpull.sh` 是**推到手机上执行**的，电脑端不用跑：

```bash
adb push wxstream.sh /data/local/tmp/
adb shell "su -c 'sh /data/local/tmp/wxstream.sh'"
```

---

## 快速开始

先看一眼环境，缺什么它会直说：

```bash
python wxdump_android.py doctor
```

或者什么都不带跑，进菜单：

```bash
python wxdump_android.py
```

```
    1) 检查环境            Python / 依赖 / adb / 设备 一次看完
    2) 一键全流程          拉取 -> 解口令 -> 解密 -> 导出
    3) 处理本地已有数据    解口令 -> 解密 -> 导出（数据已经在 dump/ 里）
    4) 手机端推流直连      stream（推荐，不落手机存储）
    5) 无 root 中转拉取    pull-sd（数据先拷到 /sdcard/wxdump）
    6) 只导出              换格式 html / csv / txt / json
    7) 下载 adb            platform-tools 自动解压到脚本旁
    0) 退出
```

习惯敲命令的话，等价的分步流程：

```bash
# 1) 检查 adb / root / 列出账号目录
python wxdump_android.py probe

# 2) 拉取（三选一，见下一节）
python wxdump_android.py stream

# 3) 推口令 -> 解密 -> 导出
python wxdump_android.py crack
python wxdump_android.py decrypt
python wxdump_android.py export --format html
```

或者一条龙（仅适用于 adb shell 能直接拿到 root 的情况）：

```bash
python wxdump_android.py all
python wxdump_android.py all --media          # 连图片/语音/视频一起拉
```

数据已经手动拉到本地了？跳过拉取，一条命令走完后半程：

```bash
python wxdump_android.py local                # crack -> decrypt -> export
python wxdump_android.py local --format csv
```

所有产物都落在**脚本旁边的 `dump/`**，用 `--src` 换位置：

```bash
python wxdump_android.py all --src "D:/wxwork"
```

```
dump/
├── MicroMsg/
│   ├── EnMicroMsg.db              加密库
│   ├── EnMicroMsg.db-wal          WAL，少了会丢最近的消息
│   └── EnMicroMsg.plain.db        解密后的明文库
├── shared_prefs/                  推 uin 用
├── key.json                       命中的口令
└── export/
    ├── html/   index.html + 每会话一份 .html / .html.json
    ├── csv/    index.html + 每会话一份 .csv
    └── json/   index.html + 每会话一份 .json
```

---

## 三条拉取路线

| 路线           | 前置条件                  | 说明                                           |
| ------------ | --------------------- | -------------------------------------------- |
| **`stream`** | 手机上有一个能拿到 root 的终端    | **推荐**。tar 流经 `adb reverse` 直连电脑，手机存储上不留任何东西 |
| `pull`       | adb shell 自己能执行到 `su` | 直接从 `/data/data/com.tencent.mm/` 拉           |
| `pull-sd`    | 手机上有一个能拿到 root 的文件管理器 | 先拷到 `/sdcard/wxdump/`，电脑再拉。两步，但最稳            |

### stream（推荐）

```bash
# 电脑上先跑，它会建立 adb reverse 并开始监听
python wxdump_android.py stream

# 然后在手机的 root 终端里跑
sh /data/local/tmp/wxstream.sh
```

方向是「手机主动连电脑」，所以电脑先起、手机后跑，没有时序问题。  
手机端会先做连通性预检（产生一个 0 字节连接），电脑端会自动忽略空连接继续等。

```sh
sh wxstream.sh -m          # 连图片/语音/视频一起传
sh wxstream.sh -p 9001     # 换端口（电脑端 --port 9001）
sh wxstream.sh -a <hash>   # 指定账号目录
sh wxstream.sh -k          # 不 force-stop 微信
```

### pull（adb shell 能拿到 root 时）

```bash
python wxdump_android.py pull
python wxdump_android.py pull --media
python wxdump_android.py pull --su /data/local/tmp/su   # 手动指定 su 路径
```

### pull-sd（无 root 兜底）

手机上用有 root 权限的文件管理器，把下面这些复制到 `/sdcard/wxdump/`：

```
/data/data/com.tencent.mm/MicroMsg/<32位hash>/EnMicroMsg.db
/data/data/com.tencent.mm/MicroMsg/<32位hash>/EnMicroMsg.db-wal
/data/data/com.tencent.mm/MicroMsg/<32位hash>/EnMicroMsg.db-shm
/data/data/com.tencent.mm/shared_prefs/          -> 整个目录
```

目标结构是 `wxdump/MicroMsg/EnMicroMsg.db` + `wxdump/shared_prefs/`。  
也可以直接跑 `wxpull.sh`（手机上执行）自动完成这一步：

```bash
# 手机上
sh /data/local/tmp/wxpull.sh

# 电脑上
python wxdump_android.py pull-sd
```

---

## 口令是怎么来的

```
password = md5(imei + uin)[:7]        # 全小写
```

### uin

在 `shared_prefs/auth_info_key_prefs.xml` 的 `_auth_uin` / `_auth_uin64` 字段。

⚠️ **它是 32 位有符号整数，账号大了就是负数**（例如 `-1234567890`）。  
正则写成 `value="(\d+)"` 会**完全匹配不到**，必须写成 `(-?\d+)`。

三种写法都要试，因为不同微信版本用的形式不一样：

```
有符号原值    -1234567890
无符号 32 位   3060399406      (= n + 2**32)
绝对值        1234567890
```

同一份 prefs 里通常 `_auth_uin` / `_auth_uin64` / `default_uin` / `default_uin64` 四个字段同值，可以互相印证。

### imei

Android 10 起微信拿不到真实 IMEI，会退回硬编码常量。按命中概率依次试：

```
1234567890  ->  1234567890ABCDEF  ->  000000000000000  ->  空串
```

另外去 `shared_prefs/WLOGIN_DEVICE_INFO.xml` 找微信自己记的那份。字段名叫 `imei`，  
但值是**十六进制编码的 ASCII**：

```
4142434445464748494a4b4c4d4e4f50   ->   ABCDEFGHIJKLMNOP
```

原始串和解码串都要当候选试。老版本还有 `MicroMsg/<hash>/CompatibleInfo.cfg`，新版基本见不到，当捡漏。

### 读 prefs 的坑：SharedPreferences XML 有两种写法

```xml
<string name="imei" value="ABC" />      
<string name="imei">ABC</string>        
```

微信**两种混用**。只写 `name="..." value="..."` 一个正则会静默漏掉后者 ——  
实测就踩了这个，imei 候选从 5 个掉到 3 个。正确写法：

```python
entry_re = re.compile(
    r'<(?:string|int|long|boolean)\s+name="([^"]*)"\s*'
    r'(?:value="([^"]*)"\s*/?>|>([^<]*)</)', re.I)
```

### 全失败怎么办

```bash
python wxdump_android.py crack --brute
```

7 位十六进制口令空间只有 16^7 ≈ 2.7 亿，而 SQLCipher `compat=1` 只用 4000 轮  
PBKDF2-SHA1，自己写循环（`hashlib.pbkdf2_hmac` + AES-256-CBC 解首页比对  
`b"SQLite format 3\x00"`）多核几十分钟到几小时能跑完。需要 `pycryptodome`。

---

## 解密

SQLCipher 4，AES-256。**`cipher_compatibility = 1` 是关键**，而且必须在 `key` 之后设置：

```python
from sqlcipher3 import dbapi2 as sqlcipher
conn = sqlcipher.connect(enc_db)
conn.execute("PRAGMA cipher_log_level = NONE")   # 否则每次试错都往 stderr 吐 ERROR 噪声
conn.execute(f"PRAGMA key = '{key}'")
conn.execute("PRAGMA cipher_compatibility = 1")
conn.execute(f"ATTACH DATABASE '{plain}' AS plain KEY ''")
conn.execute("SELECT sqlcipher_export('plain')")
conn.execute("DETACH DATABASE plain")
```

纯 SQL 版本（sqlcipher CLI）：

```sql
PRAGMA key = 'xxxxxxx';
PRAGMA cipher_compatibility = 1;
ATTACH DATABASE 'plain.sqlite3' AS db KEY '';
SELECT sqlcipher_export('db');
DETACH DATABASE db;
```

---

## 导出格式

| `--format` | 产物                         | 说明                               |
| ---------- | -------------------------- | -------------------------------- |
| `html`     | `名字.html` + `名字.html.json` | **推荐**。JSON 里有 `is_send`，不用靠猜谁是我 |
| `csv`      | `名字.csv`                   | 留痕 8 列格式，utf-8-sig               |
| `txt`      | `名字.txt`                   | 空行分块，系统消息只有时间行                   |
| `json`     | `名字.json`                  | 带真实时间戳，方便自己调试                    |

每次导出都会额外写一份 `export/<格式>/index.html` 总览（按消息数排序，可点进详情）。

```bash
python wxdump_android.py export --format html
python wxdump_android.py export --format csv --min-msgs 50    # 过滤小会话
python wxdump_android.py export --format json --talker wxid_xxx
```

### HTML 的字段（与留痕对齐）

```jsonc
[{
  "type": "1",              // 字符串化的消息类型
  "type_name": "文本",
  "is_send": false,         // true = 本人发出
  "is_system": false,
  "timestamp": 1700000000,  // 秒级
  "server_id": "123456",
  "sender": "张三",          // 群聊里是具体发言人
  "sender_id": "wxid_xxx",  // 本人消息是 "self"
  "display_name": "张三",
  "avatar_src": "",
  "xml_dict": { "msg": {} },
  "text": "你好"
}]
```

⚠️ **CSV 的「谁是我」是不可靠的**：留痕的 CSV 没有 `is_send` 列，只能靠  
「备注 == 发送人 == 昵称」猜，遇到备注和昵称恰好相同的联系人会误判。  
本工具的 CSV 里，本人行的三列都取 `Me()`，`更多信息` 列写了 `self` / `<对方wxid>` 作为明确标记。  
**要准确区分收发，用 `--format html`。**

---

## 实测记录：message 表解码的坑

下面这些是拿一份真实库（28 万条消息 / 320 个会话）调出来的，  
只看文档想不到，不处理会**静默丢数据或显示错乱**。

| 现象               | 真相                                         | 处理                             |
| ---------------- | ------------------------------------------ | ------------------------------ |
| 时间解析抛 `Errno 22` | `createTime` 是 **13 位毫秒**，不是秒              | `while n > 10**11: n //= 1000` |
| 近 6 万条消息类型显示"其他" | `type` **高 16 位是标志位**，真实类型在低 16 位          | `t & 0xFFFF`                   |
| 群消息发送者错乱         | 群聊前缀的**分隔符随消息类型变化**                        | 见下                             |
| 导出后少了 2286 条     | 8 个联系人昵称都叫 `.`，文件名互相覆盖                     | 重名追加 talker 标识                 |
| 本人昵称取不到          | `userinfo` 表 `id=2` 存的是 **wxid 不是昵称 JSON** | 拿 wxid 回查 `rcontact`           |

### 1. `type` 高 16 位是标志位

| 原始值       | 十六进制         | 低 16 位 | 真实含义 |
| --------- | ------------ | ------ | ---- |
| 285212721 | `0x11000031` | 49     | 分享链接 |
| 822083633 | `0x31000031` | 49     | 引用消息 |
| 268445456 | `0x10002710` | 10000  | 系统消息 |

掩码后分布干净：文本 167090 / 49 类 62793 / 表情 26135 / 图片 12018 /  
系统 4475 / 语音 3886 / 通话 3246。

### 2. 群聊 content 前缀就是发送者，但分隔符随类型变化

```
文本 1 / 49 :  wxid_aaaaaaaaaaaa11:\n正文内容
语音 34     :  wxid_bbbbbbbbbbbb22:4197:0\n         ← 冒号后是时长元数据
视频 43     :  wxid_bbbbbbbbbbbb22:0:0\n
表情 47     :  wxid_cccccccccccc33:0:1:<md5>:<md5>   ← 连换行都没有
企业微信     :  12345678901234567@openim:\n<?xml ...
```

**只认 `:\n` 会漏掉 35,910 条**。正确做法分两档：

```python
SENDER_ID = (r"(?:wxid_[A-Za-z0-9_]{4,}|[0-9]+@(?:openim|chatroom)|gh_[0-9a-f]{8,}"
             r"|newsapp|fmessage|medianote|floatbottle|qmessage|tmessage"
             r"|qqmail|weibo|notifymessage|voiceinputapp)")
STRICT = re.compile(r"^(" + SENDER_ID + r"):\n")     # 所有类型
LOOSE  = re.compile(r"^(" + SENDER_ID + r"):")       # 仅元数据类型
META_TYPES = {3, 34, 43, 47, 62}   # 正文是元数据而非用户文本，可以放心切
```

别用 `^([A-Za-z0-9_@.\-]+):` 这种宽松正则匹配所有类型 —— 会把 `weixin://dl/...`、  
`https://...` 这类正文开头误当发送者切掉。

修复后覆盖率 165,882 / 178,091 = **93%**，剩下 7% 是「自己发的」（群里自己发的不带前缀）

- 系统消息 + 少数无发送者信息的占位消息。

### 3. `isSend` 有 4 种取值

`0` 接收 / `1` 发送 / `2` 系统 / `NULL` 系统。  
实测 `NULL` 只出现在 type 64 和 10000 上，所以  
`isSys = isSend not in (0, 1) or type in (10000, 10002)` 是安全的。

### 4. `type=10002` 的 XML 根节点就是 `<sysmsg>`

不是 `<msg><sysmsg>`，所以 `xml["msg"]["sysmsg"]` 取不到：

```python
sm = root.get("sysmsg") or (root if "@type" in root else {})
```

`sysmsgtemplate > content_template` 里 `<template>` 的 `$xxx$` 占位符，  
要用 `link_list` 里同名 `link` 的 `<title>` 回填：

```
template: 将“某人”添加到备注 $remark_msg_native_url$
link[name=remark_msg_native_url].title: 添加
→ 将“某人”添加到备注 添加
```

未知子类型（如 `reportbizlocation`）兜底：递归找第一个 `text` / `plain` / `content` 节点。

### 5. `type=49` 的 lvbuffer 基本用不上

实测 62,793 条 type=49 里，只有 **12 条**真的需要解 lz4，  
其余 61,828 条虽然带 `lvbuffer`，`content` 却直接就是明文 XML。

判断条件应是 `if t == 49 and "<" not in raw`，别反过来无条件解压。

（真要解的时候，格式是 **4 字节大端长度前缀 + lz4 block**。）

### 6. 其他类型速查

| type    | 内容形态                                                                                                    |
| ------- | ------------------------------------------------------------------------------------------------------- |
| 42 名片   | `<msg nickname="..." username="...">`，取 `@nickname`（`@username` 是 `v3_` 开头的二进制串）                        |
| 50 通话   | 内部串 `voip_content_voice` / `voip_content_video`，或 `<voipmsg><VoIPBubbleMsg><msg><![CDATA[通话时长 00:34]]>` |
| 64 通话   | 纯文本 `XXX发起了语音通话` / `语音通话已经结束`                                                                           |
| 67 企业微信 | `<msg nickname="..." openimdesc="...">`                                                                 |
| 10000   | 纯文本（`"某人" 撤回了一条消息`），少数是 XML                                                                             |

`appmsg.type` 实测分布：5 链接(48080) / 57 引用(8949) / 62 视频号(1204) /  
2000 转账(1115) / 6 文件(543) / 2001 红包(336) / 33 小程序(318) /  
19 合并转发(218) / 4 视频(210) / 53 直播(114) / 51 视频号(68)。

---

## 命令参考

| 命令        | 干什么                                                      |
| --------- | -------------------------------------------------------- |
| *(无参数)*   | 进交互菜单（Windows 双击 `start.bat` 就是它）                        |
| `doctor`  | 环境自检：Python 版本、依赖、adb 路径与版本、已连接设备；缺什么给什么命令              |
| `adb`     | 下载官方 platform-tools 并解压到脚本旁，自动设为本次的 adb                     |
| `probe`   | 查 adb、查 root、列出所有微信账号目录及库大小；root 不可用会打印诊断                |
| `pull`    | 有 root 时直接从 `/data/data/com.tencent.mm/` 拉；`--media` 加附件 |
| `stream`  | 直连推流：建 adb reverse + 监听，等手机端 `wxstream.sh` 推过来           |
| `pull-sd` | 无 root 兜底：从 `/sdcard/wxdump` 拉（`--from` 换路径）             |
| `local`   | 数据已在本地：crack → decrypt → export（跳过一切 adb 环节）             |
| `crack`   | 从 `shared_prefs` 推 uin/imei 并试出口令，命中后写 `dump/key.json`   |
| `decrypt` | 用 `sqlcipher_export` 导出明文库 `EnMicroMsg.plain.db`         |
| `export`  | 按 `--format` 导出到 `dump/export/<格式>/`                     |
| `all`     | 上面全套（probe → pull → crack → decrypt → export）            |

| 选项           | 说明                                     |
| ------------ | -------------------------------------- |
| `--src DIR`  | 工作目录，默认脚本旁的 `dump/`                    |
| `--media`    | `pull` 时连图片/语音/视频一起拉（先检查剩余空间）          |
| `--from DIR` | `pull-sd` 从设备哪个目录拉，默认 `/sdcard/wxdump` |


| `--port N` | `stream` 用哪个端口，默认 9000 |  
| `--timeout N` | `stream` 等待手机连接的秒数，默认 3600 |  
| `--key KEY` | `decrypt` 时直接指定口令，跳过 `key.json` |  
| `--su PATH` | 手动指定 su 路径 |  
| `--format F` | `html` / `csv` / `txt` / `json` |  
| `--talker ID` | 只导指定会话，可重复 |  
| `--min-msgs N` | 少于该条数的会话跳过，默认 2 |  
| `--brute` | `crack` 候选全失败时暴破口令空间 |

---

## 疑难排查

### 装了 root 管理端，但 adb shell 拿不到 root

这两件事是独立的：**装了管理端 ≠ root 生效**，**内核模块活着 ≠ adb shell 能提权**。

```bash
python rootcheck.py
```

判定顺序：

1. `adb shell id` → 是不是 `uid=0`
2. `adb shell which su` / `ls -l /system/bin/su /system/xbin/su /sbin/su /debug_ramdisk/su`
3. `adb shell grep kernelsu /proc/modules` → 模块是否加载（注意：加载了也可能够不到 su）
4. `adb shell ls -ld /data/adb` → **Permission denied 意味着 shell 无法遍历**，  
   于是 `/data/adb/ksu/bin/su`、`/data/adb/ksud` 全部够不到
5. `adb shell pm list packages | grep -iE 'kernelsu|magisk|apatch'` → 只看有没有管理端，  
   **不能**作为 root 生效的证据

**解法**：换一个能向 root 管理端申请授权的终端执行脚本（管理端自带的终端、  
MT 管理器之类的 root 文件管理器，或提权脚本给出的 root shell）。

在 `/data/local/tmp` 造一个同名 `su` 文件触发 sucompat **无效** ——  
新版只匹配 `/system/bin/su`、`/system/xbin/su`、`/sbin/su` 这几个固定路径字符串，  
而这些路径下文件不存在时，shell 在 execve 之前就报 not found 了。

### `crack` 试完所有组合都打不开

1. **拉取时微信还在跑**，WAL 没合并 → 重新 `force-stop` 微信后再拉一次
2. **这是一台换过设备的库**，imei 与当前设备不符
3. **微信改了口令算法** → 用 `crack --brute`

### 只拿到一半消息 / 最新消息缺失

`EnMicroMsg.db-wal` 没一起拷。WAL 里是最近的提交，少了它就丢最近的消息。

### Git Bash 把设备路径改写了

在 Git Bash 里传 `--from /data/local/tmp/e2e` 会被 MSYS 改写成  
`C:/.../PortableGit/.../data/local/tmp/e2e`，导致"目录是空的"这种误报。  
工具里已有 `fix_remote_path()` 自动还原；手动测试时用 `export MSYS_NO_PATHCONV=1`。

### 提示找不到 adb

工具按这个顺序找：`$ADB` 环境变量 → `PATH` → 脚本旁的 `platform-tools/` → 常见安装位置
（`D:\ADB`、`C:\ADB`、Android SDK 默认目录、Homebrew 路径等）。

都不中就跑一次自动下载：

```bash
python wxdump_android.py adb        # 下到脚本旁，本次直接用
python wxdump_android.py doctor     # 再看一遍，应该显示 [ok] adb
```

国内下载慢的话手动下载 zip，解压后把 `platform-tools/` 整个目录放到脚本旁边即可：
<https://developer.android.com/tools/releases/platform-tools>

只用本地已有数据（`crack` / `decrypt` / `export` / `local`）时**完全不需要 adb**。

### 依赖装不上

`sqlcipher3` 需要编译。Windows 上装不动就换预编译包：

```bash
pip install sqlcipher3-binary
```

还是不行就用虚拟环境，避免和系统 Python 打架：

```bash
python -m venv .venv
.venv\Scripts\activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

`lz4` 缺失不影响主流程，只会让少数被压缩的 `type=49` 消息显示成原始内容。

### 不需要手机也能验证链路

```bash
python wxdump_android.py doctor                 # 先看环境齐不齐
python selfcheck.py                             # 造假数据
python wxdump_android.py local --src ./selfcheck_data   # crack -> decrypt -> export
```

`local` 一条命令把后半程跑完；想分步就是 `crack` / `decrypt` / `export --src ./selfcheck_data`。

会造一份假的加密库（口令用 `WLOGIN_DEVICE_INFO.xml` 里十六进制编码的那个 imei），  
然后按 crack / decrypt / export 跑一遍。跑通说明环境没问题，剩下的就只是 adb 权限。

假数据**刻意复刻了真机上才会出现的形态**，所以它同时是一份回归测试：

- `createTime` 是 13 位毫秒
- `type` 高位带标志位（`0x11000031`、`0x31000031`）
- 群聊前缀覆盖四种分隔符（文本 / 语音 / 视频 / 表情）
- `userinfo` 表 `id=2` 存裸 wxid
- `isSend` 有 `NULL`
- `type=49` 既有明文 XML 也有 lz4 压缩的
- `WLOGIN_DEVICE_INFO.xml` 里放十六进制编码的 imei

产物落在 `selfcheck_data/`（已在 `.gitignore` 里），**不会碰你的 `dump/`**。
`selfcheck.py` 还带一道安全阀：目标目录里若出现大于 32 MB 的 `EnMicroMsg*.db`，
它会拒绝删除并退出。

---

## 已知限制

- `adb backup` **无效** —— 微信 `allowBackup="false"`，别浪费时间
- `MicroMsg/` 下可能有多个 32 位 hash 目录（多账号），脚本按 `EnMicroMsg.db` 体积挑最大的
- 附件类消息（图片/语音/视频）在纯 JSON 导出里**没有实体文件**，只能渲染成 `[图片]` 之类占位；  
  需要真实附件请用 `--media` 拉取 `image2/ voice2/ video/ sfs/` 目录
- 微信版本升级可能更换加密策略，工具失效属常态，先小范围验证
- 明文库含全部聊天记录且**无任何加密**，注意保管

---

## 合法边界

本项目只用于**导出你自己设备上、你自己账号的聊天记录**。

请勿用于：

- 破解、窃取他人账号或聊天记录
- 破解商业软件牟利
- 任何违反当地法律法规的用途

使用者需自行承担因使用本工具产生的一切法律责任。  
作者不对任何滥用行为负责。

---

## 致谢

- 格式规范参考 [WeChatMsgArchive / 留痕](https://github.com/CosilC/WeChatMsgArchive)（LC044 / SiYuan，MIT）
- 口令推导思路参考 [PyWxDump](https://github.com/xaoyaoo/PyWxDump) 与 [wechat-dump](https://github.com/ppwwyyxx/wechat-dump)

## License

[MIT](LICENSE)

---

> **留住淌在记忆里的ta，挽住回忆里的我。**
