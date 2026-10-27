# -*- coding: utf-8 -*-
"""
微信消息发送通道 (参考 whale_gril 发送引擎)

功能：
1. 自动定位当前活跃或目标微信号窗口句柄；
2. 剪贴板安全写入与键盘模拟通道（Ctrl+V 注入 + Enter/Ctrl+Enter 发送）；
3. 可选调用 WeChatGUI 进行会话自动切换与安全投递；
4. 发送前后焦点管理与节流防抖。
"""

import ctypes
from ctypes import wintypes
import os
import math
import re
import sys
import time
from typing import Optional, Tuple, List

import win32clipboard
import win32con
import win32gui

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_V = 0x56
VK_F = 0x46
VK_A = 0x41
VK_DELETE = 0x2E
KEYEVENTF_KEYUP = 0x0002

from .ai_config import load_ai_settings
from .db_locator import resolve_db_dir


def split_into_bubbles(text: str, max_bubbles: int = 2) -> List[str]:
    """
    按自然标点与段落将长文本智能切分成 1~N 个独立的气泡短句
    避免一次性回复又臭又长，模拟真人打字交流习惯。
    """
    text = (text or "").strip()
    if not text or max_bubbles <= 1:
        return [text] if text else []

    # 按标点（句号/感叹号/问号/换行）切分，保留标点符号
    raw_parts = re.split(r"([。！？!?~～\n]+)", text)
    sentences = []
    current = ""
    for p in raw_parts:
        if not p:
            continue
        if re.match(r"^[。！？!?~～\n]+$", p):
            current += p.strip("\n")
            if current.strip():
                sentences.append(current.strip())
                current = ""
        else:
            current += p
    if current.strip():
        sentences.append(current.strip())

    if len(sentences) <= max_bubbles:
        return sentences

    chunk_size = math.ceil(len(sentences) / max_bubbles)
    bubbles = []
    for i in range(0, len(sentences), chunk_size):
        bubble = "".join(sentences[i:i + chunk_size]).strip()
        if bubble:
            bubbles.append(bubble)
        if len(bubbles) == max_bubbles - 1:
            rest = "".join(sentences[i + chunk_size:]).strip()
            if rest:
                bubbles.append(rest)
            break
    return bubbles


class MessageSender:
    def __init__(self):
        self.last_send_time = 0.0
        self.last_chat_target = ""

    def find_wechat_window(self) -> Optional[int]:
        """定位当前微信 4.x 主窗口句柄"""
        from examples.window_tracker import WeChatWindowTracker
        tracker = WeChatWindowTracker()
        win = tracker.find_wechat_window()
        return win["hwnd"] if win else None

    def _set_clipboard(self, content: str):
        """安全写入剪贴板"""
        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(content, win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                return True
            except Exception:
                time.sleep(0.05)
        return False

    def _tap_key(self, vk: int, with_ctrl: bool = False):
        """模拟单次键盘敲击"""
        if with_ctrl:
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            time.sleep(0.02)
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.04)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        if with_ctrl:
            time.sleep(0.02)
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    def bring_wechat_to_foreground(self, hwnd: int):
        """
        参考 whale_gril 窗口拉起技术：
        1. 恢复最小化 (SW_RESTORE)；
        2. 敲击 ALT 键解锁 Windows 前台抢占锁；
        3. 调用 SwitchToThisWindow 与 BringWindowToTop 强力拉起微信并锁定焦点。
        """
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, win32con.SW_RESTORE)
            user32.ShowWindow(hwnd, win32con.SW_SHOW)
            time.sleep(0.05)

            # 敲击 VK_MENU (ALT) 解除前台锁
            user32.keybd_event(win32con.VK_MENU, 0, 0, 0)
            time.sleep(0.04)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.08)
            user32.keybd_event(win32con.VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.05)

            try:
                user32.SwitchToThisWindow(hwnd, True)
            except Exception:
                pass
            user32.BringWindowToTop(hwnd)
            time.sleep(0.12)
        except Exception as e:
            print(f"[MessageSender] 拉起微信窗口异常: {e}", flush=True)

    def send_to_chat(
        self,
        text: str,
        target_name: str = "",
        hwnd: Optional[int] = None,
        force_search: bool = False,
    ) -> Tuple[bool, str]:
        """
        向微信目标会话发送消息。
        如果指定了 target_name 且启用了 search_before_send：
        先通过 Ctrl+F 搜索目标好友名/群名 -> 回车打开对应会话 -> 粘贴正文发送。
        如果当前已在对应会话中，则智能跳过搜索直接发送。
        """
        text = (text or "").strip()
        if not text:
            return False, "发送内容不能为空"

        cfg = load_ai_settings()
        search_enabled = cfg.get("search_before_send", True)
        search_delay = float(cfg.get("search_delay_ms", 400)) / 1000.0

        # 节流限制：最少间隔 0.4 秒
        now = time.time()
        if now - self.last_send_time < 0.4:
            time.sleep(0.4)

        target_hwnd = hwnd or self.find_wechat_window()
        if not target_hwnd or not user32.IsWindow(target_hwnd):
            return False, "未能定位到微信主窗口，请确保微信客户端已打开！"

        try:
            # 1. 突破前台锁，把微信挂起唤醒到前台
            self.bring_wechat_to_foreground(target_hwnd)

            # 2. 搜索并定位目标会话（每次必搜，彻底杜绝串聊错乱）
            clean_target = (target_name or "").strip()
            if search_enabled and clean_target:
                print(f"[MessageSender] 正在唤醒微信并执行会话搜索定位: [{clean_target}]", flush=True)

                # ① 调出微信全局搜索 (Ctrl + F)
                self._tap_key(VK_F, with_ctrl=True)
                time.sleep(0.2)

                # ② 全选并清空旧搜索关键词 (Ctrl + A -> Delete)
                self._tap_key(VK_A, with_ctrl=True)
                time.sleep(0.04)
                self._tap_key(VK_DELETE)
                time.sleep(0.06)

                # ③ 粘贴目标联系人或群名称
                self._set_clipboard(clean_target)
                self._tap_key(VK_V, with_ctrl=True)

                # 预留充分的渲染等待时间（默认 0.65 秒，确保微信搜索结果第一项稳定就绪）
                render_wait = max(search_delay, 0.65)
                time.sleep(render_wait)

                # ④ 回车进入搜索结果第一项对应的会话
                self._tap_key(VK_RETURN)
                # 等待会话页面加载完成并将焦点置于输入框
                time.sleep(0.5)

            # 3. 解析是否分气泡多条发送
            multi_enabled = cfg.get("multi_bubble_enabled", True)
            max_bubbles = int(cfg.get("max_bubbles_count", 2))
            bubble_interval = float(cfg.get("bubble_send_interval_ms", 800)) / 1000.0

            if multi_enabled and max_bubbles > 1:
                bubbles = split_into_bubbles(text, max_bubbles=max_bubbles)
            else:
                bubbles = [text]

            if not bubbles:
                bubbles = [text]

            # 4. 循环发送每一条气泡
            for idx, bubble in enumerate(bubbles):
                self._set_clipboard(bubble)
                time.sleep(0.04)
                self._tap_key(VK_V, with_ctrl=True)
                time.sleep(0.08)

                # 模拟按 Enter 发送
                self._tap_key(VK_RETURN)
                time.sleep(0.04)
                self._tap_key(VK_RETURN, with_ctrl=True)

                if idx < len(bubbles) - 1:
                    # 模拟真人输入停顿，稍作等待再发下一句
                    time.sleep(bubble_interval)

            self.last_send_time = time.time()
            if clean_target:
                self.last_chat_target = clean_target

            return True, f"发送成功 ({len(bubbles)}条)"

        except Exception as e:
            return False, f"发送失败: {e}"

    def paste_to_chat(
        self,
        text: str,
        target_name: str = "",
        hwnd: Optional[int] = None,
        force_search: bool = False,
    ) -> Tuple[bool, str]:
        """
        向微信目标会话粘贴文本，但不模拟按 Enter，供用户人工复核与微调后再发送。
        """
        if not hwnd:
            hwnd = self.find_wechat_window()
        if not hwnd:
            return False, "未找到微信主窗口"

        try:
            self.bring_wechat_to_foreground(hwnd)
            cfg = load_ai_settings()
            clean_target = target_name.strip()

            if clean_target and (force_search or cfg.get("search_before_send", True)):
                if clean_target != self.last_chat_target:
                    self._tap_key(VK_F, with_ctrl=True)
                    time.sleep(0.08)
                    self._tap_key(VK_A, with_ctrl=True)
                    time.sleep(0.04)
                    self._tap_key(VK_DELETE)
                    time.sleep(0.04)
                    self._set_clipboard(clean_target)
                    time.sleep(0.04)
                    self._tap_key(VK_V, with_ctrl=True)
                    search_delay = max(0.4, float(cfg.get("search_delay_ms", 400)) / 1000.0 + 0.25)
                    time.sleep(search_delay)
                    self._tap_key(VK_RETURN)
                    time.sleep(0.5)

            self._set_clipboard(text)
            time.sleep(0.05)
            self._tap_key(VK_V, with_ctrl=True)
            self.last_chat_target = clean_target
            return True, "已成功填入微信输入框"
        except Exception as e:
            return False, f"填入失败: {e}"

    def send_to_active_chat(self, text: str, hwnd: Optional[int] = None) -> Tuple[bool, str]:
        """向当前活动聊天框直接发送消息（向下兼容）"""
        return self.send_to_chat(text, target_name="", hwnd=hwnd, force_search=False)
