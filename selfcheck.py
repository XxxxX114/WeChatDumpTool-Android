#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selfcheck.py -- 不需要手机，造一份"假的"微信数据库，验证 crack / decrypt / export 链路。

    python selfcheck.py
    python wxdump_android.py crack   --src ./selfcheck_data
    python wxdump_android.py decrypt --src ./selfcheck_data
    python wxdump_android.py export  --format html --src ./selfcheck_data

造出来的口令 = md5('1234567890ABCDEF' + '1234567890')[:7]
（故意用第二个 imei 回退常量，用来验证候选列表确实会逐个尝试）

假数据刻意复刻了真机上才会出现的形态，所以这个脚本同时是**回归测试**：

  * createTime 是 13 位毫秒，不是秒
  * message.type 高位带标志位（0x11000031 之类）
  * 群聊 content 带发送者前缀，且分隔符随类型变化
  * userinfo 表 id=2 存的是裸 wxid，不是昵称 JSON
  * isSend 有 NULL（系统消息）
  * type=49 既有明文 XML，也有 lz4 压缩的
"""
import hashlib
import os
import shutil
import sqlite3
import sys

import lz4.block

try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError:  # pragma: no cover
    print("[!] 缺少 sqlcipher3，先 pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1)

HERE = os.path.dirname(os.path.abspath(__file__))

# 刻意和真机工作目录 dump/ 分开，避免自检把真实数据删掉
SRC = os.path.join(HERE, "selfcheck_data")

IMEI, UIN = "1234567890ABCDEF", "1234567890"
KEY = hashlib.md5((IMEI + UIN).encode()).hexdigest()[:7]

# 真机时间戳是毫秒
T0 = 1_700_000_000_000

SHARE_XML = (
    "<msg><appmsg appid='' sdkver='0'><title>一篇好文章</title>"
    "<type>5</type><url>https://example.com/a</url></appmsg></msg>"
)
QUOTE_XML = (
    "<msg><appmsg><title>收到</title><type>57</type>"
    "<refermsg><content>原始消息内容</content></refermsg></appmsg></msg>"
)
LOC_XML = "<msg><location x='39.9' y='116.4' label='北京市海淀区' /></msg>"
SYSMSG_XML = (
    "<sysmsg type='sysmsgtemplate'><sysmsgtemplate><content_template "
    "type='tmpl_type_recommend_remark_sys_tip'><plain></plain>"
    "<template><![CDATA[将“小明”添加到备注 $remark_msg_native_url$]]></template>"
    "<link_list><link name='remark_msg_native_url' type='link_recommend_remark_url'>"
    "<title>添加</title></link></link_list>"
    "</content_template></sysmsgtemplate></sysmsg>"
)
VOIP_XML = (
    "<voipmsg type='VoIPBubbleMsg'><VoIPBubbleMsg><msg>"
    "<![CDATA[通话时长 00:34]]></msg></VoIPBubbleMsg></voipmsg>"
)

GROUP = "12345678@chatroom"
FRIEND = "wxid_friend01"
MEMBER = "wxid_member01"

# (msgId, msgSvrId, type, isSend, createTime, talker, content, lvbuffer)
MESSAGES = [
    # ---- 单聊：wxid_friend01 ----
    (1, 1001, 10000, 0, T0 + 0, FRIEND, "你已添加了老王，现在可以开始聊天了", None),
    (2, 1002, 1, 0, T0 + 10_000, FRIEND, "在吗？", None),
    (3, 1003, 1, 1, T0 + 20_000, FRIEND, "在的", None),
    (4, 1004, 3, 0, T0 + 30_000, FRIEND, "", None),
    (5, 1005, 34, 0, T0 + 40_000, FRIEND, "", None),
    # type 高位带标志位：0x11000031 -> 49
    (6, 1006, 0x11000031, 0, T0 + 50_000, FRIEND, SHARE_XML, None),
    # 引用消息：0x31000031 -> 49
    (7, 1007, 0x31000031, 0, T0 + 60_000, FRIEND, QUOTE_XML, None),
    (8, 1008, 48, 0, T0 + 70_000, FRIEND, LOC_XML, None),
    # type=49 但正文被 lz4 压在 lvbuffer 里
    (9, 1009, 49, 0, T0 + 80_000, FRIEND, "", "LZ4_QUOTE"),
    # 系统消息（isSend = NULL）
    (10, 1010, 64, None, T0 + 90_000, FRIEND, "老王发起了语音通话", None),
    (11, 1011, 50, 0, T0 + 100_000, FRIEND, "voip_content_voice", None),
    (12, 1012, 1, 1, T0 + 110_000, FRIEND, "收到，晚点回你", None),

    # ---- 群聊：前缀分隔符随类型变化 ----
    (13, 2001, 1, 0, T0 + 200_000, GROUP, f"{MEMBER}:\n大家好", None),
    (14, 2002, 1, 1, T0 + 210_000, GROUP, "我也在", None),          # 自己发的，无前缀
    (15, 2003, 47, 0, T0 + 220_000, GROUP, f"{MEMBER}:0:1:abc123:def456", None),
    (16, 2004, 34, 0, T0 + 230_000, GROUP, f"{MEMBER}:4197:0\n", None),
    (17, 2005, 43, 0, T0 + 240_000, GROUP, f"{MEMBER}:0:0\n", None),
    (18, 2006, 10000, 0, T0 + 250_000, GROUP, '"小明" 撤回了一条消息', None),
    (19, 2007, 10002, 2, T0 + 260_000, GROUP, SYSMSG_XML, None),
    (20, 2008, 64, 2, T0 + 270_000, GROUP, "语音通话已经结束", None),

    # ---- 另一个会话，用来验证多会话导出 ----
    (21, 3001, 1, 0, T0 + 300_000, "wxid_other", "另一个会话", None),
    (22, 3002, 1, 1, T0 + 310_000, "wxid_other", "嗯", None),
]


def build_plain(path: str) -> None:
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE rcontact (
            username TEXT, alias TEXT, conRemark TEXT, nickname TEXT, type INT);
        CREATE TABLE userinfo (id INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE message (
            msgId INTEGER PRIMARY KEY, msgSvrId INT, type INT, status INT,
            isSend INT, createTime INT, talker TEXT, content TEXT,
            imgPath TEXT, reserved TEXT, lvbuffer BLOB, msgSeq INT);
    """)
    c.executemany("INSERT INTO rcontact VALUES (?,?,?,?,3)", [
        ("wxid_me", "me", "", "我自己"),
        (FRIEND, "laowang", "老王", "隔壁老王"),
        (MEMBER, "", "小明", "小明昵称"),
        (GROUP, "", "", "测试群"),
        ("wxid_other", "", "", "另一个人"),
    ])
    # 真机上 id=2 存的是裸 wxid，不是 JSON
    c.execute("INSERT INTO userinfo VALUES (2, 'wxid_me')")
    c.execute("INSERT INTO userinfo VALUES (4, '我自己')")

    for r in MESSAGES:
        msg_id, svr_id, mtype, is_send, ts, talker, content, _lv = r
        c.execute(
            "INSERT INTO message (msgId,msgSvrId,type,isSend,createTime,talker,content)"
            " VALUES (?,?,?,?,?,?,?)",
            (msg_id, svr_id, mtype, is_send, ts, talker, content),
        )

    # msgId=9：正文在 lvbuffer 里，格式是 4 字节大端长度 + lz4 block
    raw = QUOTE_XML.encode("utf-8")
    blob = len(raw).to_bytes(4, "big") + lz4.block.compress(raw, store_size=False)
    c.execute("UPDATE message SET lvbuffer = ? WHERE msgId = 9", (blob,))
    c.commit()
    c.close()


def guard_against_real_data(path: str) -> None:
    """安全阀：确认要删的目录确实是自检产物，而不是真实数据。"""
    for root, _dirs, files in os.walk(path):
        for fn in files:
            if fn.startswith("EnMicroMsg") and fn.endswith(".db"):
                full = os.path.join(root, fn)
                size = os.path.getsize(full)
                if size > 32 * 1024 * 1024:      # 真机库都是几百 MB 起
                    print(f"[!] {full} 有 {size / 1048576:.0f} MB，看着像真实数据，"
                          f"拒绝删除。请手动确认后再处理。", file=sys.stderr)
                    raise SystemExit(1)


def main() -> None:
    if os.path.isdir(SRC):
        guard_against_real_data(SRC)
        shutil.rmtree(SRC)
    os.makedirs(os.path.join(SRC, "MicroMsg"), exist_ok=True)
    os.makedirs(os.path.join(SRC, "shared_prefs"), exist_ok=True)

    plain = os.path.join(SRC, "plain_tmp.db")
    build_plain(plain)

    enc = os.path.join(SRC, "MicroMsg", "EnMicroMsg.db")
    c = sqlcipher.connect(plain)
    c.execute("PRAGMA cipher_compatibility = 1")
    c.execute(f"ATTACH DATABASE '{enc}' AS enc KEY '{KEY}'")
    # attach 的库不会继承主连接的 compat 设置，必须显式再设一次
    c.execute("PRAGMA enc.cipher_compatibility = 1")
    c.execute("SELECT sqlcipher_export('enc')")
    c.close()
    os.remove(plain)

    with open(os.path.join(SRC, "shared_prefs", "auth_info_key_prefs.xml"), "w",
              encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                '<map>\n'
                '    <boolean name="_auth_uin_initialized" value="true" />\n'
                f'    <int name="_auth_uin" value="{UIN}" />\n'
                f'    <long name="_auth_uin64" value="{UIN}" />\n'
                '</map>\n')

    # 顺便放一份十六进制编码的 imei，验证 WLOGIN_DEVICE_INFO.xml 那条路径
    with open(os.path.join(SRC, "shared_prefs", "WLOGIN_DEVICE_INFO.xml"), "w",
              encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
                '<map>\n'
                '    <string name="imei">' + IMEI.encode().hex() + '</string>\n'
                '</map>\n')

    print(f"[*] 假数据已生成: {SRC}")
    print(f"[*] 数据库口令应为: {KEY}   (imei={IMEI} uin={UIN})")
    print("[*] 接着跑:")
    print(f"      python wxdump_android.py crack   --src {SRC}")
    print(f"      python wxdump_android.py decrypt --src {SRC}")
    print(f"      python wxdump_android.py export  --format html --src {SRC}")


if __name__ == "__main__":
    main()
