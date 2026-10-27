# -*- coding: utf-8 -*-
"""
微信 4.x 多账号并发消息实时监控 WebUI 服务端 (FastAPI + WebSocket)

【核心功能】：
1. 多账号切换与会话列表读取 (REST API)
2. 历史聊天记录查询与格式化清洗 (REST API)
3. 图片即时转码、Silk 语音转码流式输出 (REST API)
4. 新消息全双工实时广播推送 (WebSocket)
5. 桌面版微信高保真 UI 单页应用挂载
"""

import asyncio
import io
import json
import os
import re
import sys
import threading
import time
from typing import Dict, List, Optional, Set
import urllib.parse

# 终端字符集兼容
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import Body, FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.db_locator import resolve_db_dir
from core.db_reader import MultiAccountListenerManager, WeChatDatabaseReader
from core.ai_config import load_ai_settings, save_ai_settings, PROVIDER_PRESETS
from core.persona_manager import load_persona, save_persona, PERSONA_PRESETS, build_system_prompt
from core.memory_manager import MemoryManager
from core.ai_brain import AIBrain
from core.message_sender import MessageSender
from core.whitelist_manager import WhitelistManager
from core.message_pool import MessagePoolEngine

ai_brain = AIBrain()
message_sender = MessageSender()
whitelist_manager = WhitelistManager()
message_pool = MessagePoolEngine(brain=ai_brain, sender=message_sender, whitelist=whitelist_manager)


def load_config() -> dict:
    cfg_file = os.path.join(PROJECT_ROOT, "config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


cfg = load_config()
db_dir = cfg.get("dbDir") or ""
poll_interval = float(cfg.get("pollInterval", 0.4))
ignore_self = bool(cfg.get("ignoreSelf", False))

app = FastAPI(title="微信桌面版 WebUI 消息监控控制台")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局管理器与连接池
manager: Optional[MultiAccountListenerManager] = None
reader_map: Dict[str, WeChatDatabaseReader] = {}
account_list: List[Dict] = []
active_websockets: Set[WebSocket] = set()
ws_lock = threading.Lock()
loop: Optional[asyncio.AbstractEventLoop] = None


def broadcast_to_websockets(payload: dict):
    """跨线程向所有活跃的 WebSocket 客户端广播新消息"""
    global loop
    if not active_websockets:
        return
    data_str = json.dumps(payload, ensure_ascii=False)

    async def _send():
        dead_sockets = set()
        for ws in list(active_websockets):
            try:
                await ws.send_text(data_str)
            except Exception:
                dead_sockets.add(ws)
        if dead_sockets:
            with ws_lock:
                active_websockets.difference_update(dead_sockets)

    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(_send(), loop)


def on_incoming_message(msg: dict):
    """底层监听器捕获到新消息时的全局回调"""
    broadcast_to_websockets({
        "type": "new_message",
        "data": msg
    })
    # 传递给自动托管消息池（防刷聚合与串行队列）
    try:
        message_pool.handle_incoming_message(msg)
    except Exception as e:
        print(f"[WebUI] 消息池接入异常: {e}", flush=True)


@app.on_event("startup")
def startup_event():
    global manager, reader_map, account_list, loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    message_pool.set_broadcast_callback(broadcast_to_websockets)

    print("\n[WebUI] 正在启动微信 4.x 数据挂载引擎...", flush=True)
    found_db = resolve_db_dir(db_dir, verbose=True)
    if not found_db:
        print("[WebUI 错误] 未能定位到微信数据目录，请确认微信客户端已登录！", flush=True)
        return

    manager = MultiAccountListenerManager(
        db_dir=found_db,
        poll_interval=poll_interval,
        ignore_self=ignore_self,
        media_cache_dir=os.path.join(PROJECT_ROOT, "media-cache"),
    )

    try:
        account_list = manager.discover_and_mount()
    except Exception as e:
        print(f"[WebUI 错误] 挂载账号失败: {e}", flush=True)
        account_list = []

    # 建立账号映射表供接口快速查找
    for r in manager.readers:
        # 支持以 account 目录名或者 wxid 寻址
        reader_map[r.account] = r
        if r.self_wxid:
            reader_map[r.self_wxid] = r

    if manager.readers:
        message_pool.set_db_reader(manager.readers[0])

    # 注册实时消息推送回调并启动增量监听
    manager.on_message(on_incoming_message)
    manager.start()
    print(f"[WebUI] 微信监听引擎就绪，成功挂载 {len(manager.readers)} 个账号！\n", flush=True)


@app.on_event("shutdown")
def shutdown_event():
    global manager
    if manager:
        print("[WebUI] 正在平滑停止所有账号监听线程...", flush=True)
        manager.stop()


def get_reader_for_account(acct: str) -> Optional[WeChatDatabaseReader]:
    if not acct:
        if manager and manager.readers:
            return manager.readers[0]
        return None
    return reader_map.get(acct)


# ─────────────────────────────────────────────────────────────
# REST API 接口
# ─────────────────────────────────────────────────────────────

@app.get("/api/accounts")
def api_get_accounts():
    """获取所有已登录并挂载的账号列表"""
    return {
        "code": 0,
        "data": account_list,
    }


@app.get("/api/sessions")
def api_get_sessions(account: Optional[str] = Query(None)):
    """获取指定账号的会话列表（按最近活跃时间倒序）"""
    reader = get_reader_for_account(account)
    if not reader:
        raise HTTPException(status_code=404, detail="未找到指定的微信账号或当前无可用账号")

    raw_sessions = []
    try:
        raw_sessions = reader.db.get_sessions(limit=500)
    except Exception as e:
        print(f"[API] 获取会话列表异常: {e}", flush=True)

    formatted = []
    for s in raw_sessions:
        uname = s.get("username") or ""
        if not uname or uname.startswith("@placeholder"):
            continue

        is_group = uname.endswith("@chatroom")
        title = reader.get_display_name(uname)
        last_sender = s.get("last_sender") or ""
        if last_sender and last_sender != uname:
            sender_name = reader.get_display_name(last_sender)
        else:
            sender_name = ""

        summary = s.get("summary", "")
        if "<refermsg" in summary or "<type>57</type>" in summary:
            ref = reader.processor.parse_refer_msg(summary)
            if ref and ref.get("title"):
                summary = f"「引用」{ref['title']}"
        elif "<appmsg" in summary:
            card = reader.processor.parse_xml_card(summary)
            if card and card.get("title"):
                summary = f"[卡片] {card['title']}"

        session_mem = ai_brain.memory.get_session_memory(uname)
        in_wl = whitelist_manager.is_in_whitelist(uname, title or uname)

        formatted.append({
            "username": uname,
            "title": title or uname,
            "is_group": is_group,
            "unread": s.get("unread", 0),
            "summary": summary,
            "last_time": s.get("last_time", 0),
            "last_sender": sender_name or last_sender,
            "auto_reply": session_mem.get("auto_reply", False) or in_wl,
            "in_whitelist": in_wl,
            "debounce_sec": session_mem.get("debounce_sec", 0),
        })

    # 按时间降序排序
    formatted.sort(key=lambda x: x["last_time"], reverse=True)
    return {
        "code": 0,
        "account": reader.account,
        "self_name": reader.self_name,
        "self_wxid": reader.self_wxid,
        "data": formatted,
    }


@app.get("/api/messages")
def api_get_messages(
    account: Optional[str] = Query(None),
    chat_id: str = Query(..., description="好友wxid或群聊chatroom id"),
    limit: int = Query(50, ge=1, le=200),
):
    """获取指定会话的历史消息（按时间升序）"""
    reader = get_reader_for_account(account)
    if not reader:
        raise HTTPException(status_code=404, detail="微信账号未挂载")

    try:
        raw_msgs = reader.db.get_messages(chat_id, limit=limit)
    except Exception as e:
        print(f"[API] 读取会话 {chat_id} 历史记录失败: {e}", flush=True)
        raw_msgs = []

    is_group = chat_id.endswith("@chatroom")
    chat_title = reader.get_display_name(chat_id)
    out_msgs = []

    for r in raw_msgs:
        sender_id = r.get("sender_id")
        sender_username = r.get("sender_username") or ""
        mtype = r.get("type") or "未知"
        raw_content = r.get("content") or ""
        local_id = r.get("local_id")
        shard = r.get("shard") or ""

        # 判定消息方向
        is_from_me = (sender_username == reader.self_wxid)
        if not is_group and not sender_username and sender_id == 0:
            is_from_me = True

        # 群聊正文中常带有 "wxid_xxx:\n实际内容"，深度清洗去除前缀防串
        clean_text = raw_content
        if is_group:
            clean_text = re.sub(r'^[a-zA-Z0-9_\-]+:\s*\n?', '', clean_text)

        # 发送者可读名称
        if is_from_me:
            sender_name = reader.self_name
        else:
            sender_name = reader.get_display_name(sender_username or chat_id) or ("群友" if is_group else chat_title)

        # 多媒体与卡片解析
        media = None
        if mtype == "图片":
            clean_text = "[图片]"
            media = {
                "type": "image",
                "url": f"/api/media/image?account={reader.account}&chat_id={chat_id}&local_id={local_id}&shard={shard}",
            }
        elif mtype == "语音":
            clean_text = "[语音]"
            media = {
                "type": "voice",
                "url": f"/api/media/voice?account={reader.account}&chat_id={chat_id}&local_id={local_id}&shard={shard}",
            }
        elif mtype == "视频":
            media = {
                "type": "video",
                "url": f"/api/media/video?account={reader.account}&chat_id={chat_id}&local_id={local_id}&shard={shard}",
            }
            clean_text = "[视频]"
        elif "<refermsg" in raw_content or "<type>57</type>" in raw_content:
            ref = reader.processor.parse_refer_msg(raw_content)
            if ref:
                mtype = "引用消息"
                clean_text = ref.get("title", "")
                media = {"type": "refer", **ref}
        elif "<appmsg" in raw_content or mtype == "链接卡片":
            card = reader.processor.parse_xml_card(raw_content)
            if card:
                mtype = "链接卡片"
                media = {"type": "card", **card}
                clean_text = card.get("summary", "")
            else:
                mt = re.search(r"<title>(.*?)</title>", raw_content, re.DOTALL)
                clean_text = mt.group(1).strip() if mt else "[应用卡片消息]"
        elif "<emoji" in raw_content or mtype in ("动画表情", "表情包"):
            mtype = "表情包"
            # 尝试提取 cdnurl
            m = re.search(r'cdnurl\s*=\s*"([^"]+)"', raw_content)
            if not m:
                m = re.search(r'thumburl\s*=\s*"([^"]+)"', raw_content)
            cdn_url = m.group(1).replace("&amp;", "&") if m else ""
            media = {"type": "emoji", "cdn_url": cdn_url}
            clean_text = "[动画表情]"

        sort_seq = int(r.get("sort_seq") or (r.get("create_time", 0) * 1000))
        out_msgs.append({
            "local_id": local_id,
            "shard": shard,
            "msg_id": f"{chat_id}:{shard}:{local_id}",
            "type": mtype,
            "is_from_me": is_from_me,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "create_time": r.get("create_time", 0),
            "sort_seq": sort_seq,
            "text": clean_text,
            "media": media,
        })

    # 按底层的严格单调流水号 sort_seq 升序排列，彻底避免同一秒内消息乱序串流
    out_msgs.sort(key=lambda x: x["sort_seq"])
    return {
        "code": 0,
        "chat_id": chat_id,
        "chat_title": chat_title,
        "is_group": is_group,
        "data": out_msgs,
    }


@app.api_route("/api/media/image", methods=["GET", "HEAD"])
def api_get_media_image(
    account: Optional[str] = Query(None),
    chat_id: str = Query(...),
    local_id: int = Query(...),
    shard: Optional[str] = Query(None),
):
    """动态获取并转码图片数据"""
    reader = get_reader_for_account(account)
    if not reader:
        raise HTTPException(status_code=404, detail="账号未就绪")

    img_data = reader.download_image_bytes(chat_id, local_id, shard=shard)
    if not img_data or not img_data.get("clean_bytes"):
        # 返回 1x1 透明像素或占位图
        raise HTTPException(status_code=404, detail="图片无法解密或未下载到本地")

    clean_bytes = img_data["clean_bytes"]
    ext = (img_data.get("ext") or ".jpg").lower()
    media_type = "image/png" if ext == ".png" else "image/jpeg"

    return Response(
        content=clean_bytes,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.api_route("/api/media/voice", methods=["GET", "HEAD"])
def api_get_media_voice(
    account: Optional[str] = Query(None),
    chat_id: str = Query(...),
    local_id: int = Query(...),
    shard: Optional[str] = Query(None),
):
    """动态获取并转码语音数据为 WAV"""
    reader = get_reader_for_account(account)
    if not reader:
        raise HTTPException(status_code=404, detail="账号未就绪")

    voice_data = reader.download_voice_wav(chat_id, local_id, shard=shard)
    if not voice_data or not voice_data.get("wav_path"):
        raise HTTPException(status_code=404, detail="语音无法解码或不存在")

    wav_path = voice_data["wav_path"]
    if not os.path.exists(wav_path):
        raise HTTPException(status_code=404, detail="WAV 文件未生成")

    return FileResponse(
        path=wav_path,
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.api_route("/api/media/video", methods=["GET", "HEAD"])
def api_get_media_video(
    account: Optional[str] = Query(None),
    chat_id: str = Query(...),
    local_id: int = Query(...),
    shard: Optional[str] = Query(None),
):
    """动态获取视频（若有完整 MP4 则输出视频流，若仅有封面缩略图则输出封面图片）"""
    reader = get_reader_for_account(account)
    if not reader:
        raise HTTPException(status_code=404, detail="账号未就绪")

    v_res = reader.download_video_media(chat_id, local_id, shard=shard)
    if not v_res or not os.path.exists(v_res.get("path", "")):
        raise HTTPException(status_code=404, detail="视频文件未生成或不存在")

    fpath = v_res["path"]
    is_video = (v_res.get("type") == "video")
    media_type = "video/mp4" if is_video else "image/jpeg"

    return FileResponse(
        path=fpath,
        media_type=media_type,
        headers={
            "X-Media-Type": "video" if is_video else "thumb",
            "Cache-Control": "public, max-age=86400",
        },
    )


# ─────────────────────────────────────────────────────────────
# WebSocket 实时通信端点
# ─────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    with ws_lock:
        active_websockets.add(websocket)
    try:
        # 初始握手包
        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": "WebSocket 实时监听通道已建立",
            "accounts_count": len(account_list),
        }))
        while True:
            # 保持心跳连接
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        with ws_lock:
            active_websockets.discard(websocket)
    except Exception:
        with ws_lock:
            active_websockets.discard(websocket)


# ─────────────────────────────────────────────────────────────
# AI 模型、性格设计、记忆中心与消息发送 REST API
# ─────────────────────────────────────────────────────────────

@app.get("/api/ai/config")
def api_get_ai_config():
    """获取 AI 模型配置与服务商预设"""
    return {
        "code": 0,
        "config": load_ai_settings(),
        "presets": PROVIDER_PRESETS,
    }


@app.post("/api/ai/config")
def api_save_ai_config(settings: dict = Body(...)):
    """保存 AI 模型配置"""
    ok = save_ai_settings(settings)
    return {"code": 0 if ok else -1, "message": "保存成功" if ok else "保存失败"}


@app.post("/api/ai/test_connection")
def api_test_connection():
    """测试当前大模型 API 连通性"""
    ok, msg = ai_brain.test_connection()
    return {"code": 0 if ok else -1, "message": msg}


@app.get("/api/ai/persona")
def api_get_persona():
    """获取当前性格设定与预设模板"""
    p = load_persona()
    return {
        "code": 0,
        "persona": p,
        "presets": PERSONA_PRESETS,
        "system_prompt_preview": build_system_prompt(p),
    }


@app.post("/api/ai/persona")
def api_save_persona(persona: dict = Body(...)):
    """保存性格设定"""
    ok = save_persona(persona)
    return {
        "code": 0 if ok else -1,
        "message": "性格设定已保存" if ok else "保存失败",
        "system_prompt_preview": build_system_prompt(persona),
    }


@app.get("/api/ai/memory/global")
def api_get_global_memory():
    """获取整体全局记忆数据"""
    return {
        "code": 0,
        "data": ai_brain.memory.get_global_memory(),
    }


@app.post("/api/ai/memory/global")
def api_save_global_memory(payload: dict = Body(...)):
    """保存/追加整体全局记忆"""
    if "facts" in payload:
        ok = ai_brain.memory.update_global_memory(payload["facts"])
    elif "fact" in payload:
        ok = ai_brain.memory.add_global_fact(payload["fact"])
    else:
        raise HTTPException(status_code=400, detail="缺少 facts 或 fact 字段")
    return {"code": 0 if ok else -1, "message": "全局记忆已更新" if ok else "更新失败"}


@app.delete("/api/ai/memory/global")
def api_delete_global_memory(index: int = Query(...)):
    """删除指定的全局记忆事实条目"""
    ok = ai_brain.memory.delete_global_fact(index)
    return {"code": 0 if ok else -1, "message": "删除成功" if ok else "删除失败"}


@app.get("/api/ai/memory/session")
def api_get_session_memory(chat_id: str = Query(...)):
    """获取指定联系人或群聊的专属记忆画像"""
    return {
        "code": 0,
        "data": ai_brain.memory.get_session_memory(chat_id),
    }


@app.post("/api/ai/memory/session/note")
def api_add_session_note(payload: dict = Body(...)):
    """向联系人专属记忆追加事实标签"""
    chat_id = payload.get("chat_id")
    note = payload.get("note")
    title = payload.get("title", "")
    if not chat_id or not note:
        raise HTTPException(status_code=400, detail="chat_id 与 note 必填")
    ok = ai_brain.memory.add_session_note(chat_id, note, title)
    return {"code": 0 if ok else -1, "message": "专属记忆已追加" if ok else "追加失败"}


@app.delete("/api/ai/memory/session/note")
def api_delete_session_note(chat_id: str = Query(...), index: int = Query(...)):
    """删除联系人专属记忆中的指定标签"""
    ok = ai_brain.memory.delete_session_note(chat_id, index)
    return {"code": 0 if ok else -1, "message": "删除成功" if ok else "删除失败"}


@app.post("/api/ai/session/auto_reply")
def api_toggle_auto_reply(payload: dict = Body(...)):
    """开启或关闭指定会话的自动托管回复（与白名单联动）"""
    chat_id = payload.get("chat_id")
    name = payload.get("name", "")
    is_group = bool(payload.get("is_group", False))
    enabled = bool(payload.get("enabled", False))
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id 必填")

    ok = ai_brain.memory.set_session_auto_reply(chat_id, enabled)
    if enabled:
        whitelist_manager.add(chat_id, name=name, is_group=is_group)
    else:
        whitelist_manager.remove(chat_id)

    return {"code": 0 if ok else -1, "enabled": enabled, "in_whitelist": enabled}


@app.post("/api/ai/session/debounce")
def api_set_session_debounce(payload: dict = Body(...)):
    """设置指定联系人或群聊专属的消息聚合等待秒数"""
    chat_id = payload.get("chat_id", "").strip()
    debounce_sec = float(payload.get("debounce_sec", 0))
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id 必填")
    ok = ai_brain.memory.set_session_debounce(chat_id, debounce_sec)
    return {"code": 0 if ok else -1, "debounce_sec": debounce_sec}


# ─────────────────────────────────────────────────────────────
# 自动回复白名单管理 API
# ─────────────────────────────────────────────────────────────

@app.get("/api/ai/whitelist")
def api_get_whitelist():
    """获取自动回复白名单列表与开关状态"""
    return {
        "code": 0,
        "enabled": whitelist_manager.is_enabled(),
        "list": whitelist_manager.get_all(),
    }


@app.post("/api/ai/whitelist")
def api_add_whitelist(payload: dict = Body(...)):
    """向白名单新增好友或群聊"""
    chat_id = payload.get("chat_id", "").strip()
    name = payload.get("name", "").strip() or chat_id
    is_group = bool(payload.get("is_group", False)) or chat_id.endswith("@chatroom")

    if not chat_id and not name:
        raise HTTPException(status_code=400, detail="chat_id 或 name 至少填写一项")

    ok = whitelist_manager.add(chat_id=chat_id or name, name=name, is_group=is_group)
    if ok and chat_id:
        ai_brain.memory.set_session_auto_reply(chat_id, True)

    return {"code": 0 if ok else -1, "message": "已加入白名单" if ok else "添加失败"}


@app.delete("/api/ai/whitelist")
def api_delete_whitelist(chat_id: str = Query(...)):
    """从白名单移除好友或群聊"""
    ok = whitelist_manager.remove(chat_id)
    ai_brain.memory.set_session_auto_reply(chat_id, False)
    return {"code": 0 if ok else -1, "message": "已移出白名单" if ok else "移除失败"}


@app.post("/api/ai/whitelist/toggle")
def api_toggle_whitelist(payload: dict = Body(...)):
    """开启或关闭白名单过滤模式"""
    enabled = bool(payload.get("enabled", True))
    ok = whitelist_manager.set_enabled(enabled)
    return {"code": 0 if ok else -1, "enabled": enabled}


@app.post("/api/ai/generate_suggestions")
def api_generate_suggestions(payload: dict = Body(...)):
    """为当前聊天生成 3 种不同风格的回复候选建议（融合多轮上下文）"""
    chat_id = payload.get("chat_id", "")
    text = payload.get("text", "")
    sender_name = payload.get("sender_name", "")
    instruction = payload.get("custom_instruction", "")

    # 获取当前账号的最近数据库历史消息作为多轮上下文
    history_msgs = []
    reader = get_reader_for_account(None)
    if reader and hasattr(reader, "db") and reader.db and chat_id:
        try:
            from core.ai_config import load_ai_settings
            c_cfg = load_ai_settings()
            context_count = int(c_cfg.get("context_messages_count", 15))
            history_msgs = reader.db.get_messages(chat_id, limit=context_count) or []
        except Exception as e:
            print(f"[API] 获取建议上下文失败: {e}", flush=True)

    suggestions = ai_brain.generate_suggestions(
        chat_id=chat_id,
        incoming_text=text,
        sender_name=sender_name,
        custom_instruction=instruction,
        history_messages=history_msgs,
    )
    return {"code": 0, "data": suggestions}


@app.post("/api/ai/send_message")
def api_send_message(payload: dict = Body(...)):
    """向微信目标会话（必先唤醒挂起微信并搜索定位再输入）发送消息"""
    text = payload.get("text", "").strip()
    target_name = payload.get("target_name", "").strip()
    chat_id = payload.get("chat_id", "").strip()
    force_search = bool(payload.get("force_search", True))
    if not text:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    if not target_name and chat_id:
        reader = get_reader_for_account(None)
        if reader and hasattr(reader, "get_display_name"):
            try:
                target_name = reader.get_display_name(chat_id)
            except Exception:
                pass

    ok, detail = message_sender.send_to_chat(
        text=text,
        target_name=target_name,
        force_search=force_search,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=detail)

    return {"code": 0, "message": "发送成功"}


# ─────────────────────────────────────────────────────────────
# 静态资源与主页挂载
# ─────────────────────────────────────────────────────────────

STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

ASSETS_DIR = os.path.join(STATIC_DIR, "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/")
def index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse("<h2>前端页面 static/index.html 正在生成中...</h2>")


if __name__ == "__main__":
    import uvicorn
    port = int(cfg.get("webPort", 8000))
    host = cfg.get("webHost", "0.0.0.0")
    print(f"\n========================================================")
    print(f"  微信 4.x 消息监控 WebUI 控制台启动")
    print(f"  本地访问地址: http://127.0.0.1:{port}")
    print(f"  局域网访问:   http://0.0.0.0:{port}")
    print(f"========================================================\n")
    uvicorn.run(app, host=host, port=port, log_level="info")
