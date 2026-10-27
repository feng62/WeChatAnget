# -*- coding: utf-8 -*-
"""
微信 4.x 消息读取、媒体处理与 AI 自动托管核心包
"""
from .db_locator import resolve_db_dir, looks_like_db_root
from .media_processor import MediaProcessor
from .db_reader import WeChatDatabaseReader, MessageIncrementalListener, MultiAccountListenerManager
from .ai_config import load_ai_settings, save_ai_settings
from .persona_manager import load_persona, save_persona, build_system_prompt
from .memory_manager import MemoryManager
from .ai_brain import AIBrain
from .message_sender import MessageSender
from .whitelist_manager import WhitelistManager
from .message_pool import MessagePoolEngine

__all__ = [
    "resolve_db_dir",
    "looks_like_db_root",
    "MediaProcessor",
    "WeChatDatabaseReader",
    "MessageIncrementalListener",
    "MultiAccountListenerManager",
    "load_ai_settings",
    "save_ai_settings",
    "load_persona",
    "save_persona",
    "build_system_prompt",
    "MemoryManager",
    "AIBrain",
    "MessageSender",
    "WhitelistManager",
    "MessagePoolEngine",
]
