# -*- coding: utf-8 -*-
"""
微信 4.x 多账号并发消息读取与媒体处理演示程序

【核心能力】：
1. 智能寻址与多账号发现：
   不依赖固定盘符，通过 psutil 进程句柄反射发现微信数据目录及所有正在运行的多开实例。
2. 零注入只读解密与防账号漂移：
   利用内存密钥对每个账号进行安全隔离挂载，杜绝多账号间的密钥覆盖与错乱。
3. 多账号同时并发监听：
   多线程同时轮询各账号的最新消息（sort_seq 增量水位），实时接收并格式化控制台输出。
4. 深度媒体处理：
   图片（wxgf 转 JPEG，长图自适应切片）、语音（Silk 解码 WAV）、链接卡片（XML 提取）、表情包防刷屏。

【运行方式】：
直接运行：python demo_read_messages.py
离线模拟：python demo_read_messages.py --mock
"""

import argparse
import io
import json
import os
import socket
import sys
import time
from datetime import datetime

# Windows 终端中文编码与 emoji 兼容处理
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 将当前目录加入模块检索路径
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from core.db_locator import resolve_db_dir
from core.db_reader import MultiAccountListenerManager, WeChatDatabaseReader, MessageIncrementalListener


def load_config() -> dict:
    cfg_file = os.path.join(PROJECT_ROOT, "config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def format_print_message(msg: dict):
    """在控制台优雅打印多账号捕获到的增量消息"""
    t_str = datetime.fromtimestamp(msg.get("create_time") or time.time()).strftime("%H:%M:%S")
    acct_badge = f"\033[33m[账号: {msg.get('account_name') or '微信'}]\033[0m"
    direction_badge = "\033[36m[发出]\033[0m" if msg.get("is_from_me") else "\033[32m[收到]\033[0m"
    chat_type_badge = "[群聊]" if msg.get("chat_type") == "group" else "[私聊]"
    chat_title = msg.get("chat_title") or msg.get("chat_id") or "未知会话"
    sender = msg.get("sender_name") or "未知发送者"
    mtype = msg.get("msg_type") or "文本"

    color_map = {
        "文本": "\033[32m",     # 绿色
        "图片": "\033[35m",     # 紫色
        "语音": "\033[36m",     # 青色
        "链接卡片": "\033[34m", # 蓝色
        "表情包": "\033[33m",   # 黄色
    }
    reset_color = "\033[0m"
    theme_color = color_map.get(mtype, "\033[37m")

    print("\n" + "─" * 75, flush=True)
    if msg.get("is_from_me"):
        header = f"[{t_str}] {acct_badge} {direction_badge} {chat_type_badge} 发给 -> 【{chat_title}】"
    else:
        header = f"[{t_str}] {acct_badge} {direction_badge} {chat_type_badge} 【{chat_title}】 | 发送人: {sender}"
    print(header, flush=True)

    print(f"消息类型: {theme_color}【{mtype}】{reset_color}", flush=True)
    print(f"消息正文: {msg.get('text')}", flush=True)

    # 如果存在媒体详细信息，打印出来
    if msg.get("media"):
        m = msg["media"]
        if m["type"] == "image":
            print(f"  -> [图片路径]: {m.get('local_path')}", flush=True)
            print(f"  -> [规格参数]: 格式={m.get('ext')} | 大小={m.get('size_kb')} KB | 视觉切片数={m.get('slice_count')}", flush=True)
        elif m["type"] == "voice":
            print(f"  -> [转码音频]: {m.get('wav_path')} (时长: {m.get('seconds')}s)", flush=True)
        elif m["type"] == "card":
            print(f"  -> [卡片标题]: {m.get('title')}", flush=True)
            print(f"  -> [链接网址]: {m.get('url')}", flush=True)
    print("─" * 75, flush=True)


def run_mock_demo():
    """未登录微信时的功能模拟演示"""
    print("\n[Mock 模式] 演示消息解析与多媒体转码流程...", flush=True)
    from core.media_processor import MediaProcessor

    processor = MediaProcessor(media_cache_dir=os.path.join(PROJECT_ROOT, "media-cache"))

    # 1. 模拟文本消息
    mock_text_msg = {
        "account_name": "测试主号",
        "account_wxid": "wxid_main_001",
        "direction": "incoming",
        "is_from_me": False,
        "chat_id": "12345678@chatroom",
        "chat_title": "研发沟通大群",
        "chat_type": "group",
        "sender_name": "张工",
        "msg_type": "文本",
        "text": "大家测试一下微信 4.x 多开同时监听功能",
        "media": None,
        "create_time": time.time(),
    }
    format_print_message(mock_text_msg)

    # 2. 模拟分享卡片消息
    xml_content = """
    <msg><appmsg>
      <title>深入理解微信 4.x 架构与数据库解密原理</title>
      <url>https://mp.weixin.qq.com/s/sample_article_id</url>
    </appmsg></msg>
    """
    card = processor.parse_xml_card(xml_content)
    if card:
        mock_card_msg = {
            "account_name": "测试小号",
            "account_wxid": "wxid_sub_002",
            "direction": "incoming",
            "is_from_me": False,
            "chat_id": "wxid_friend_001",
            "chat_title": "架构师李工",
            "chat_type": "private",
            "sender_name": "架构师李工",
            "msg_type": "链接卡片",
            "text": card["summary"],
            "media": {"type": "card", **card},
            "create_time": time.time(),
        }
        format_print_message(mock_card_msg)

    # 3. 模拟长截图切片
    print("\n[模拟生成长截图并测试自适应切片算法]...", flush=True)
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (800, 2400), color=(245, 245, 245))
        draw = ImageDraw.Draw(img)
        draw.text((50, 100), "长截图第 1 段内容 (顶部)", fill=(0, 0, 0))
        draw.text((50, 1200), "长截图第 2 段内容 (中间)", fill=(200, 0, 0))
        draw.text((50, 2200), "长截图第 3 段内容 (底部)", fill=(0, 0, 200))

        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        raw_bytes = buf.getvalue()

        clean_bytes, ext, slices = processor.process_image(raw_bytes)
        mock_img_msg = {
            "account_name": "测试主号",
            "account_wxid": "wxid_main_001",
            "direction": "incoming",
            "is_from_me": False,
            "chat_id": "12345678@chatroom",
            "chat_title": "测试微信群",
            "chat_type": "group",
            "sender_name": "王五",
            "msg_type": "图片",
            "text": f"[图片] (格式: {ext}, 大小: {len(raw_bytes)//1024}KB, 包含 {len(slices)} 个切片)",
            "media": {
                "type": "image",
                "local_path": "memory://mock_screenshot.jpg",
                "ext": ext,
                "size_kb": len(raw_bytes) // 1024,
                "slice_count": len(slices),
            },
            "create_time": time.time(),
        }
        format_print_message(mock_img_msg)
        print(f"  ✓ 成功将 800x2400 长图按 overlap 重叠机制切为 {len(slices)} 个子图切片！", flush=True)
    except Exception as e:
        print(f"  [Mock] PIL 测试提示: {e}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="微信 4.x 多账号并发消息增量监听与多媒体处理")
    parser.add_argument("--mock", action="store_true", help="以模拟数据模式运行演示")
    parser.add_argument("--ignore-self", action="store_true", help="忽略自己发送的消息，仅监听接收的消息")
    args = parser.parse_args()

    print("=" * 75, flush=True)
    print("  微信 4.x 多账号并发消息读取核心引擎 (SQLite增量只读解密与媒体处理)", flush=True)
    print("=" * 75, flush=True)

    if args.mock:
        run_mock_demo()
        return

    # 单实例端口互斥锁：避免多开终端重复运行争抢 SQLite 锁
    lock_sock = None
    try:
        lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lock_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        lock_sock.bind(("127.0.0.1", 47835))
        lock_sock.listen(1)
    except OSError:
        print("\n[!] 警告：已经有一个消息监听器正在运行（端口 47835 被占用）！", flush=True)
        print("    请关闭其他已打开的 cmd / bat 终端窗口，避免多进程并发访问数据库产生冲突。", flush=True)
        return

    cfg = load_config()
    db_dir = cfg.get("dbDir") or ""
    poll_interval = float(cfg.get("pollInterval", 0.4))
    ignore_self = args.ignore_self or bool(cfg.get("ignoreSelf", False))

    print("\n[步骤 1/3] 扫描微信 4.x 数据根目录与登录进程...", flush=True)
    found_db = resolve_db_dir(db_dir, verbose=True)
    if not found_db:
        print("\n[!] 未能自动找到微信数据库目录。", flush=True)
        print("    1. 请确认微信 4.x 桌面端是否已经登录；", flush=True)
        print("    2. 或在 config.json 中的 dbDir 显式配置目录。", flush=True)
        print("\n提示：可输入 --mock 查看离线逻辑演示: python demo_read_messages.py --mock", flush=True)
        sys.exit(1)

    print("\n[步骤 2/3] 自动发现并挂载所有已登录账号的 SQLite 数据库...", flush=True)
    manager = MultiAccountListenerManager(
        db_dir=found_db,
        poll_interval=poll_interval,
        ignore_self=ignore_self,
        media_cache_dir=cfg.get("mediaCacheDir", "media-cache"),
    )

    try:
        accounts = manager.discover_and_mount()
    except Exception as e:
        print(f"\n[!] 挂载微信账号数据库失败: {e}", flush=True)
        sys.exit(1)

    print(f"\n[成功发现并接入 {len(accounts)} 个微信账号]:", flush=True)
    for idx, item in enumerate(accounts, 1):
        pid_str = f"PID: {item['pid']}" if item.get("pid") else "未绑定PID"
        print(f"  [{idx}] 昵称: 【{item['name']}】 (wxid: {item['wxid']}) | {pid_str} | 挂载密钥数: {item['keys_count']} [就绪]", flush=True)

    print("\n[步骤 3/3] 启动所有账号的增量轮询监听引擎 (interval=0.4s)...", flush=True)
    manager.on_message(format_print_message)
    manager.start()

    print("\n" + "=" * 75, flush=True)
    print(" >>> 实时监听中！现在可以在手机微信或电脑端任意账号中收发消息进行测试。", flush=True)
    print(f" >>> 当前已支持同时监听这 {len(accounts)} 个账号，收到的所有消息将实时显示在下方。", flush=True)
    print(" >>> 按 Ctrl + C 可安全停止监听。", flush=True)
    print("=" * 75, flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n收到退出指令，正在平滑关闭所有账号监听器...", flush=True)
        manager.stop()
        if lock_sock:
            try:
                lock_sock.close()
            except Exception:
                pass
        print("退出完成。", flush=True)


if __name__ == "__main__":
    main()
