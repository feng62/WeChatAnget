# WeChatAnget

> 微信 4.x 本地消息实时读取、大模型智能托管自动回复、个性化记忆沉淀与极简 Web 控制台系统。

基于本地只读 SQLite 解密与 Windows UI 自动化驱动。集成 **Vue 3 + Vite 现代工效学控制台**、**多轮上下文感知**、**分层双轨记忆库**、**防刷串行消息池** 以及 **搜索定位防串线** 机制。

---

## 🌟 核心特性

- **现代 macOS / Linear 风格 Web 控制台**：基于 Vue 3 + Tailwind CSS + Lucide 矢量图标，彻底去除劣质 AI 味，提供沉浸式管理体验。
- **本地零侵入只读解密**：通过内存句柄安全提取密钥，只读监听 SQLite WAL 增量，杜绝破坏官方数据库文件。
- **全自动防串线消息回复**：通过 Windows API 唤醒微信并自动使用 `Ctrl+F` 搜索目标好友/群聊后再行输入，避免串线误发。
- **防刷串行消息池 (Debounce Queue)**：
  - 群聊与私聊分别支持动态去抖聚合（支持自定义秒数），短时间内多条连发会自动汇聚为一条整体理解；
  - 全局串行 FIFO 队列，一次只处理并回复一个人，井然有序。
- **多气泡自然断句发送**：长篇回复可自动按照标点或段落拆分为多条气泡（如 2~3 条），并附带毫秒级打字停顿间隔，模拟真实真人交流。
- **双层记忆架构**：
  - **全局通用事实库**：记录跨所有会话通用的主客体核心事实；
  - **单会话专属画像**：针对特定联系人/群聊沉淀专属标签，回复时自动唤醒交织。
- **灵活的人设与模型适配**：内置 4 套预设性格人设，支持自定义 System Prompt，无缝对接 DeepSeek、Qwen、Kimi、Ollama 及兼容 OpenAI 规范的任何大模型。

---

## 📁 项目目录结构

```text
WeChatAnget/
├── pyproject.toml              # Python 标准工程定义 (src layout)
├── requirements.txt            # Python 核心依赖清单
├── config.example.json         # 配置文件示例 (复制为 config.json 后修改)
├── run_web_ui.bat              # Web 控制台一键启动脚本 (原生 ANSI 编码)
├── run_message_monitor.bat     # 终端纯 CLI 消息监听脚本
│
├── src/                        # Python 核心源码目录
│   ├── web_server.py           # FastAPI + WebSocket WebUI 服务端
│   ├── demo_read_messages.py   # CLI 消息增量监控与转码演示
│   └── core/                   # 核心业务模块包
│       ├── __init__.py
│       ├── ai_brain.py         # 大模型问答、建议生成与多轮上下文
│       ├── ai_config.py        # 模型提供商与防抖/分条气泡配置
│       ├── message_pool.py     # 串行队列 (FIFO) + 动态防刷聚合调度
│       ├── message_sender.py   # 窗口置顶 + 搜索定位 + 多气泡拆分发送
│       ├── whitelist_manager.py# 自动回复白名单管理器
│       ├── memory_manager.py   # 全局共享记忆 + 单会话专属记忆
│       ├── persona_manager.py  # 预设人设与 System Prompt 生成器
│       ├── db_locator.py       # 微信 4.x 数据目录智能寻址
│       ├── db_reader.py        # SQLite 内存密钥提取、只读解密与增量监听
│       └── media_processor.py  # 富媒体转码 (wxgf 转 JPEG、Silk 转 WAV)
│
├── frontend/                   # Vue 3 + Vite + Tailwind CSS 前端源码
│   ├── src/                    # 前端页面与组件 (Sidebar, Chat, Persona 等)
│   ├── package.json
│   ├── vite.config.js          # 输出至 ../static
│   ├── build.bat               # 前端一键构建脚本
│   └── dev.bat                 # 前端热重载开发服务器
│
├── static/                     # 已编译好的前端静态产物 (开箱即用)
│   ├── index.html
│   └── assets/
│
└── data/                       # 本地持久化数据目录 (已被 .gitignore 保护)
    ├── ai_settings.example.json# 模型配置范例
    ├── persona.example.json    # 人设配置范例
    └── whitelist.example.json  # 白名单范例
```

---

## 🚀 快速开始

### 1. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 2. 初始化配置文件
复制范例配置文件并根据需要填入本地微信数据目录（如不填会自动检索）：
```bash
copy config.example.json config.json
copy data\ai_settings.example.json data\ai_settings.json
```

### 3. 一键启动
* **启动 Web 智能控制台**：双击运行 `run_web_ui.bat`，浏览器访问 `http://127.0.0.1:8000`。
* **启动纯命令行监控**：双击运行 `run_message_monitor.bat`。

---

## 🔒 隐私与安全性规范

- 本项目**绝不**上传任何本地数据库文件、聊天记录或个人隐私至外部网络；
- 运行中生成的 `data/db_cache/`、`data/memory/`、`media-cache/` 及包含个人 API Key 的 `data/*.json` 均已在 `.gitignore` 中严格排除。

---

## 📄 License
MIT License
