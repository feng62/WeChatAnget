# -*- coding: utf-8 -*-
"""
AI 模型与自动化配置管理模块
参考 whale_gril 设计，支持主流的大语言模型服务商与参数管理。
"""

import json
import os
from typing import Dict, Any

from core.path_utils import DATA_DIR, PROJECT_ROOT

ROOT_DIR = PROJECT_ROOT
CONFIG_PATH = os.path.join(DATA_DIR, "ai_settings.json")

PROVIDER_PRESETS = {
    "deepseek": {
        "name": "DeepSeek (深度求索)",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "qwen": {
        "name": "通义千问 (DashScope / SiliconFlow)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "kimi": {
        "name": "月之暗面 (Moonshot / Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "ollama": {
        "name": "Ollama (本地私有化部署)",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
    },
    "custom": {
        "name": "自定义 OpenAI 兼容接口",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
}

DEFAULT_SETTINGS = {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "",
    "model": "deepseek-chat",
    "temperature": 0.75,
    "max_tokens": 600,
    "auto_reply_global": False,  # 全局自动回复总开关
    "group_at_only": True,       # 群聊仅在被 @ 时自动回复
    "reply_cooldown_sec": 3,     # 两次回复冷却秒数，防刷屏
    "auto_extract_memory": True, # 是否在对话后自动提炼记忆
    "context_messages_count": 15, # 回复时参考最近消息条数 (10~30条)
    "search_before_send": True,   # 发送前是否在微信中 Ctrl+F 搜索并定位目标好友/群聊
    "search_delay_ms": 400,       # 搜索切换到会话后的等待延时 (ms)
    "private_debounce_sec": 3.0,  # 私聊多条消息合并防刷聚合等待时间 (秒)
    "group_debounce_sec": 6.0,    # 群聊多条消息合并防刷聚合等待时间 (秒)
    "multi_bubble_enabled": True, # 是否启用长回复自然切分多条连续气泡发送
    "max_bubbles_count": 2,       # 一次性发送消息的最大条数 (1~5条，默认2条)
    "bubble_send_interval_ms": 800, # 多条消息之间模拟真人打字的停顿间隔 (ms)
}


def load_ai_settings() -> Dict[str, Any]:
    """读取 AI 模型与全局自动化设置"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                settings.update(saved)
        except Exception as e:
            print(f"[AIConfig] 读取设置失败: {e}", flush=True)
    return settings


def save_ai_settings(new_settings: Dict[str, Any]) -> bool:
    """持久化保存 AI 模型与全局设置"""
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        current = load_ai_settings()
        current.update(new_settings)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[AIConfig] 保存设置异常: {e}", flush=True)
        return False
