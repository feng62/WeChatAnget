# -*- coding: utf-8 -*-
"""
微信 4.x 桌面端窗口探测、位置同步与智能吸附引擎

功能特性：
1. 窗口特征多维度自愈探测（类名 Qt51514QWindowIcon / WeChatMainWndForPC、标题「微信」、进程名 Weixin.exe）；
2. 跨桌面沙箱穿透（自动衔接 Default 交互桌面，消除权限隔离）；
3. 严格同步状态：
   - 微信最小化 -> 伴随窗自动隐藏；
   - 微信还原/恢复 -> 伴随窗自动出现；
   - 微信移动/缩放 -> 伴随窗无缝贴紧右侧（毫秒级同步）；
4. 智能边缘防越界：
   - 若微信右侧贴紧屏幕边缘或全屏最大化，伴随窗口自动切换至「贴紧左侧」或「内嵌吸附」，绝不移出屏幕可视区；
5. 一键前台激活与自动贴入（支持模拟 Ctrl+V 填入微信输入框）。
"""

import ctypes
from ctypes import wintypes
import os
import sys
import time
from typing import Dict, Optional, Tuple

import win32con
import win32gui
import win32process

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

# 常量定义
VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002

WX_CLASS_KEYWORDS = ("Qt51514QWindowIcon", "Qt5", "WeChatMainWndForPC")
WX_TITLE_KEYWORDS = ("微信", "WeChat")
WX_PROCESS_NAMES = ("weixin.exe", "wechat.exe")


def ensure_default_desktop():
    """确保当前线程附着在系统的 Default 交互桌面上，避免沙箱与无交互环境无法获取窗口"""
    try:
        h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
    except Exception:
        pass


class WeChatWindowTracker:
    def __init__(self):
        ensure_default_desktop()
        self.cached_hwnd: Optional[int] = None
        self.cached_pid: Optional[int] = None

    def _get_process_name(self, pid: int) -> str:
        if not pid:
            return ""
        h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        except Exception:
            return ""
        finally:
            kernel32.CloseHandle(h)
        return ""

    def find_wechat_window(self) -> Optional[Dict]:
        """
        多维特征匹配微信 4.x 主界面窗口
        返回: {"hwnd": int, "pid": int, "rect": (l,t,r,b), "is_minimized": bool, "is_visible": bool}
        """
        ensure_default_desktop()

        # 1. 优先验证缓存的 HWND 是否依然有效存活
        if self.cached_hwnd and user32.IsWindow(self.cached_hwnd):
            if user32.IsWindowVisible(self.cached_hwnd):
                rect = win32gui.GetWindowRect(self.cached_hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                if w >= 250 and h >= 250:
                    is_minimized = bool(user32.IsIconic(self.cached_hwnd))
                    return {
                        "hwnd": self.cached_hwnd,
                        "pid": self.cached_pid,
                        "rect": rect,
                        "is_minimized": is_minimized,
                        "is_visible": True,
                    }

        # 2. 全局枚举查找有效的主界面
        candidates = []

        def enum_cb(hwnd, _):
            if not user32.IsWindow(hwnd):
                return 1
            is_vis = bool(user32.IsWindowVisible(hwnd))
            # 即使被最小化也可以检测到
            title = win32gui.GetWindowText(hwnd).strip()
            cls = win32gui.GetClassName(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            pname = self._get_process_name(pid)

            if pname in WX_PROCESS_NAMES:
                rect = win32gui.GetWindowRect(hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                is_min = bool(user32.IsIconic(hwnd))

                score = 0
                if any(k in cls for k in WX_CLASS_KEYWORDS):
                    score += 5
                if any(k in title for k in WX_TITLE_KEYWORDS):
                    score += 5
                if w >= 300 and h >= 300:
                    score += 3
                if is_vis or is_min:
                    score += 2

                # 排除小悬浮条/截图辅助窗
                if w < 100 or h < 100:
                    score = 0

                if score >= 7:
                    candidates.append({
                        "hwnd": hwnd,
                        "pid": pid,
                        "title": title,
                        "class": cls,
                        "rect": rect,
                        "is_minimized": is_min,
                        "is_visible": is_vis,
                        "score": score,
                    })
            return 1

        try:
            user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        except Exception:
            pass

        if not candidates:
            self.cached_hwnd = None
            return None

        # 优选评分最高者
        candidates.sort(key=lambda x: x["score"], reverse=True)
        best = candidates[0]
        self.cached_hwnd = best["hwnd"]
        self.cached_pid = best["pid"]
        return best

    def get_monitor_work_area(self, hwnd: int) -> Tuple[int, int, int, int]:
        """获取目标窗口所在屏幕的可用工作区坐标 (去除任务栏，left, top, right, bottom)"""
        try:
            h_mon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                ]
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
                return (
                    mi.rcWork.left,
                    mi.rcWork.top,
                    mi.rcWork.right,
                    mi.rcWork.bottom,
                )
        except Exception:
            pass

        # 默认取主屏幕尺寸
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        return (0, 0, sw, sh)

    def calculate_dock_geometry(
        self,
        wechat_rect: Tuple[int, int, int, int],
        dock_width: int = 340,
        padding: int = 2,
    ) -> Tuple[int, int, int, int, str]:
        """
        计算伴随窗的最佳显示矩形与吸附模式
        返回: (x, y, width, height, dock_mode)
        dock_mode: 'right' (外右侧) | 'left' (外左侧) | 'inside_right' (内嵌右侧)
        """
        wl, wt, wr, wb = wechat_rect
        wh = wb - wt
        target_h = max(300, wh)

        hwnd = self.cached_hwnd or 0
        ml, mt, mr, mb = self.get_monitor_work_area(hwnd)

        # 约束 Y 轴与高度在屏幕可用区内
        target_y = max(mt, min(wt, mb - target_h))
        target_h = min(target_h, mb - target_y)

        # 1. 优先尝试吸附在微信外右侧
        target_x = wr + padding
        if target_x + dock_width <= mr:
            return (target_x, target_y, dock_width, target_h, "right")

        # 2. 如果右侧空间不足（微信贴右侧屏幕边缘），尝试吸附在微信外左侧
        target_x = wl - dock_width - padding
        if target_x >= ml:
            return (target_x, target_y, dock_width, target_h, "left")

        # 3. 如果微信全屏最大化或双侧都超出，则内嵌于微信右侧边缘
        target_x = max(wl, wr - dock_width)
        return (target_x, target_y, dock_width, target_h, "inside_right")

    @staticmethod
    def activate_wechat_and_paste(wechat_hwnd: int, text: str) -> bool:
        """
        将文本注入系统剪贴板，激活微信窗口，并模拟 Ctrl+V 填入微信当前输入框
        """
        if not wechat_hwnd or not user32.IsWindow(wechat_hwnd):
            return False

        try:
            # 1. 设置剪贴板
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
            else:
                import win32clipboard
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()

            # 2. 唤醒并激活微信窗口
            if user32.IsIconic(wechat_hwnd):
                user32.ShowWindow(wechat_hwnd, win32con.SW_RESTORE)
            user32.ShowWindow(wechat_hwnd, win32con.SW_SHOW)
            user32.SetForegroundWindow(wechat_hwnd)
            time.sleep(0.08)

            # 3. 模拟按下 Ctrl+V
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            user32.keybd_event(VK_V, 0, 0, 0)
            time.sleep(0.03)
            user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            return True
        except Exception as e:
            print(f"[WindowTracker] 粘贴到微信失败: {e}", flush=True)
            return False
