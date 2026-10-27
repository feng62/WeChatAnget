# -*- coding: utf-8 -*-
"""
AI 自动托管回复调度引擎
实现全局总控 + 单会话独立托管开关 + 群聊被 @ 回复 + 智能防刷屏节流。
"""

import threading
import time
from typing import Dict, Any, Optional

from .ai_brain import AIBrain
from .ai_config import load_ai_settings
from .message_sender import MessageSender
from .whitelist_manager import WhitelistManager


class AutoReplyEngine:
    def __init__(
        self,
        brain: Optional[AIBrain] = None,
        sender: Optional[MessageSender] = None,
        db_reader: Optional[Any] = None,
        whitelist: Optional[WhitelistManager] = None,
    ):
        self.brain = brain or AIBrain()
        self.sender = sender or MessageSender()
        self.whitelist = whitelist or WhitelistManager()
        self.db_reader = db_reader
        self.last_reply_times: Dict[str, float] = {}
        self.lock = threading.Lock()
        self.broadcast_callback = None

    def set_db_reader(self, reader):
        self.db_reader = reader

    def set_broadcast_callback(self, cb):
        self.broadcast_callback = cb

    def handle_incoming_message(self, msg: Dict[str, Any]):
        """在增量新消息到来时触发的判断与执行逻辑"""
        # 1. 过滤自己发出的消息与系统通知
        if msg.get("is_from_me") or msg.get("direction") == "outgoing":
            return

        chat_id = msg.get("chat_id") or msg.get("username") or ""
        sender_name = msg.get("sender_name") or msg.get("account_name") or "好友"
        raw_text = msg.get("text") or msg.get("content") or ""
        mtype = msg.get("type") or "文本"

        if not chat_id or mtype not in ("文本", "引用消息"):
            return

        # 2. 检查全局设置与白名单 / 单会话托管设置
        cfg = load_ai_settings()
        if not cfg.get("auto_reply_global", False):
            return

        target_chat_name = msg.get("contact_name") or msg.get("chat_name") or sender_name
        session_mem = self.brain.memory.get_session_memory(chat_id)
        in_whitelist = self.whitelist.is_in_whitelist(chat_id, target_chat_name)
        in_session_toggle = bool(session_mem.get("auto_reply", False))

        # 既不在白名单中，也未开启该会话托管，跳过
        if not in_whitelist and not in_session_toggle:
            return

        is_group = chat_id.endswith("@chatroom")
        group_at_only = cfg.get("group_at_only", True)

        # 3. 群聊 @ 判断：
        # 用户需求：白名单内的所有私聊和群聊均自动回复（群聊不需要被 @ 也自动回复）；
        # 仅当未加入白名单但勾选了单会话托管时，才根据 group_at_only 检查 @。
        if is_group and not in_whitelist and group_at_only:
            self_name = msg.get("account_name") or "我"
            if f"@{self_name}" not in raw_text and "@所有人" not in raw_text:
                return

        # 4. 防刷屏与冷却节流
        cooldown = float(cfg.get("reply_cooldown_sec", 3))
        now = time.time()
        with self.lock:
            last_t = self.last_reply_times.get(chat_id, 0.0)
            if now - last_t < cooldown:
                print(f"[AutoReply] 会话 {chat_id} 处于回复冷却期 ({cooldown}s)，暂不处理", flush=True)
                return
            self.last_reply_times[chat_id] = now

        # 5. 异步执行生成与发送
        def _reply_task():
            try:
                # 1. 精准解析会话显示名（优先通过数据库获取群名称或好友备注/昵称，确保搜索词百分之百有效）
                target_chat_name = ""
                if self.db_reader and hasattr(self.db_reader, "get_display_name"):
                    try:
                        target_chat_name = self.db_reader.get_display_name(chat_id)
                    except Exception as ex:
                        print(f"[AutoReply] 数据库解析联系人名称异常: {ex}", flush=True)

                if not target_chat_name or target_chat_name == chat_id:
                    target_chat_name = msg.get("contact_name") or msg.get("chat_name") or sender_name
                if not target_chat_name or target_chat_name == chat_id:
                    session_mem = self.brain.memory.get_session_memory(chat_id)
                    target_chat_name = session_mem.get("title") or sender_name

                # 2. 拉取当前会话最近 10~20 条真实消息作为上下文
                history_msgs = []
                if self.db_reader and hasattr(self.db_reader, "db") and self.db_reader.db:
                    try:
                        context_count = int(cfg.get("context_messages_count", 15))
                        history_msgs = self.db_reader.db.get_messages(chat_id, limit=context_count) or []
                    except Exception as ex:
                        print(f"[AutoReply] 拉取消息上下文失败: {ex}", flush=True)

                print(f"[AutoReply] 开始为会话 [{target_chat_name}] (参考 {len(history_msgs)} 条上下文) 生成智能回复...", flush=True)
                reply = self.brain.generate_chat_reply(
                    chat_id=chat_id,
                    incoming_text=raw_text,
                    sender_name=sender_name,
                    is_group=is_group,
                    history_messages=history_msgs,
                )
                if reply:
                    # 每次回复前：必须强行把微信挂起唤醒到前台 -> Ctrl+F 搜索该好友/群聊名 -> 回车进入 -> 粘贴发送
                    ok, detail = self.sender.send_to_chat(reply, target_name=target_chat_name, force_search=True)
                    log_text = f"[AI托管回复 -> {target_chat_name}]: {reply}" if ok else f"[AI托管发送失败]: {detail}"
                    print(log_text, flush=True)
                    if self.broadcast_callback:
                        self.broadcast_callback({
                            "type": "ai_auto_reply",
                            "chat_id": chat_id,
                            "sender_name": target_chat_name,
                            "reply": reply,
                            "status": "success" if ok else "failed",
                        })
            except Exception as e:
                print(f"[AutoReply] 自动回复执行异常: {e}", flush=True)

        threading.Thread(target=_reply_task, daemon=True).start()
