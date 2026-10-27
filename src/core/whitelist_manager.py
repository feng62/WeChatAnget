# -*- coding: utf-8 -*-
"""
自动回复白名单管理器
支持群聊、联系人的专属白名单配置与状态持久化。
"""

import json
import os
import time
from typing import Dict, Any, List, Optional

from core.path_utils import DATA_DIR, PROJECT_ROOT

ROOT_DIR = PROJECT_ROOT
WHITELIST_PATH = os.path.join(DATA_DIR, "whitelist.json")

DEFAULT_WHITELIST_DATA = {
    "enabled": True,  # 是否开启白名单模式（开启后只有白名单内的对象才自动回复）
    "list": [
        # {"chat_id": "filehelper", "name": "文件传输助手", "is_group": False, "added_at": 1793100000}
    ],
}


class WhitelistManager:
    def __init__(self, file_path: str = WHITELIST_PATH):
        self.file_path = file_path
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        self._ensure_init()

    def _ensure_init(self):
        if not os.path.exists(self.file_path):
            self.save(DEFAULT_WHITELIST_DATA)

    def load(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"[WhitelistManager] 读取白名单失败: {e}", flush=True)
        return dict(DEFAULT_WHITELIST_DATA)

    def save(self, data: Dict[str, Any]) -> bool:
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[WhitelistManager] 保存白名单失败: {e}", flush=True)
            return False

    def is_in_whitelist(self, chat_id: str, name: str = "") -> bool:
        """检查指定 chat_id 或昵称/群名是否在白名单中"""
        data = self.load()
        if not data.get("enabled", True):
            return False

        clean_id = (chat_id or "").strip()
        clean_name = (name or "").strip()

        for item in data.get("list", []):
            item_id = str(item.get("chat_id") or "").strip()
            item_name = str(item.get("name") or "").strip()

            if clean_id and item_id and clean_id == item_id:
                return True
            if clean_name and item_name and clean_name == item_name:
                return True
            if clean_id and item_name and clean_id == item_name:
                return True

        return False

    def add(self, chat_id: str, name: str = "", is_group: bool = False) -> bool:
        """添加对象到白名单"""
        data = self.load()
        items = data.setdefault("list", [])
        clean_id = (chat_id or "").strip()
        clean_name = (name or "").strip() or clean_id

        # 检查是否已存在
        for it in items:
            if (clean_id and it.get("chat_id") == clean_id) or (clean_name and it.get("name") == clean_name):
                it["name"] = clean_name
                it["is_group"] = is_group or clean_id.endswith("@chatroom")
                return self.save(data)

        items.append({
            "chat_id": clean_id,
            "name": clean_name,
            "is_group": is_group or clean_id.endswith("@chatroom"),
            "added_at": int(time.time()),
        })
        return self.save(data)

    def remove(self, chat_id: str) -> bool:
        """从白名单中移除对象"""
        data = self.load()
        items = data.get("list", [])
        clean_id = (chat_id or "").strip()

        new_items = [
            it for it in items
            if str(it.get("chat_id") or "").strip() != clean_id and str(it.get("name") or "").strip() != clean_id
        ]
        data["list"] = new_items
        return self.save(data)

    def get_all(self) -> List[Dict[str, Any]]:
        data = self.load()
        return data.get("list", [])

    def is_enabled(self) -> bool:
        return bool(self.load().get("enabled", True))

    def set_enabled(self, enabled: bool) -> bool:
        data = self.load()
        data["enabled"] = bool(enabled)
        return self.save(data)
