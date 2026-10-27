# -*- coding: utf-8 -*-
"""
微信 4.x 桌面 AI 副驾驶 - 贴边伴随助手 (PyQt6 + Win32 零延迟硬件级吸附)

核心特性：
1. 丝滑吸附：基于 Windows Event Hook (EVENT_OBJECT_LOCATIONCHANGE) 纳秒级响应，
   彻底解决高频 QTimer 轮询导致的拖拽卡顿、掉帧与画面撕裂；
2. 状态全同步：微信最小化 -> 伴随窗自动隐身；微信恢复/移动 -> 瞬时贴合右侧；
3. 智能防越界：右侧贴边或全屏时自动切至左侧或内嵌吸附；
4. 共享 Web 端大脑与配置：直接复用 src.core (AI 配置、记忆库、人设 System Prompt、消息池)；
5. 可搜索会话下拉框：支持按好友/群聊拼音汉字实时模糊搜索过滤会话；
6. 3 种微信口吻 AI 建议卡片（得体、幽默、精炼），支持「一键发送」、「填入微信」与「复制」；
7. 遵循微信 4.x 原生设计语言（WeChat Light Theme + Emerald #07c160 强调色）；
8. WebSocket 全双工实时同步：实时感知微信新消息推送并自动触发生成。
"""

import asyncio
import ctypes
from ctypes import wintypes
import json
import os
import sys
import threading
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import requests
import websockets
import win32con
import win32gui
import win32process

from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QIcon,
    QKeyEvent,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# 确保当前路径与项目根路径加入 sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.ai_brain import AIBrain
from core.ai_config import load_ai_settings
from core.memory_manager import MemoryManager
from core.message_sender import MessageSender
from core.path_utils import CONFIG_PATH, DATA_DIR, PROJECT_ROOT
from core.persona_manager import build_system_prompt, load_persona

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)

# Win32 常量
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
WINEVENT_OUTOFCONTEXT = 0x0000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080
SWP_NOSENDCHANGING = 0x0200

WX_CLASS_KEYWORDS = ("Qt51514QWindowIcon", "Qt5", "WeChatMainWndForPC")
WX_TITLE_KEYWORDS = ("微信", "WeChat")
WX_PROCESS_NAMES = ("weixin.exe", "wechat.exe")


def ensure_default_desktop():
    """附着在系统的 Default 交互桌面，消除权限隔离"""
    try:
        h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
    except Exception:
        pass


class SmoothDockTracker(QObject):
    """
    高精度窗口探测与吸附计算器
    使用 SetWinEventHook 在 Windows 消息泵级捕获位置变动，彻底告别轮询掉帧
    """

    locationChanged = pyqtSignal(int, int, int, int, str)
    visibilityChanged = pyqtSignal(bool)
    wechatFound = pyqtSignal(int, int)

    def __init__(self, dock_width: int = 356, parent=None):
        super().__init__(parent)
        ensure_default_desktop()
        self.dock_width = dock_width
        self.wechat_hwnd: Optional[int] = None
        self.wechat_pid: Optional[int] = None
        self.hook: Optional[int] = None
        self.cb_ref: Optional[WINEVENTPROC] = None
        self.last_rect: Optional[Tuple[int, int, int, int]] = None
        self.is_minimized: bool = False

    def get_process_name(self, pid: int) -> str:
        if not pid:
            return ""
        h = kernel32.OpenProcess(0x1000, False, pid)
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
        ensure_default_desktop()

        # 1. 验证现有缓存
        if self.wechat_hwnd and user32.IsWindow(self.wechat_hwnd):
            if user32.IsWindowVisible(self.wechat_hwnd):
                rect = win32gui.GetWindowRect(self.wechat_hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                if w >= 250 and h >= 250:
                    is_min = bool(user32.IsIconic(self.wechat_hwnd))
                    return {
                        "hwnd": self.wechat_hwnd,
                        "pid": self.wechat_pid,
                        "rect": rect,
                        "is_minimized": is_min,
                    }

        # 2. 全局枚举
        candidates = []

        def enum_cb(hwnd, _):
            if not user32.IsWindow(hwnd):
                return 1
            is_vis = bool(user32.IsWindowVisible(hwnd))
            is_min = bool(user32.IsIconic(hwnd))
            if not is_vis and not is_min:
                return 1

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            pname = self.get_process_name(pid)
            if pname in WX_PROCESS_NAMES:
                title = win32gui.GetWindowText(hwnd).strip()
                cls = win32gui.GetClassName(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]

                score = 0
                if any(k in cls for k in WX_CLASS_KEYWORDS):
                    score += 5
                if any(k in title for k in WX_TITLE_KEYWORDS):
                    score += 5
                if w >= 300 and h >= 300:
                    score += 3
                if is_vis:
                    score += 2
                if w < 120 or h < 120:
                    score = 0

                if score >= 7:
                    candidates.append({
                        "hwnd": hwnd,
                        "pid": pid,
                        "title": title,
                        "class": cls,
                        "rect": rect,
                        "is_minimized": is_min,
                        "score": score,
                    })
            return 1

        try:
            user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        except Exception:
            pass

        if not candidates:
            return None

        candidates.sort(key=lambda x: x["score"], reverse=True)
        best = candidates[0]
        self.wechat_hwnd = best["hwnd"]
        self.wechat_pid = best["pid"]
        return best

    def get_monitor_work_area(self, hwnd: int) -> Tuple[int, int, int, int]:
        try:
            h_mon = user32.MonitorFromWindow(hwnd, 2)

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
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        return (0, 0, sw, sh)

    def calculate_dock_geometry(
        self,
        wechat_rect: Tuple[int, int, int, int],
        padding: int = 2,
    ) -> Tuple[int, int, int, int, str]:
        wl, wt, wr, wb = wechat_rect
        wh = wb - wt
        target_h = max(300, wh)

        hwnd = self.wechat_hwnd or 0
        ml, mt, mr, mb = self.get_monitor_work_area(hwnd)

        target_y = max(mt, min(wt, mb - target_h))
        target_h = min(target_h, mb - target_y)

        # 1. 右侧吸附
        target_x = wr + padding
        if target_x + self.dock_width <= mr:
            return (target_x, target_y, self.dock_width, target_h, "right")

        # 2. 左侧吸附
        target_x = wl - self.dock_width - padding
        if target_x >= ml:
            return (target_x, target_y, self.dock_width, target_h, "left")

        # 3. 内嵌右侧
        target_x = max(wl, wr - self.dock_width)
        return (target_x, target_y, self.dock_width, target_h, "inside_right")

    def start_hook(self):
        """安装系统事件监听钩子"""
        if self.hook:
            return

        def _event_proc(h_hook, event, hwnd, id_obj, id_child, thread, time_ms):
            if id_obj != 0:  # OBJID_WINDOW
                return
            if not self.wechat_hwnd or hwnd != self.wechat_hwnd:
                return

            if event == EVENT_SYSTEM_MINIMIZESTART:
                self.is_minimized = True
                self.visibilityChanged.emit(False)
                return
            elif event == EVENT_SYSTEM_MINIMIZEEND:
                self.is_minimized = False
                self.visibilityChanged.emit(True)

            if event == EVENT_OBJECT_LOCATIONCHANGE:
                is_min = bool(user32.IsIconic(hwnd))
                if is_min != self.is_minimized:
                    self.is_minimized = is_min
                    self.visibilityChanged.emit(not is_min)
                    if is_min:
                        return

                if not is_min and user32.IsWindowVisible(hwnd):
                    rect = win32gui.GetWindowRect(hwnd)
                    x, y, w, h, mode = self.calculate_dock_geometry(rect)
                    self.last_rect = (x, y, w, h)
                    self.locationChanged.emit(x, y, w, h, mode)

        self.cb_ref = WINEVENTPROC(_event_proc)
        pid = self.wechat_pid or 0
        self.hook = user32.SetWinEventHook(
            EVENT_OBJECT_LOCATIONCHANGE,
            EVENT_OBJECT_LOCATIONCHANGE,
            None,
            self.cb_ref,
            pid,
            0,
            WINEVENT_OUTOFCONTEXT,
        )

    def stop_hook(self):
        if self.hook:
            try:
                user32.UnhookWinEvent(self.hook)
            except Exception:
                pass
            self.hook = None


class WebSocketListenerBridge(QObject):
    """后台 WebSocket 监听器，与 Web 控制台保持全双工长连 (daemon 线程，退出绝不阻塞)"""

    newMessageReceived = pyqtSignal(dict)
    connectionStatusChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.is_running = False

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._listen())
        except Exception:
            pass
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _listen(self):
        uri = "ws://127.0.0.1:8000/ws"
        while self.is_running:
            try:
                async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
                    self.connectionStatusChanged.emit(True)
                    while self.is_running:
                        msg_str = await ws.recv()
                        try:
                            pkt = json.loads(msg_str)
                            if pkt.get("type") == "new_message":
                                self.newMessageReceived.emit(pkt.get("data", {}))
                        except Exception:
                            pass
            except Exception:
                self.connectionStatusChanged.emit(False)
                for _ in range(25):
                    if not self.is_running:
                        return
                    await asyncio.sleep(0.1)


class AISuggestionWorker(QThread):
    """
    后台大模型建议生成线程
    复用 src.core (AI 配置、人设、记忆)，一次生成 3 种微信日常回复风格
    """

    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        context_msgs: List[Dict],
        chat_id: str,
        chat_title: str,
        custom_instruction: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.context_msgs = context_msgs
        self.chat_id = chat_id
        self.chat_title = chat_title
        self.custom_instruction = custom_instruction.strip()

    def run(self):
        try:
            cfg = load_ai_settings()
            persona = load_persona()
            api_key = (cfg.get("api_key") or "").strip()
            base_url = (cfg.get("base_url") or "https://api.deepseek.com/v1").rstrip("/")
            model = cfg.get("model") or "deepseek-chat"
            max_words = persona.get("max_words", 100)

            # 获取该会话的记忆事实画像
            mem_mgr = MemoryManager()
            global_facts = mem_mgr.get_global_memory().get("facts", [])
            session_notes = mem_mgr.get_session_memory(self.chat_id).get("notes", [])

            # 整理最近对话上下文
            dialogue_text = ""
            for m in self.context_msgs[-12:]:
                speaker = "我" if m.get("is_from_me") else (m.get("sender_name") or self.chat_title or "对方")
                dialogue_text += f"{speaker}: {m.get('content', '')}\n"

            if not dialogue_text.strip():
                dialogue_text = f"对方: 你好"

            # 离线模拟兜底（无 API KEY 时）
            if not api_key:
                results = self._generate_offline_mock(dialogue_text)
                self.finished.emit(results)
                return

            system_prompt = f"""你是「{persona.get('name', '小暖')}」，正在微信上与好友聊天。
请根据上下文，给出 3 种不同风格的回复建议：
1. 【得体礼貌】自然温暖、得体周全、态度诚恳；
2. 【风趣幽默】高情商、轻松俏皮、适合熟络好友互动；
3. 【精简高效】直奔主题、言简意赅（适合忙碌或快速确认）。

【已知记忆事实】：
- 全局常识: {', '.join(global_facts[:3]) if global_facts else '无'}
- 对方画像: {', '.join(session_notes[:3]) if session_notes else '无'}

【回复格式要求】：
请务必严格输出 3 行，每行格式如下（不要有其他寒暄说明）：
[得体] 回复内容（单句限{max_words}字内）
[幽默] 回复内容（单句限{max_words}字内）
[精简] 回复内容（单句限{max_words}字内）"""

            user_prompt = f"【当前联系人】: {self.chat_title}\n【近期对话记录】:\n{dialogue_text}"
            if self.custom_instruction:
                user_prompt += f"\n【我的额外回复意图/要求】: {self.custom_instruction}"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": float(cfg.get("temperature", 0.7)),
                "max_tokens": int(cfg.get("max_tokens", 500)),
            }

            resp = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=18,
            )

            if resp.status_code != 200:
                raise RuntimeError(f"API 请求失败 HTTP {resp.status_code}: {resp.text}")

            res_json = resp.json()
            content = res_json["choices"][0]["message"]["content"].strip()
            results = self._parse_suggestions(content)
            self.finished.emit(results)

        except Exception as e:
            self.failed.emit(str(e))

    def _parse_suggestions(self, text: str) -> List[Dict]:
        items = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("[得体]") or line.startswith("【得体】"):
                items.append({"style": "得体礼貌", "tag": "得体", "text": line[4:].strip()})
            elif line.startswith("[幽默]") or line.startswith("【幽默】"):
                items.append({"style": "风趣幽默", "tag": "幽默", "text": line[4:].strip()})
            elif line.startswith("[精简]") or line.startswith("【精简】"):
                items.append({"style": "精简高效", "tag": "精简", "text": line[4:].strip()})

        if not items:
            items.append({"style": "综合建议", "tag": "建议", "text": text})
        return items

    def _generate_offline_mock(self, dialogue: str) -> List[Dict]:
        return [
            {"style": "得体礼貌", "tag": "得体", "text": "好嘞，我收到啦！这会儿稍微有点忙，稍等我倒杯水马上详细回复你哈~"},
            {"style": "风趣幽默", "tag": "幽默", "text": "哈哈哈哈笑死我了，听你这么一说我突然精神了，快坐下细细唠唠！"},
            {"style": "精简高效", "tag": "精简", "text": "明白，没问题，马上安排！"},
        ]


class SuggestionCard(QFrame):
    """单条回复建议卡片 (微信设计语言)"""

    sendRequested = pyqtSignal(str)
    pasteRequested = pyqtSignal(str)
    copyRequested = pyqtSignal(str)

    def __init__(self, tag: str, style_name: str, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self.setObjectName("suggestionCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # 头部标签栏
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        tag_badge = QLabel(style_name)
        tag_badge.setObjectName("styleBadge")
        header_row.addWidget(tag_badge)
        header_row.addStretch()

        layout.addLayout(header_row)

        # 建议文本
        content_lbl = QLabel(text)
        content_lbl.setWordWrap(True)
        content_lbl.setObjectName("cardContent")
        layout.addWidget(content_lbl)

        # 操作按钮工具栏
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.setSpacing(6)
        btn_row.addStretch()

        self.copy_btn = QPushButton("复制")
        self.copy_btn.setObjectName("btnGhost")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(lambda: self.copyRequested.emit(self.text))

        self.paste_btn = QPushButton("填入微信")
        self.paste_btn.setObjectName("btnGhost")
        self.paste_btn.setToolTip("填入微信输入框，供人工修改核对")
        self.paste_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.paste_btn.clicked.connect(lambda: self.pasteRequested.emit(self.text))

        self.send_btn = QPushButton("一键发送")
        self.send_btn.setObjectName("btnPrimary")
        self.send_btn.setToolTip("自动置顶微信并执行多气泡模拟发送")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(lambda: self.sendRequested.emit(self.text))

        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.paste_btn)
        btn_row.addWidget(self.send_btn)
        layout.addLayout(btn_row)


class WeChatCopilotDock(QWidget):
    """
    微信 4.x 桌面副驾驶主窗口
    """

    def __init__(self):
        super().__init__()
        self.dock_width = 356
        self.is_pinned = True
        self.current_session: Optional[Dict] = None
        self.sessions_cache: List[Dict] = []
        self.recent_messages: List[Dict] = []

        self.sender = MessageSender()
        self.tracker = SmoothDockTracker(dock_width=self.dock_width, parent=self)

        self.init_window_flags()
        self.init_ui()
        self.init_styles()
        self.init_signals()

        # 启动窗口寻址与毫秒级吸附
        self.bootstrap_tracker()

        # 初始加载会话
        QTimer.singleShot(500, self.refresh_sessions_list)

        # 启动 WebSocket 实时长连
        self.ws_bridge = WebSocketListenerBridge(self)
        self.ws_bridge.newMessageReceived.connect(self.on_ws_message_received)
        self.ws_bridge.connectionStatusChanged.connect(self.on_ws_status_changed)
        self.ws_bridge.start()

    def init_window_flags(self):
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
        )
        if self.is_pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(self.dock_width, 680)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. 顶部 Header (微信浅灰原生质感)
        header = QFrame()
        header.setObjectName("headerFrame")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 10, 10)
        header_layout.setSpacing(8)

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDot")

        self.title_lbl = QLabel("微信 AI 副驾驶")
        self.title_lbl.setObjectName("appTitle")

        self.backend_badge = QLabel("本地模式")
        self.backend_badge.setObjectName("backendBadge")

        header_layout.addWidget(self.status_dot)
        header_layout.addWidget(self.title_lbl)
        header_layout.addWidget(self.backend_badge)
        header_layout.addStretch()

        self.pin_btn = QPushButton("📌")
        self.pin_btn.setObjectName("btnIcon")
        self.pin_btn.setToolTip("切换窗口置顶状态")
        self.pin_btn.clicked.connect(self.toggle_pin)

        self.web_btn = QPushButton("🌐")
        self.web_btn.setObjectName("btnIcon")
        self.web_btn.setToolTip("打开 Web 控制台 (http://127.0.0.1:8000)")
        self.web_btn.clicked.connect(self.open_web_console)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("btnIcon")
        self.close_btn.setToolTip("最小化隐藏伴随窗口")
        self.close_btn.clicked.connect(self.hide)

        header_layout.addWidget(self.pin_btn)
        header_layout.addWidget(self.web_btn)
        header_layout.addWidget(self.close_btn)
        main_layout.addWidget(header)

        # 2. 会话下拉搜索选择栏 (Searchable Session Combobox)
        search_card = QFrame()
        search_card.setObjectName("searchCard")
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(12, 10, 12, 8)
        search_layout.setSpacing(6)

        search_header = QHBoxLayout()
        lbl_hint = QLabel("选择/搜索对话窗口:")
        lbl_hint.setObjectName("secLabel")

        self.auto_toggle = QCheckBox("收到新消息自动建议")
        self.auto_toggle.setChecked(True)
        self.auto_toggle.setObjectName("customCheck")

        search_header.addWidget(lbl_hint)
        search_header.addStretch()
        search_header.addWidget(self.auto_toggle)
        search_layout.addLayout(search_header)

        # 搜索与切换下拉框 (集成 QCompleter 模糊匹配)
        self.session_combo = QComboBox()
        self.session_combo.setObjectName("sessionCombo")
        self.session_combo.setEditable(True)
        self.session_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.session_combo.lineEdit().setPlaceholderText("🔍 输入拼音、好友名或群聊名过滤...")

        # 配置实时模糊搜索 Completer
        comp = self.session_combo.completer()
        if comp:
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

        self.session_combo.currentIndexChanged.connect(self.on_session_selected)
        search_layout.addWidget(self.session_combo)

        main_layout.addWidget(search_card)

        # 3. 当前对话上文卡片
        context_card = QFrame()
        context_card.setObjectName("contextCard")
        ctx_layout = QVBoxLayout(context_card)
        ctx_layout.setContentsMargins(12, 8, 12, 8)
        ctx_layout.setSpacing(4)

        ctx_top = QHBoxLayout()
        self.target_name_lbl = QLabel("未选定会话")
        self.target_name_lbl.setObjectName("targetNameLbl")

        self.msg_count_lbl = QLabel("参考近 15 条记录")
        self.msg_count_lbl.setObjectName("msgCountLbl")

        ctx_top.addWidget(self.target_name_lbl)
        ctx_top.addStretch()
        ctx_top.addWidget(self.msg_count_lbl)
        ctx_layout.addLayout(ctx_top)

        self.last_msg_box = QLabel("暂无消息记录")
        self.last_msg_box.setObjectName("lastMsgBox")
        self.last_msg_box.setWordWrap(True)
        ctx_layout.addWidget(self.last_msg_box)

        main_layout.addWidget(context_card)

        # 4. 建议卡片滚动展示区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("cardsScroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(12, 8, 12, 8)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch()

        scroll.setWidget(self.cards_container)
        main_layout.addWidget(scroll, 1)

        # 5. 底部输入与重新生成区 (微信输入工具栏风)
        bottom_bar = QFrame()
        bottom_bar.setObjectName("bottomBar")
        bot_layout = QVBoxLayout(bottom_bar)
        bot_layout.setContentsMargins(12, 8, 12, 10)
        bot_layout.setSpacing(8)

        self.instruct_input = QLineEdit()
        self.instruct_input.setObjectName("instructInput")
        self.instruct_input.setPlaceholderText("微调回复要求（如：婉拒对方、约明天下午...）")
        self.instruct_input.returnPressed.connect(self.trigger_generation)
        bot_layout.addWidget(self.instruct_input)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 刷新会话")
        self.refresh_btn.setObjectName("btnGhost")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_sessions_list)

        self.gen_btn = QPushButton("✨ 生成回复建议")
        self.gen_btn.setObjectName("btnPrimary")
        self.gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gen_btn.clicked.connect(self.trigger_generation)

        btn_row.addWidget(self.refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.gen_btn)
        bot_layout.addLayout(btn_row)

        main_layout.addWidget(bottom_bar)

    def init_styles(self):
        self.setStyleSheet("""
            QWidget {
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                background-color: #f7f7f7;
                color: #222222;
            }
            #headerFrame {
                background-color: #f0f0f0;
                border-bottom: 1px solid #e5e5e5;
            }
            #statusDot {
                color: #07c160;
                font-size: 13px;
            }
            #appTitle {
                font-size: 13px;
                font-weight: 600;
                color: #1a1a1a;
            }
            #backendBadge {
                font-size: 9px;
                color: #07c160;
                background-color: #e8f7ee;
                border: 1px solid #c8ebd4;
                border-radius: 3px;
                padding: 1px 4px;
            }
            #btnIcon {
                background: transparent;
                border: none;
                color: #777777;
                font-size: 12px;
                padding: 4px 6px;
                border-radius: 4px;
            }
            #btnIcon:hover {
                background-color: #e5e5e5;
                color: #111111;
            }
            #searchCard {
                background-color: #ffffff;
                border-bottom: 1px solid #ededed;
            }
            #secLabel {
                font-size: 11px;
                font-weight: 600;
                color: #666666;
            }
            #customCheck {
                font-size: 11px;
                color: #555555;
            }
            #sessionCombo {
                background-color: #f3f3f3;
                border: 1px solid #e2e2e2;
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 12px;
                color: #222222;
            }
            #sessionCombo:focus {
                background-color: #ffffff;
                border-color: #07c160;
            }
            #sessionCombo::drop-down {
                border: none;
                width: 20px;
            }
            #contextCard {
                background-color: #fafafa;
                border-bottom: 1px solid #e8e8e8;
            }
            #targetNameLbl {
                font-size: 12px;
                font-weight: bold;
                color: #1a1a1a;
            }
            #msgCountLbl {
                font-size: 10px;
                color: #999999;
            }
            #lastMsgBox {
                background-color: #ffffff;
                border: 1px solid #e4e4e4;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 11px;
                line-height: 1.4;
                color: #333333;
            }
            #cardsScroll {
                background-color: #f7f7f7;
                border: none;
            }
            #suggestionCard {
                background-color: #ffffff;
                border: 1px solid #e6e6e6;
                border-radius: 8px;
            }
            #suggestionCard:hover {
                border-color: #c9e8d4;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
            }
            #styleBadge {
                font-size: 10px;
                font-weight: 600;
                color: #07c160;
                background-color: #edf9f2;
                padding: 1px 6px;
                border-radius: 3px;
            }
            #cardContent {
                font-size: 12px;
                line-height: 1.5;
                color: #262626;
                padding: 2px 0;
            }
            #btnPrimary {
                background-color: #07c160;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            #btnPrimary:hover {
                background-color: #06ad56;
            }
            #btnPrimary:pressed {
                background-color: #059b4c;
            }
            #btnGhost {
                background-color: #f2f2f2;
                color: #444444;
                border: 1px solid #d9d9d9;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            #btnGhost:hover {
                background-color: #e8e8e8;
                color: #222222;
            }
            #bottomBar {
                background-color: #ffffff;
                border-top: 1px solid #e5e5e5;
            }
            #instructInput {
                background-color: #f5f5f5;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                color: #222222;
            }
            #instructInput:focus {
                background-color: #ffffff;
                border-color: #07c160;
            }
        """)

    def init_signals(self):
        self.tracker.locationChanged.connect(self.on_dock_location_changed)
        self.tracker.visibilityChanged.connect(self.on_dock_visibility_changed)

    def bootstrap_tracker(self):
        win = self.tracker.find_wechat_window()
        if win:
            self.status_dot.setStyleSheet("color: #07c160;")
            self.title_lbl.setText(f"微信 AI 副驾驶 (PID: {win['pid']})")
            rect = win["rect"]
            x, y, w, h, mode = self.tracker.calculate_dock_geometry(rect)
            self.apply_geometry_smooth(x, y, w, h)
            self.show()
            self.tracker.start_hook()
        else:
            self.status_dot.setStyleSheet("color: #999999;")
            self.title_lbl.setText("微信 AI 副驾驶 (等待微信...)")

        # 定时自愈心跳（120ms 检查微信是否重新启动或句柄更迭）
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self.on_heartbeat)
        self.heartbeat_timer.start(120)

    def on_heartbeat(self):
        if not self.tracker.wechat_hwnd or not user32.IsWindow(self.tracker.wechat_hwnd):
            win = self.tracker.find_wechat_window()
            if win:
                self.tracker.stop_hook()
                self.tracker.start_hook()
                self.status_dot.setStyleSheet("color: #07c160;")
                self.title_lbl.setText(f"微信 AI 副驾驶 (PID: {win['pid']})")
                rect = win["rect"]
                x, y, w, h, mode = self.tracker.calculate_dock_geometry(rect)
                self.apply_geometry_smooth(x, y, w, h)
                self.show()
            else:
                self.status_dot.setStyleSheet("color: #999999;")
                self.title_lbl.setText("微信 AI 副驾驶 (等待微信...)")
                if self.isVisible():
                    self.hide()
        else:
            # 检查最小化
            is_min = bool(user32.IsIconic(self.tracker.wechat_hwnd))
            if is_min and self.isVisible():
                self.hide()
            elif not is_min and not self.isVisible() and user32.IsWindowVisible(self.tracker.wechat_hwnd):
                rect = win32gui.GetWindowRect(self.tracker.wechat_hwnd)
                x, y, w, h, mode = self.tracker.calculate_dock_geometry(rect)
                self.apply_geometry_smooth(x, y, w, h)
                self.show()

    def on_dock_location_changed(self, x: int, y: int, w: int, h: int, mode: str):
        """位置改变时调用硬件级 SetWindowPos 零延迟吸附"""
        self.apply_geometry_smooth(x, y, w, h)

    def on_dock_visibility_changed(self, visible: bool):
        if visible:
            if not self.isVisible():
                self.show()
        else:
            if self.isVisible():
                self.hide()

    def apply_geometry_smooth(self, x: int, y: int, w: int, h: int):
        hwnd = int(self.winId())
        curr = self.geometry()
        flags = SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOSENDCHANGING

        # 如果宽高一致则不重设尺寸，加速 DWM 绘制
        if curr.width() == w and curr.height() == h:
            flags |= SWP_NOSIZE

        user32.SetWindowPos(hwnd, 0, x, y, w, h, flags)

    def toggle_pin(self):
        self.is_pinned = not self.is_pinned
        self.init_window_flags()
        self.pin_btn.setText("📌" if self.is_pinned else "📍")
        self.show()

    def open_web_console(self):
        import webbrowser
        webbrowser.open("http://127.0.0.1:8000")

    def on_ws_status_changed(self, connected: bool):
        if connected:
            self.backend_badge.setText("Web已联通")
            self.backend_badge.setStyleSheet("color: #07c160; background-color: #e8f7ee; border: 1px solid #c8ebd4;")
        else:
            self.backend_badge.setText("本地离线")
            self.backend_badge.setStyleSheet("color: #888888; background-color: #eeeeee; border: 1px solid #dddddd;")

    def on_ws_message_received(self, msg: Dict):
        """收到 WebSocket 推送的微信新消息"""
        chat_id = msg.get("chat_id") or msg.get("username")
        if not chat_id:
            return

        # 若为当前选定会话
        if self.current_session and self.current_session.get("username") == chat_id:
            spk = "我" if msg.get("is_from_me") else (msg.get("sender_name") or "对方")
            self.last_msg_box.setText(f"{spk}: {msg.get('content', '...')}")
            self.recent_messages.append(msg)
            if self.auto_toggle.isChecked() and not msg.get("is_from_me"):
                self.trigger_generation()
        else:
            # 更新下拉项显示
            for i in range(self.session_combo.count()):
                d = self.session_combo.itemData(i)
                if d and d.get("username") == chat_id:
                    title = d.get("title") or chat_id
                    prefix = "👥 " if d.get("is_group") else "👤 "
                    self.session_combo.setItemText(i, f"{prefix}{title} (新)")
                    break

    def refresh_sessions_list(self):
        """优先从运行中的 Web 服务拉取会话列表，离线时直接读本地数据"""
        try:
            resp = requests.get("http://127.0.0.1:8000/api/sessions", timeout=1.0)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                self.populate_sessions(data)
                return
        except Exception:
            pass

        # 离线模拟/缓存会话
        mock_sessions = [
            {"username": "filehelper", "title": "文件传输助手", "is_group": False, "latest_msg": "欢迎使用微信 AI 对话副驾驶"},
        ]
        self.populate_sessions(mock_sessions)

    def populate_sessions(self, sessions: List[Dict]):
        self.sessions_cache = sessions
        self.session_combo.blockSignals(True)
        self.session_combo.clear()

        for s in sessions:
            title = s.get("title") or s.get("username") or "未知"
            prefix = "👥 " if s.get("is_group") else "👤 "
            self.session_combo.addItem(f"{prefix}{title}", s)

        # 重新配置 Completer 保持包含模糊匹配
        comp = self.session_combo.completer()
        if comp:
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

        self.session_combo.blockSignals(False)

        if sessions:
            self.on_session_selected(0)

    def on_session_selected(self, index: int):
        data = self.session_combo.itemData(index)
        if not data:
            return
        self.current_session = data
        title = data.get("title") or data.get("username")
        self.target_name_lbl.setText(f"{'👥 群聊: ' if data.get('is_group') else '👤 好友: '}{title}")

        # 拉取该会话近 15 条消息
        self.load_session_context(data.get("username", ""))

    def load_session_context(self, chat_id: str):
        if not chat_id:
            return

        try:
            resp = requests.get(
                "http://127.0.0.1:8000/api/messages",
                params={"username": chat_id, "limit": 15},
                timeout=1.0,
            )
            if resp.status_code == 200:
                msgs = resp.json().get("data", [])
                self.recent_messages = msgs
                if msgs:
                    latest = msgs[-1]
                    spk = "我" if latest.get("is_from_me") else (latest.get("sender_name") or "对方")
                    self.last_msg_box.setText(f"{spk}: {latest.get('content', '...')}")
                else:
                    self.last_msg_box.setText("（暂无近期消息）")

                if self.auto_toggle.isChecked() and msgs:
                    self.trigger_generation()
                return
        except Exception:
            pass

        # 离线兜底
        self.recent_messages = [
            {"is_from_me": False, "sender_name": "对方", "content": self.current_session.get("latest_msg", "你好呀")}
        ]
        self.last_msg_box.setText(f"对方: {self.current_session.get('latest_msg', '你好')}")
        if self.auto_toggle.isChecked():
            self.trigger_generation()

    def clear_cards(self):
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def trigger_generation(self):
        if not self.current_session:
            return

        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("生成中...")
        instruction = self.instruct_input.text().strip()

        chat_id = self.current_session.get("username", "")
        chat_title = self.current_session.get("title") or chat_id

        self.worker = AISuggestionWorker(
            context_msgs=self.recent_messages,
            chat_id=chat_id,
            chat_title=chat_title,
            custom_instruction=instruction,
            parent=self,
        )
        self.worker.finished.connect(self.on_generation_finished)
        self.worker.failed.connect(self.on_generation_failed)
        self.worker.start()

    def on_generation_finished(self, suggestions: List[Dict]):
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("✨ 生成回复建议")
        self.clear_cards()

        for s in suggestions:
            card = SuggestionCard(
                tag=s.get("tag", "建议"),
                style_name=s.get("style", "智能建议"),
                text=s.get("text", ""),
                parent=self,
            )
            card.sendRequested.connect(self.handle_send_request)
            card.pasteRequested.connect(self.handle_paste_request)
            card.copyRequested.connect(self.handle_copy_request)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

    def on_generation_failed(self, error_msg: str):
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("✨ 生成回复建议")
        QMessageBox.warning(self, "AI 生成失败", f"大模型接口调用异常: {error_msg}")

    def handle_send_request(self, text: str):
        """一键置顶微信并执行多气泡模拟发送"""
        if not self.current_session:
            return
        title = self.current_session.get("title") or self.current_session.get("username")
        ok, msg = self.sender.send_to_chat(text=text, target_name=title, force_search=True)
        if not ok:
            QMessageBox.warning(self, "发送遇到异常", msg)

    def handle_paste_request(self, text: str):
        """置顶微信并填入输入框，不执行发送"""
        if not self.current_session:
            return
        title = self.current_session.get("title") or self.current_session.get("username")
        ok, msg = self.sender.paste_to_chat(text=text, target_name=title, force_search=True)
        if not ok:
            QMessageBox.warning(self, "填入遇到异常", msg)

    def handle_copy_request(self, text: str):
        """复制到剪贴板"""
        QApplication.clipboard().setText(text)

    def closeEvent(self, event):
        if hasattr(self, "tracker"):
            self.tracker.stop_hook()
        if hasattr(self, "ws_bridge"):
            self.ws_bridge.stop()
        super().closeEvent(event)


def main():
    ensure_default_desktop()
    app = QApplication(sys.argv)
    ensure_default_desktop()
    app.setApplicationName("WeChatCopilotDock")
    window = WeChatCopilotDock()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
