# -*- coding: utf-8 -*-
"""
分层记忆管理系统 (参考 whale_gril 记忆架构)

核心架构：
1. 【整体全局记忆】 (Global Memory)
   - 跨所有会话共享的通用知识与背景事实（如我自己的身份、核心习惯、通用备忘）；
   - 存储于 data/memory/global_memory.json。
2. 【单个聊天专属记忆】 (Session Memory)
   - 每个联系人/群聊拥有专属的独立记忆库；
   - 存储联系人画像 (Notes：如对方喜好、常住地、特定约定)、专属自动回复开关、最近 N 轮上下文；
   - 存储于 data/memory/sessions/{safe_chat_id}.json。
3. 【智能记忆提炼与注入】
   - 在生成回复时，将「全局记忆」+「当前联系人专属记忆」+「对话轮次」动态注入 Prompt；
   - 支持后台自动提炼新事实，或在 Web 控制台随时手动增删改查。
"""

import json
import os
import re
import time
from typing import Dict, Any, List, Optional

from core.path_utils import DATA_DIR, PROJECT_ROOT

ROOT_DIR = PROJECT_ROOT
MEMORY_DIR = os.path.join(DATA_DIR, "memory")
GLOBAL_MEMORY_PATH = os.path.join(MEMORY_DIR, "global_memory.json")
SESSIONS_MEMORY_DIR = os.path.join(MEMORY_DIR, "sessions")


def _safe_filename(name: str) -> str:
    """去除文件名中 Windows 非法字符"""
    return re.sub(r'[\\/:*?"<>|]', '_', name)


class MemoryManager:
    def __init__(self):
        os.makedirs(SESSIONS_MEMORY_DIR, exist_ok=True)
        self._ensure_global_memory()

    def _ensure_global_memory(self):
        if not os.path.exists(GLOBAL_MEMORY_PATH):
            default_global = {
                "title": "整体全局共享记忆",
                "updated_at": int(time.time()),
                "facts": [
                    "我的日常工作是自由创作者/独立顾问，平时作息规律。",
                    "我平时热爱探索各种前沿技术、大模型与摄影。",
                    "对朋友真诚友好、沟通讲信用、回复消息讲究高效得体。",
                ],
            }
            try:
                with open(GLOBAL_MEMORY_PATH, "w", encoding="utf-8") as f:
                    json.dump(default_global, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[MemoryManager] 初始化全局记忆异常: {e}", flush=True)

    # ========================== 1. 全局记忆管理 ==========================

    def get_global_memory(self) -> Dict[str, Any]:
        """获取整体全局记忆数据"""
        self._ensure_global_memory()
        try:
            with open(GLOBAL_MEMORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[MemoryManager] 读取全局记忆异常: {e}", flush=True)
            return {"facts": [], "updated_at": 0}

    def update_global_memory(self, facts: List[str]) -> bool:
        """更新整体全局记忆事实列表"""
        clean_facts = [str(f).strip() for f in facts if str(f).strip()]
        data = {
            "title": "整体全局共享记忆",
            "updated_at": int(time.time()),
            "facts": clean_facts,
        }
        try:
            with open(GLOBAL_MEMORY_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[MemoryManager] 保存全局记忆异常: {e}", flush=True)
            return False

    def add_global_fact(self, fact: str) -> bool:
        """追加一条全局事实"""
        fact = fact.strip()
        if not fact:
            return False
        mem = self.get_global_memory()
        facts = mem.get("facts", [])
        if fact not in facts:
            facts.append(fact)
            return self.update_global_memory(facts)
        return True

    def delete_global_fact(self, index: int) -> bool:
        """删除指定索引的全局事实"""
        mem = self.get_global_memory()
        facts = mem.get("facts", [])
        if 0 <= index < len(facts):
            facts.pop(index)
            return self.update_global_memory(facts)
        return False

    # ========================== 2. 会话专属记忆管理 ==========================

    def _get_session_path(self, chat_id: str) -> str:
        safe_id = _safe_filename(chat_id)
        return os.path.join(SESSIONS_MEMORY_DIR, f"{safe_id}.json")

    def get_session_memory(self, chat_id: str, title: str = "") -> Dict[str, Any]:
        """获取指定联系人或群聊的专属记忆"""
        path = self._get_session_path(chat_id)
        default_session = {
            "chat_id": chat_id,
            "title": title or chat_id,
            "auto_reply": False,   # 独立会话自动回复托管开关
            "notes": [],           # 专属记忆事实标签（如偏好、身份、重要约定）
            "history": [],         # 最近对话轮次 [{"role": "user"|"assistant", "text": "...", "time": 123}]
            "updated_at": int(time.time()),
        }
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    default_session.update(data)
                    if title:
                        default_session["title"] = title
                    return default_session
            except Exception as e:
                print(f"[MemoryManager] 读取会话专属记忆异常 ({chat_id}): {e}", flush=True)

        return default_session

    def save_session_memory(self, chat_id: str, data: Dict[str, Any]) -> bool:
        """保存会话专属记忆"""
        path = self._get_session_path(chat_id)
        data["updated_at"] = int(time.time())
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[MemoryManager] 保存会话专属记忆异常 ({chat_id}): {e}", flush=True)
            return False

    def set_session_auto_reply(self, chat_id: str, enabled: bool) -> bool:
        """开启或关闭指定会话的自动托管回复"""
        mem = self.get_session_memory(chat_id)
        mem["auto_reply"] = bool(enabled)
        return self.save_session_memory(chat_id, mem)

    def set_session_debounce(self, chat_id: str, debounce_sec: float) -> bool:
        """设置该会话专属的消息防刷聚合秒数 (0 或负数表示恢复系统默认)"""
        mem = self.get_session_memory(chat_id)
        if debounce_sec > 0:
            mem["debounce_sec"] = round(float(debounce_sec), 1)
        else:
            mem.pop("debounce_sec", None)
        return self.save_session_memory(chat_id, mem)

    def add_session_note(self, chat_id: str, note: str, title: str = "") -> bool:
        """向当前联系人的专属记忆库追加一条事实标签"""
        note = note.strip()
        if not note:
            return False
        mem = self.get_session_memory(chat_id, title)
        notes = mem.get("notes", [])
        if note not in notes:
            notes.append(note)
            mem["notes"] = notes
            return self.save_session_memory(chat_id, mem)
        return True

    def delete_session_note(self, chat_id: str, index: int) -> bool:
        """删除指定联系人的某条记忆事实"""
        mem = self.get_session_memory(chat_id)
        notes = mem.get("notes", [])
        if 0 <= index < len(notes):
            notes.pop(index)
            mem["notes"] = notes
            return self.save_session_memory(chat_id, mem)
        return False

    def record_turn(self, chat_id: str, user_text: str, assistant_text: str, title: str = "", max_turns: int = 20):
        """记录一轮对话历史到会话记忆中"""
        mem = self.get_session_memory(chat_id, title)
        history = mem.get("history", [])
        now = int(time.time())

        if user_text:
            history.append({"role": "user", "text": user_text, "time": now})
        if assistant_text:
            history.append({"role": "assistant", "text": assistant_text, "time": now})

        # 滑动窗口保留最近 max_turns 轮（2 * max_turns 条）
        if len(history) > max_turns * 2:
            history = history[-max_turns * 2:]

        mem["history"] = history
        self.save_session_memory(chat_id, mem)

    # ========================== 3. 记忆上下文组装注入 ==========================

    def build_memory_prompt_block(self, chat_id: str, sender_name: str = "") -> str:
        """
        合成记忆上下文增强块：
        1. 全局记忆（关于我的长期背景事实）；
        2. 当前联系人/会话的专属记忆（对方的画像、喜好、约定）。
        """
        blocks = []

        # 1. 注入整体全局记忆
        global_mem = self.get_global_memory()
        facts = global_mem.get("facts", [])
        if facts:
            facts_text = "\n".join([f"- {f}" for f in facts])
            blocks.append(f"【关于我自身与全局共享记忆】：\n{facts_text}")

        # 2. 注入当前会话的专属记忆
        session_mem = self.get_session_memory(chat_id)
        notes = session_mem.get("notes", [])
        display_target = sender_name or session_mem.get("title") or "当前联系人"
        if notes:
            notes_text = "\n".join([f"- {n}" for n in notes])
            blocks.append(f"【关于「{display_target}」的专属记忆标签】：\n{notes_text}")

        if not blocks:
            return ""

        return "【背景记忆检索已唤醒（请自然融合到对话中，不要刻意照念）：】\n" + "\n\n".join(blocks)
