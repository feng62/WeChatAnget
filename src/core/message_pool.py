# -*- coding: utf-8 -*-
"""
AI 托管消息池与聚合防刷调度引擎
核心能力：
1. 串行消息池队列 (FIFO)：一个人一个人排队回复，一个完成再回复下一个，杜绝前台窗口焦点抢占错乱；
2. 动态防刷聚合 (Debounce)：群聊/私聊多人连续发言时，合并在聚合窗口期内（默认私聊3秒、群聊6秒，支持单群单独配置），仅回复一次；
3. 多条连续气泡发送：结合标点自然切分 1~N 条，模拟真人打字节奏。
"""

import queue
import threading
import time
from typing import Dict, Any, List, Optional, Callable

from .ai_brain import AIBrain
from .ai_config import load_ai_settings
from .message_sender import MessageSender
from .whitelist_manager import WhitelistManager


class MessagePoolEngine:
    def __init__(
        self,
        brain: Optional[AIBrain] = None,
        sender: Optional[MessageSender] = None,
        whitelist: Optional[WhitelistManager] = None,
        db_reader: Optional[Any] = None,
    ):
        self.brain = brain or AIBrain()
        self.sender = sender or MessageSender()
        self.whitelist = whitelist or WhitelistManager()
        self.db_reader = db_reader

        self.broadcast_callback: Optional[Callable] = None
        self.last_reply_times: Dict[str, float] = {}

        # 待处理会话聚合桶：chat_id -> {"timer": Timer, "messages": [...], "meta": dict}
        self.pending_buckets: Dict[str, Dict[str, Any]] = {}
        self.bucket_lock = threading.Lock()

        # 串行回复队列：严格一人一人依次执行
        self.reply_queue = queue.Queue()

        # 启动后台单工作者消费线程
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="AI-Reply-Worker")
        self.worker_thread.start()

    def set_db_reader(self, reader):
        self.db_reader = reader

    def set_broadcast_callback(self, cb: Callable):
        self.broadcast_callback = cb

    def handle_incoming_message(self, msg: Dict[str, Any]):
        """在增量新消息到来时触发的过滤与入池聚合逻辑"""
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

        # 3. 群聊 @ 判断（若在白名单中，按用户要求无需 @ 即可回复；若不在白名单仅开单聊托管，则按设置判断）
        if is_group and not in_whitelist and group_at_only:
            self_name = msg.get("account_name") or "我"
            if f"@{self_name}" not in raw_text and "@所有人" not in raw_text:
                return

        # 4. 计算该会话专属性或默认的聚合等待秒数 (默认私聊 3秒、群聊 6秒，可单独配置)
        custom_debounce = session_mem.get("debounce_sec")
        if isinstance(custom_debounce, (int, float)) and custom_debounce > 0:
            debounce_sec = float(custom_debounce)
        else:
            if is_group:
                debounce_sec = float(cfg.get("group_debounce_sec", 6.0))
            else:
                debounce_sec = float(cfg.get("private_debounce_sec", 3.0))

        # 5. 会话多条消息聚合防刷机制 (Debounce Buffer)
        with self.bucket_lock:
            bucket = self.pending_buckets.get(chat_id)
            if bucket:
                # 已有该群/该好友正在聚合等待，取消之前的定时器，追加当前新发言
                old_timer: threading.Timer = bucket.get("timer")
                if old_timer:
                    old_timer.cancel()
                bucket["messages"].append(msg)
                print(f"[MessagePool] 会话 [{target_chat_name}] 收到连发消息(共 {len(bucket['messages'])} 条)，重置等待定时器 ({debounce_sec}s)...", flush=True)
            else:
                # 开启全新聚合桶
                bucket = {
                    "chat_id": chat_id,
                    "target_name": target_chat_name,
                    "is_group": is_group,
                    "messages": [msg],
                    "debounce_sec": debounce_sec,
                }
                self.pending_buckets[chat_id] = bucket

            # 启动/重启防抖定时器，时间到后才打包送入执行队列
            new_timer = threading.Timer(debounce_sec, self._on_debounce_complete, args=[chat_id])
            bucket["timer"] = new_timer
            new_timer.start()

    def _on_debounce_complete(self, chat_id: str):
        """当会话静默期结束，把整包消息推入串行回复队列"""
        with self.bucket_lock:
            bucket = self.pending_buckets.pop(chat_id, None)

        if not bucket or not bucket.get("messages"):
            return

        print(f"[MessagePool] 会话 [{bucket['target_name']}] 聚合完成（合并 {len(bucket['messages'])} 条消息），推入串行处理队列排队...", flush=True)
        self.reply_queue.put(bucket)

    def _worker_loop(self):
        """单工作者消费循环：严格一个人一个人回复，完成一个再进行下一个"""
        while True:
            try:
                task = self.reply_queue.get()
                if task is None:
                    break
                self._process_single_reply_task(task)
            except Exception as e:
                print(f"[MessagePool] 工作线程执行异常: {e}", flush=True)
            finally:
                self.reply_queue.task_done()

    def _process_single_reply_task(self, task: Dict[str, Any]):
        """处理单个会话的完整生成与发送流程"""
        chat_id = task["chat_id"]
        target_name = task.get("target_name") or chat_id
        is_group = task.get("is_group", False)
        msgs = task.get("messages", [])
        if not msgs:
            return

        cfg = load_ai_settings()

        # 1. 冷却校验（两次回复之间必须间隔 cooldown 秒）
        cooldown = float(cfg.get("reply_cooldown_sec", 3.0))
        now = time.time()
        last_t = self.last_reply_times.get(chat_id, 0.0)
        if now - last_t < cooldown:
            time.sleep(cooldown - (now - last_t))

        # 2. 组装多条聚合消息内容（若是群聊多人发，拼成清晰的多人对话摘要）
        if len(msgs) == 1:
            combined_text = msgs[0].get("text") or msgs[0].get("content") or ""
            last_sender = msgs[0].get("sender_name") or "对方"
        else:
            lines = []
            for m in msgs:
                s_name = m.get("sender_name") or ("群友" if is_group else "对方")
                content = m.get("text") or m.get("content") or ""
                lines.append(f"{s_name}: {content}")
            combined_text = "\n".join(lines)
            last_sender = msgs[-1].get("sender_name") or "群友"

        # 3. 精准解析联系人真实名称 (供 Ctrl+F 搜索定位)
        real_search_target = ""
        if self.db_reader and hasattr(self.db_reader, "get_display_name"):
            try:
                real_search_target = self.db_reader.get_display_name(chat_id)
            except Exception:
                pass
        if not real_search_target or real_search_target == chat_id:
            real_search_target = target_name

        # 4. 拉取历史真实数据库记录
        history_msgs = []
        if self.db_reader and hasattr(self.db_reader, "db") and self.db_reader.db:
            try:
                context_count = int(cfg.get("context_messages_count", 15))
                history_msgs = self.db_reader.db.get_messages(chat_id, limit=context_count) or []
            except Exception as ex:
                print(f"[MessagePool] 读取上下文失败: {ex}", flush=True)

        print(f"[MessagePool 正在回复] [{real_search_target}] (收到 {len(msgs)} 条聚合发言, 参考 {len(history_msgs)} 条上下文)...", flush=True)

        # 5. 大模型综合生成回复
        reply = self.brain.generate_chat_reply(
            chat_id=chat_id,
            incoming_text=combined_text,
            sender_name=last_sender,
            is_group=is_group,
            history_messages=history_msgs,
        )

        if not reply:
            print(f"[MessagePool] 未生成有效回复，跳过发送", flush=True)
            return

        # 6. 挂起微信 -> 搜索定位 -> 按多气泡分条发送
        ok, detail = self.sender.send_to_chat(reply, target_name=real_search_target, force_search=True)
        self.last_reply_times[chat_id] = time.time()

        log_text = f"[AI串行回复成功 -> {real_search_target}]: {reply} ({detail})" if ok else f"[AI回复失败 -> {real_search_target}]: {detail}"
        print(log_text, flush=True)

        if self.broadcast_callback:
            try:
                self.broadcast_callback({
                    "type": "ai_auto_reply",
                    "chat_id": chat_id,
                    "sender_name": real_search_target,
                    "reply": reply,
                    "status": "success" if ok else "failed",
                    "detail": detail,
                })
            except Exception as e:
                print(f"[MessagePool] 广播回调异常: {e}", flush=True)
