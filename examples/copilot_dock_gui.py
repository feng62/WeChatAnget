# -*- coding: utf-8 -*-
"""
微信 AI 对话副驾驶 - 桌面贴边伴随窗口 (PyQt6 高保真实现)

核心功能：
1. 始终无缝贴合在微信桌面端主窗口右侧；
2. 微信最小化 -> 伴随窗口自动隐藏；微信恢复/移动/缩放 -> 伴随窗毫秒级自动吸附跟踪；
3. 智能防越界：微信全屏或贴近屏幕最右边缘时，自动吸附至左侧或内嵌右侧；
4. 实时展示当前聊天最新消息；
5. 提供 3 种风格 AI 建议卡片（得体、幽默、精简）；
6. 提供「一键填入/发送」与「仅复制到剪贴板」双操作；
7. 支持自定义 Prompt 指令重新生成建议；
8. 支持在界面中直观开关自动托管与快捷模型设置。
"""

import os
import sys
import time
from typing import Optional

# 确保引入上一级 core 模块
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from examples.ai_service import (
    AISuggestionWorker,
    load_copilot_config,
    save_copilot_config,
)
from examples.window_tracker import WeChatWindowTracker
from core.message_sender import MessageSender


class SuggestionCard(QFrame):
    """单个回复建议卡片"""

    sendRequested = pyqtSignal(str)
    copyRequested = pyqtSignal(str)

    def __init__(self, style_tag: str, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self.setObjectName("suggestionCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # 头部标签栏
        top_layout = QHBoxLayout()
        tag_lbl = QLabel(f"[{style_tag}]")
        tag_lbl.setObjectName("cardTag")
        top_layout.addWidget(tag_lbl)
        top_layout.addStretch()

        layout.addLayout(top_layout)

        # 建议文本
        content_lbl = QLabel(text)
        content_lbl.setWordWrap(True)
        content_lbl.setObjectName("cardContent")
        layout.addWidget(content_lbl)

        # 操作按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.copy_btn = QPushButton("📋 复制")
        self.copy_btn.setObjectName("btnCopy")
        self.copy_btn.clicked.connect(lambda: self.copyRequested.emit(self.text))

        self.send_btn = QPushButton("🚀 一键发送")
        self.send_btn.setObjectName("btnSend")
        self.send_btn.clicked.connect(lambda: self.sendRequested.emit(self.text))

        btn_layout.addWidget(self.copy_btn)
        btn_layout.addWidget(self.send_btn)
        layout.addLayout(btn_layout)


class SettingsDialog(QDialog):
    """快捷模型配置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ AI 模型接口与参数设置")
        self.resize(380, 420)
        self.cfg = load_copilot_config()

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel("<b>Base URL (API 根地址):</b>"))
        self.url_edit = QLineEdit(self.cfg.get("base_url", "https://api.deepseek.com/v1"))
        layout.addWidget(self.url_edit)

        layout.addWidget(QLabel("<b>API Key (密钥):</b>"))
        self.key_edit = QLineEdit(self.cfg.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.key_edit)

        layout.addWidget(QLabel("<b>Model (模型名称):</b>"))
        self.model_edit = QLineEdit(self.cfg.get("model", "deepseek-chat"))
        layout.addWidget(self.model_edit)

        self.auto_cb = QCheckBox("收到新消息时自动生成回复建议")
        self.auto_cb.setChecked(self.cfg.get("auto_generate", True))
        layout.addWidget(self.auto_cb)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self.save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def save(self):
        self.cfg["base_url"] = self.url_edit.text().strip()
        self.cfg["api_key"] = self.key_edit.text().strip()
        self.cfg["model"] = self.model_edit.text().strip()
        self.cfg["auto_generate"] = self.auto_cb.isChecked()
        save_copilot_config(self.cfg)
        self.accept()


class WeChatCopilotDockWindow(QWidget):
    """始终伴随在微信右侧的副驾驶悬浮面板"""

    def __init__(self):
        super().__init__()
        self.tracker = WeChatWindowTracker()
        self.sender = MessageSender()
        self.cfg = load_copilot_config()
        self.dock_width = int(self.cfg.get("dock_width", 340))

        self.wechat_hwnd = None
        self.last_msg_text = "等待微信消息接入..."
        self.sender_name = "微信联系人"
        self.is_user_unpinned = False

        self.init_window_flags()
        self.init_ui()
        self.init_styles()
        self.init_tracker_timer()

    def init_window_flags(self):
        # 无边框 + 保持置顶 + 任务栏不占单独大图标
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. 顶部标题栏与吸附状态
        header = QFrame()
        header.setObjectName("headerFrame")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDot")
        self.title_lbl = QLabel("微信 AI 副驾驶")
        self.title_lbl.setObjectName("appTitle")

        header_layout.addWidget(self.status_dot)
        header_layout.addWidget(self.title_lbl)
        header_layout.addStretch()

        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setObjectName("btnIcon")
        self.btn_settings.setToolTip("打开模型设置")
        self.btn_settings.clicked.connect(self.open_settings)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("btnIcon")
        self.btn_close.setToolTip("最小化隐藏")
        self.btn_close.clicked.connect(self.hide)

        header_layout.addWidget(self.btn_settings)
        header_layout.addWidget(self.btn_close)
        main_layout.addWidget(header)

        # 2. 当前会话与上文卡片
        context_box = QFrame()
        context_box.setObjectName("contextBox")
        ctx_layout = QVBoxLayout(context_box)
        ctx_layout.setContentsMargins(12, 8, 12, 8)
        ctx_layout.setSpacing(4)

        ctx_header = QHBoxLayout()
        self.chat_name_lbl = QLabel(f"💬 {self.sender_name}")
        self.chat_name_lbl.setObjectName("chatTargetName")
        ctx_header.addWidget(self.chat_name_lbl)
        ctx_header.addStretch()

        self.auto_toggle = QCheckBox("自动生成")
        self.auto_toggle.setChecked(self.cfg.get("auto_generate", True))
        self.auto_toggle.stateChanged.connect(self.on_auto_toggle_changed)
        ctx_header.addWidget(self.auto_toggle)
        ctx_layout.addLayout(ctx_header)

        self.msg_preview = QLabel(self.last_msg_text)
        self.msg_preview.setWordWrap(True)
        self.msg_preview.setObjectName("msgPreview")
        ctx_layout.addWidget(self.msg_preview)

        main_layout.addWidget(context_box)

        # 3. 建议卡片滚动展示区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("cardsScroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(12, 8, 12, 8)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch()

        scroll.setWidget(self.cards_container)
        main_layout.addWidget(scroll, 1)

        # 4. 底部输入与重新生成区
        bottom_bar = QFrame()
        bottom_bar.setObjectName("bottomBar")
        bot_layout = QVBoxLayout(bottom_bar)
        bot_layout.setContentsMargins(12, 10, 12, 12)
        bot_layout.setSpacing(8)

        self.instruct_input = QLineEdit()
        self.instruct_input.setPlaceholderText("指定要求（如：婉拒聚餐、约明天下午...）")
        self.instruct_input.setObjectName("instructInput")
        self.instruct_input.returnPressed.connect(self.trigger_generation)
        bot_layout.addWidget(self.instruct_input)

        action_row = QHBoxLayout()
        self.web_btn = QPushButton("🌐 打开 Web 控制台")
        self.web_btn.setObjectName("btnGhost")
        self.web_btn.clicked.connect(self.open_web_console)

        self.gen_btn = QPushButton("✨ 生成建议")
        self.gen_btn.setObjectName("btnPrimary")
        self.gen_btn.clicked.connect(self.trigger_generation)

        action_row.addWidget(self.web_btn)
        action_row.addStretch()
        action_row.addWidget(self.gen_btn)
        bot_layout.addLayout(action_row)

        main_layout.addWidget(bottom_bar)

    def init_styles(self):
        self.setStyleSheet("""
            QWidget {
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                background: #f7f7f7;
                color: #222;
            }
            #headerFrame {
                background: #2e2e2e;
                color: #fff;
                border-bottom: 1px solid #1f1f1f;
            }
            #statusDot {
                color: #07c160;
                font-size: 14px;
            }
            #appTitle {
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
            }
            #btnIcon {
                background: transparent;
                border: none;
                color: #bbb;
                font-size: 13px;
                padding: 3px 6px;
                border-radius: 4px;
            }
            #btnIcon:hover {
                background: rgba(255, 255, 255, 0.15);
                color: #fff;
            }
            #contextBox {
                background: #ffffff;
                border-bottom: 1px solid #e5e5e5;
            }
            #chatTargetName {
                font-size: 13px;
                font-weight: 600;
                color: #333;
            }
            #msgPreview {
                font-size: 12px;
                color: #666;
                background: #f4f4f5;
                padding: 6px 8px;
                border-radius: 4px;
                border-left: 3px solid #07c160;
            }
            #suggestionCard {
                background: #ffffff;
                border: 1px solid #e2e2e2;
                border-radius: 6px;
            }
            #suggestionCard:hover {
                border-color: #07c160;
                background: #fcfcfc;
            }
            #cardTag {
                font-size: 11px;
                font-weight: bold;
                color: #07c160;
                background: #e8f8ed;
                padding: 2px 6px;
                border-radius: 3px;
            }
            #cardContent {
                font-size: 13px;
                line-height: 1.4;
                color: #222;
            }
            #btnCopy {
                background: #f0f0f0;
                border: 1px solid #dcdcdc;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
                color: #444;
            }
            #btnCopy:hover {
                background: #e4e4e4;
            }
            #btnSend {
                background: #07c160;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                color: #ffffff;
                font-weight: 600;
            }
            #btnSend:hover {
                background: #06ad56;
            }
            #bottomBar {
                background: #ffffff;
                border-top: 1px solid #e5e5e5;
            }
            #instructInput {
                background: #f5f5f5;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }
            #instructInput:focus {
                border-color: #07c160;
                background: #fff;
            }
            #btnPrimary {
                background: #07c160;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
                color: #fff;
                font-weight: bold;
            }
            #btnPrimary:hover {
                background: #06ad56;
            }
            #btnGhost {
                background: transparent;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
                color: #555;
            }
            #btnGhost:hover {
                background: #f0f0f0;
                color: #222;
            }
        """)

    def init_tracker_timer(self):
        # 30ms 高频定时器无缝同步微信窗口位置与最小化状态
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.sync_with_wechat)
        self.sync_timer.start(35)

    def sync_with_wechat(self):
        """与微信主窗口位置及最小化状态实时同步"""
        win = self.tracker.find_wechat_window()
        if not win:
            self.status_dot.setStyleSheet("color: #999;")
            self.title_lbl.setText("微信 AI 副驾驶 (等待微信...)")
            return

        self.wechat_hwnd = win["hwnd"]
        self.status_dot.setStyleSheet("color: #07c160;")
        self.title_lbl.setText(f"微信副驾驶 (PID: {win['pid']})")

        # 微信最小化 -> 伴随窗自动隐藏
        if win["is_minimized"] or not win["is_visible"]:
            if self.isVisible():
                self.hide()
            return

        # 微信正常可见 -> 伴随窗自动显现并同步吸附几何位置
        x, y, w, h, mode = self.tracker.calculate_dock_geometry(
            win["rect"],
            dock_width=self.dock_width,
            padding=2,
        )

        if not self.isVisible():
            self.show()

        # 仅当位置变动超过 1 像素时移动，消除多余刷新抖动
        curr = self.geometry()
        if abs(curr.x() - x) > 1 or abs(curr.y() - y) > 1 or abs(curr.height() - h) > 1:
            self.setGeometry(x, y, w, h)

    def set_context_message(self, chat_name: str, msg_text: str):
        """外部推送新消息时更新上文并可自动生成建议"""
        self.sender_name = chat_name or "当前联系人"
        self.last_msg_text = msg_text or "..."
        self.chat_name_lbl.setText(f"💬 {self.sender_name}")
        self.msg_preview.setText(self.last_msg_text)

        if self.auto_toggle.isChecked():
            self.trigger_generation()

    def trigger_generation(self):
        """触发 AI 建议生成"""
        instruction = self.instruct_input.text().strip()
        self.gen_btn.setEnabled(False)
        self.gen_btn.setText("生成中...")

        self.worker = AISuggestionWorker(
            context_msg=self.last_msg_text,
            sender_name=self.sender_name,
            custom_instruction=instruction,
            cfg=self.cfg,
        )
        self.worker.finished.connect(self.render_suggestions)
        self.worker.start()

    def render_suggestions(self, suggestions: list):
        self.gen_btn.setEnabled(True)
        self.gen_btn.setText("✨ 生成建议")

        # 清空原卡片
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 重新插入建议卡片
        for item in suggestions:
            card = SuggestionCard(item.get("style", "建议"), item.get("text", ""))
            card.sendRequested.connect(self.on_send_requested)
            card.copyRequested.connect(self.on_copy_requested)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

    def on_send_requested(self, text: str):
        """一键定位目标会话并自动发送"""
        target = self.sender_name if self.sender_name not in ("微信联系人", "当前联系人") else ""
        ok, detail = self.sender.send_to_chat(text, target_name=target, hwnd=self.wechat_hwnd)
        if ok:
            self.show_toast("已一键发送到微信！")
        else:
            QMessageBox.warning(self, "发送提示", detail)

    def on_copy_requested(self, text: str):
        """仅复制到系统剪贴板"""
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
            self.show_toast("已复制到剪贴板！")

    def show_toast(self, msg: str):
        orig_title = self.title_lbl.text()
        self.title_lbl.setText(f"✓ {msg}")
        QTimer.singleShot(1800, lambda: self.title_lbl.setText(orig_title))

    def on_auto_toggle_changed(self, state):
        self.cfg["auto_generate"] = bool(state)
        save_copilot_config(self.cfg)

    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            self.cfg = load_copilot_config()
            self.dock_width = int(self.cfg.get("dock_width", 340))
            self.auto_toggle.setChecked(self.cfg.get("auto_generate", True))

    def open_web_console(self):
        import webbrowser
        webbrowser.open("http://127.0.0.1:8000")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dock = WeChatCopilotDockWindow()
    dock.show()
    # 模拟初始默认卡片
    dock.set_context_message("微信测试好友", "晚上有空一起吃火锅吗？")
    sys.exit(app.exec())
