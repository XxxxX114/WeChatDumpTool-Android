# 引流素材库

> **留住淌在记忆里的ta，挽住回忆里的我。**

这个文件不是给使用者看的文档，是给作者（你）**复制粘贴用**的推广素材。
下面每一条都可以原样发出去，只需要把 `<仓库链接>` 换成实际地址。

---

## 0. GitHub 仓库设置（先填这几项，别人搜得到）

**Description**（仓库简介，建议 ≤120 字符）

```
从已 root 的 Android 手机导出微信聊天记录：推流拉取 → 推导口令 → 解密 SQLCipher → 导出 HTML/CSV/TXT/JSON。双击即用。
```

**Topics**（标签，直接影响 GitHub 站内搜索）

```
wechat  wechat-export  chat-history  sqlcipher  android  adb  root  forensics  memo-trace  python
```

**Website**：有博客/公众号就填，没有留空。

---

## 1. 一句话版（签名档 / 评论区 / 短回复）

> 留住淌在记忆里的ta，挽住回忆里的我。

备选：

- 把手机里那几年的聊天记录，完整搬到电脑上。
- 微信聊天记录导出：从手机到能翻的 HTML，一条命令。
- 28 万条真实数据实测跑通的开源微信导出工具。

---

## 2. 短文案（QQ 群 / 微信群 / 朋友圈）

```
【开源】Android 微信聊天记录导出工具

把手机里的聊天记录完整搬到电脑，导出成能直接翻的 HTML——
文字、图片、语音、视频、表情、引用、链接全都在，不是那种只导出纯文本的。

· 手机端 tar 流经 adb reverse 直推电脑，不在手机存储上留任何东西
· 口令自动推导，负数 uin、十六进制编码的 imei 这些坑都处理了
· 四种格式：HTML / CSV / TXT / JSON，字段和「留痕」对齐，能直接喂下游工具
· Windows 双击 start.bat 就能用，不用记命令；找不到 adb 它会自己下

需要 root（或者手机上有个能读 /data/data 的文件管理器也行，有无 root 兜底路线）。
仅限自己的设备和自己的账号。

<仓库链接>

留住淌在记忆里的ta，挽住回忆里的我。
```

---

## 3. 中文档（贴吧 / 酷安 / 知乎回答 / V2EX）

```
微信的聊天记录一直没法正经导出，官方的「迁移与备份」只能在微信生态里搬来搬去，
拿到手的还是一堆加密库。市面上几个工具要么停更，要么只覆盖 PC 端微信。

这个项目解决的是 Android 端：从手机里把 SQLCipher 加密的 EnMicroMsg.db 拿出来、
推导出口令、解密、导出成能直接看的格式。

和同类工具比，它多做了几件事：

【拉取】三条路线，按你的 root 情况挑
  · stream —— 手机端 tar 流经 adb reverse 直连电脑，不落手机存储（推荐）
  · pull   —— adb shell 能拿到 root 时直接拉
  · pull-sd —— 完全没有 root，用有 root 权限的文件管理器先拷到 /sdcard 再拉

【口令】这一步最容易卡住，所以下了功夫
  · uin 是 32 位有符号整数，账号大了就是负数，正则写 (\d+) 会完全匹配不到
  · imei 在 WLOGIN_DEVICE_INFO.xml 里是十六进制编码的 ASCII
  · SharedPreferences 的 XML 有两种写法（值在属性里 / 值在标签体里），微信两种混用
  · 全部候选都失败还能 --brute 暴破 7 位十六进制空间

【导出】四种格式，HTML 可以直接翻
  · 群聊消息的发送者前缀有四种分隔符（文本 / 语音 / 视频 / 表情各不同），都处理了
  · 消息 type 的高 16 位是标志位，不掩码的话近 6 万条会变成「未知类型」
  · createTime 是 13 位毫秒，不是秒
  · 联系人昵称重名会覆盖文件，实测有 8 个联系人昵称都叫「.」

【可验证】不需要手机就能自检
  · selfcheck.py 会造一份假的加密库，把解密到导出整条链路跑一遍
  · 假数据刻意复刻了真机上才会出现的形态，所以它同时是回归测试

【一键】Windows 双击 start.bat 进菜单，自动找 Python、检查依赖、定位 adb
  · 找不到 adb 可以直接在菜单里下（官方 platform-tools，自动解压到脚本旁）

README 里有一整节「实测记录：message 表解码的坑」，都是真机上踩出来的，
就算你不用这个工具，只做微信数据解析也能拿去参考。

需要 root。仅限自己的设备和自己的账号。

<仓库链接>

留住淌在记忆里的ta，挽住回忆里的我。
```

---

## 4. 长文（博客 / 公众号 / 知乎专栏）

**标题备选**

- 《我把手机里 28 万条微信聊天记录导出来了》
- 《微信聊天记录怎么导出？从 root 到 HTML 的完整路径》
- 《写完这个工具后，我才知道微信的 message 表有多坑》
- 《留住淌在记忆里的ta，挽住回忆里的我》

**结构建议**

1. **开头**：为什么想导出聊天记录（情绪切入，别一上来讲技术）
   一个具体的人、一段具体的时间，比「备份数据」这种理由有力得多。
2. **官方路径为什么走不通**
   迁移与备份只在微信生态内搬，adb backup 早就失效（`allowBackup="false"`）。
3. **真正可行的路线**
   讲 root 直读 / 推流直连 / sdcard 中转三条路，配上各自的适用场景。
4. **技术上最有意思的坑**（这一段是涨粉主力，写细节）
   - type 高 16 位标志位
   - 群聊发送者前缀的四种分隔符
   - 负数 uin + 十六进制 imei
   - 重名文件覆盖掉 2286 条消息
5. **成品长什么样**
   index.html 总览 + 每个会话的 HTML，截图打码。
6. **开源地址 + 免责声明**

结尾落回那句：

> 留住淌在记忆里的ta，挽住回忆里的我。

---

## 5. English（Reddit / Hacker News / X）

```
[Open Source] Export WeChat chat history from a rooted Android phone

WeChat has no official export. The data sits in a SQLCipher-encrypted
EnMicroMsg.db inside /data/data/com.tencent.mm/, and most existing tools
only cover the PC client.

This one covers Android:
- three pull routes (adb-reverse streaming / direct root pull / no-root
  sdcard relay)
- automatic passphrase derivation (handles negative uin, hex-encoded imei,
  and both SharedPreferences XML shapes)
- export to HTML / CSV / TXT / JSON, field-aligned with MemoTrace
- a self-check that builds a fake encrypted DB so the whole pipeline can be
  verified without a phone (it doubles as a regression test)
- one-click launcher on Windows with automatic adb discovery

The README has a section on the message-table decoding pitfalls we hit on
real data — useful even if you only do WeChat data parsing.

Requires root. For your own device and your own account only.

<repo link>

留住淌在记忆里的ta，挽住回忆里的我。
```

---

## 6. 话题标签

```
#微信 #聊天记录 #数据导出 #开源 #Python #Android #SQLCipher #逆向
#wechat #sqlcipher #android #opensource #python #forensics
```

中文平台用前一组，英文平台用后一组，别混着堆。

---

## 7. 配图建议（三张就够）

| 图 | 内容 | 注意 |
|---|---|---|
| 1 | 终端跑 `stream` 的截图，接收进度条 + `1.2 GB` | 把工作目录路径打码 |
| 2 | `export/html/index.html` 总览页截图 | **群名/联系人名必须打码**，这是最容易漏的 |
| 3 | 某个会话的 HTML 截图，展示图片/语音/引用都渲染出来了 | 同样打码 |

截图前先拿一份自检数据（`python selfcheck.py`）跑一遍，用假数据出图最省事。

---

## 8. 发布渠道与时机

| 渠道 | 适合的版本 | 备注 |
|---|---|---|
| 酷安 | 中文档 | 安卓用户密度最高，工具类内容反馈最好 |
| V2EX（分享创造节点） | 中文档 | 认技术细节，把「坑」那节写足 |
| 知乎 | 长文 | 回答「微信聊天记录怎么导出」这类问题，比发文章流量大 |
| 贴吧（安卓吧 / 微信吧） | 短文案 | 容易被删，标题别太像广告 |
| GitHub Trending | 靠 Topics + Star 增长 | 首周冲一下 star 有机会上榜 |
| Reddit r/androidapps、r/DataHoarder | English | 注意子版规则，别硬广 |
| X / 微博 | 一句话版 + 配图 | 配图比文字重要 |

节奏建议：先发酷安 + V2EX 试水，看反馈改一版文案，再铺知乎和英文渠道。
同一天全平台群发容易被当成营销号。

---

## 9. 红线（务必别踩）

- **不接「代导别人聊天记录」的活**，不管对方说得多合理
- **不卖数据、不卖解密服务**，这个项目只面向「自己的设备和自己的账号」
- 截图里的群名、联系人昵称、wxid、手机号**一律打码**，包括文件树里的
- 别在文案里承诺「不需要 root」—— 需要 root 是事实，写清楚反而更可信
- 别把「留痕 / MemoTrace」写成自己的项目，致谢要留着

---

> 留住淌在记忆里的ta，挽住回忆里的我。
