# -*- coding: utf-8 -*-
"""
微信 4.x 内存密钥提取、SQLite 只读解密与多账号并发增量监听引擎

【核心实现机制】：
1. 内存密钥提取与防漂移：
   借助 wechatauto-replica 库的 WeChatDB 类，在微信处于已登录状态时，
   直接从对应 PID 内存中提取 SQLite 动态解密密钥，无需注入 DLL，安全不封号；
   针对微信多开（多账号并存）场景，阻断跨账号自动漂移与覆盖，确保各账号隔离。
2. 数据库只读访问与极速秒开：
   对已验证的会话表（session）、联系人表（contact）与消息表（message）密钥进行本地持久化，
   启动时直接复用有效密钥校验（0.01s 秒级就绪），避免每次启动重复耗时全内存扫描。
3. 多账号独立增量轮询：
   每个已登录账号拥有独立的 SQLite 映射工作区与高频轮询线程（interval=0.4s），
   互不干扰，不产生 Windows 文件锁冲突（PermissionError 13）。
4. 综合消息清洗与多媒体处理：
   配合 MediaProcessor 进行去重、防刷屏、长截图切片（wxgf->JPEG）与音频转码（Silk->WAV）。
"""

import os
import sys
import threading
import time
from typing import Callable, Dict, List, Optional

from .db_locator import find_all_accounts, resolve_db_dir
from .media_fallback import install_media_fallback
from .media_processor import MediaProcessor


def _patch_wechatauto_for_multi_account():
    """
    对 wechatauto.db.WeChatDB 进行安全性加固猴子补丁：
    1. 彻底禁用 _try_other_accounts 和 _select_account_by_keys，防止在多开环境下
       某个账号因部分辅助库未加载而强行篡改实例的目标账号目录；
    2. 优化 _load_or_extract_keys：当本地已保存的 keys.json 能够解开核心消息库
       (message_*.db 与 session.db) 时，跳过冗长且昂贵的全内存扫描，实现 0.01 秒极速启动。
    """
    try:
        from wechatauto.db import WeChatDB
    except ImportError:
        return

    # 1. 禁用跨账号漂移
    WeChatDB._try_other_accounts = lambda self: False
    WeChatDB._select_account_by_keys = lambda self, cands: False

    # 2. 核心库优先加载优化
    if not getattr(WeChatDB, "_is_multi_account_patched", False):
        orig_load = WeChatDB._load_or_extract_keys

        def _fast_load_keys(self, master_key: Optional[str] = None) -> None:
            if master_key:
                return orig_load(self, master_key=master_key)

            # 优先从本地 keys.json 加载
            cache_paths = [self.keys_file, self.keys_file + ".bak"]
            sf = self._stable_key_file()
            if sf:
                cache_paths.insert(0, sf)

            for cp in cache_paths:
                if not os.path.exists(cp):
                    continue
                for rel, key in self._load_key_cache(cp).items():
                    self._keys.setdefault(rel, key)

            # 只保留能通过页1 校验的有效密钥
            valid: Dict[str, bytes] = {}
            for rel, k in self._keys.items():
                try:
                    if self._key_works(rel):
                        valid[rel] = k
                except Exception:
                    continue
            self._keys = valid

            # 检查关键核心库是否均已有可用密钥
            has_session = any("session" in rel for rel in valid)
            has_message = any("message" in rel for rel in valid)
            has_contact = any("contact" in rel for rel in valid)

            if has_session and has_message and has_contact:
                # 核心数据库全部就绪，无需再扫描其他辅助库（如 wcfinder/newtips 等未打开功能的库）
                self.unkeyed = [
                    rel for rel, _, _ in self._db_files if not self._key_works(rel)
                ]
                self._save_keys()
                return

            # 如果本地密钥不全，回退到原版内存提取
            orig_load(self, master_key=master_key)

        WeChatDB._load_or_extract_keys = _fast_load_keys

        # 3. 增强 SQLite 解密并发锁与文件冲突安全防护（消除 PermissionError 13）
        orig_open_unlocked = WeChatDB._open_unlocked

        def _safe_open_unlocked(self, rel: str):
            for attempt in range(4):
                try:
                    return orig_open_unlocked(self, rel)
                except PermissionError:
                    time.sleep(0.08 * (attempt + 1))
            # 持续被其他进程或连接锁定，安全复用当前已就绪的 SQLite 解密副本
            dst = os.path.join(self.workdir, rel.replace(os.sep, "__"))
            if os.path.exists(dst):
                import sqlite3
                conn = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                conn.text_factory = lambda b: b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b)
                return conn
            raise

        WeChatDB._open_unlocked = _safe_open_unlocked
        WeChatDB._is_multi_account_patched = True


class WeChatDatabaseReader:
    """单个微信账号的 4.x 数据库连接与只读操作封装器"""

    def __init__(
        self,
        db_dir: Optional[str] = None,
        account: Optional[str] = None,
        target_pid: Optional[int] = None,
        media_cache_dir: str = "media-cache",
    ):
        self.db_dir = db_dir or resolve_db_dir(verbose=False)
        if not self.db_dir:
            raise RuntimeError("未能找到微信 4.x 数据目录！请确认微信已登录，或在 config.json 中配置 dbDir。")

        self.account = account
        self.target_pid = target_pid
        self.media_cache_dir = os.path.abspath(media_cache_dir)
        os.makedirs(self.media_cache_dir, exist_ok=True)
        self.processor = MediaProcessor(media_cache_dir=self.media_cache_dir)

        # 确保应用多账号猴子补丁
        _patch_wechatauto_for_multi_account()

        try:
            from wechatauto import MediaDownloader, WeChatDB
        except ImportError as e:
            raise ImportError(
                "缺少 wechatauto-replica 核心依赖！\n"
                "请在 Python 环境中执行: pip install wechatauto-replica\n"
                f"错误详情: {e}"
            )

        from core.path_utils import PROJECT_ROOT
        root_dir = PROJECT_ROOT
        # 稳定密钥共享存储，确保跨进程复用有效解密密钥
        stable_keys_dir = os.path.join(root_dir, "data", "db_cache", self.account or "default")
        os.makedirs(stable_keys_dir, exist_ok=True)
        stable_keys_file = os.path.join(stable_keys_dir, "keys.json")

        # 进程隔离独立解密工作区，杜绝多进程争抢 SQLite 锁导致 PermissionError 13
        cache_subdir = f"{self.account or 'default'}_{os.getpid()}"
        self.workdir = os.path.join(root_dir, "data", "db_cache", cache_subdir)
        os.makedirs(self.workdir, exist_ok=True)

        _db_box = {}

        def _open_work():
            try:
                # 如果指定了 target_pid，限定 WeChatDB 内存扫描仅针对该目标进程
                orig_find = WeChatDB._find_weixin_pids
                if self.target_pid:
                    WeChatDB._find_weixin_pids = lambda self_inner: [self.target_pid]

                try:
                    _db_box["db"] = WeChatDB(
                        db_dir=self.db_dir,
                        account=self.account,
                        workdir=self.workdir,
                        keys_file=stable_keys_file,
                    )
                finally:
                    WeChatDB._find_weixin_pids = orig_find
            except BaseException as exc:
                _db_box["err"] = exc

        th = threading.Thread(target=_open_work, daemon=True)
        th.start()
        th.join(timeout=60)
        if th.is_alive():
            raise TimeoutError(
                f"打开微信账号 [{self.account or '默认'}] 数据库超时！\n"
                "常见原因：该微信进程尚未登录进入主界面，内存中不存在解密密钥。"
            )
        if _db_box.get("err"):
            raise _db_box["err"]

        self.db = _db_box.get("db")
        self.account = self.db.account
        self.self_wxid = self.db.wxid

        # 读取当前账号登录人信息
        try:
            self.self_info = self.db.get_self_info() or {}
            self.self_name = (
                self.self_info.get("nick_name")
                or self.self_info.get("remark")
                or self.self_wxid
            )
        except Exception:
            self.self_info = {}
            self.self_name = self.self_wxid

        # 初始化媒体下载器并应用跨目录兜底补丁
        self.downloader = MediaDownloader(self.db, save_dir=self.media_cache_dir)
        # 绑定持久化的图片密钥存储路径到账号公共缓存目录，跨多进程共享已提取的图片密钥
        shared_img_key_path = os.path.join(stable_keys_dir, "image_keys.json")
        self.downloader._key_store = lambda: shared_img_key_path

        # 封装 _scan_aes_key 避免在 Web 请求或无大图查看时阻塞 120 秒
        orig_scan = getattr(self.downloader, "_scan_aes_key", None)
        if callable(orig_scan):
            self.downloader._scan_aes_key = lambda monitor=False, **kw: orig_scan(monitor=False, **kw)

        try:
            install_media_fallback(self.downloader, self.db, log=lambda *a: None)
        except Exception:
            pass

        # 昵称与群名缓存字典
        self.name_cache: Dict[str, str] = {}
        self.sessions: Dict[str, Dict] = {}
        self._refresh_sessions()

    def _refresh_sessions(self):
        """刷新会话列表缓存"""
        try:
            for s in self.db.get_sessions(limit=500):
                self.sessions[s["username"]] = s
        except Exception:
            pass

    def get_display_name(self, username: str) -> str:
        """根据 wxid 或群 chatroom id 获取人类可读的昵称或群聊名称"""
        if not username:
            return ""
        if username in self.name_cache:
            return self.name_cache[username]

        name = ""
        try:
            if username.endswith("@chatroom"):
                name = self.db.group_id_to_name(username) or ""
                if not name and username in self.sessions:
                    name = self.sessions[username].get("last_sender") or ""
            else:
                name = self.db.get_nickname(username) or ""
        except Exception:
            name = ""

        name = name or username
        self.name_cache[username] = name
        return name

    def download_image_bytes(self, username: str, local_id: int, shard: Optional[str] = None) -> Optional[Dict]:
        """按优先级下载图片（原图 > 高清/压缩图 > 默认下发档 > 缩略图全档位自动降级），并交由 MediaProcessor 转码"""
        path = None
        for tier in ("best", "full", None, "thumb"):
            try:
                path = self.downloader.download_image(username, int(local_id), tier=tier, shard=shard)
                if path and os.path.exists(path):
                    break
            except Exception:
                path = None

        if not path or not os.path.exists(path):
            return None

        try:
            with open(path, "rb") as f:
                raw = f.read()
            clean_bytes, ext, sliced_parts = self.processor.process_image(raw)
            return {
                "local_path": path,
                "clean_bytes": clean_bytes,
                "ext": ext,
                "sliced_parts": sliced_parts,
                "size_kb": len(raw) // 1024,
            }
        except Exception as e:
            return None

    def download_video_media(self, username: str, local_id: int, shard: Optional[str] = None) -> Optional[Dict]:
        """
        下载视频或其封面缩略图：
        若本地有 MP4 则返回 {"type": "video", "path": mp4_path}；
        若微信客户端尚未点击下载该视频，返回已落地的封面缩略图 {"type": "thumb", "path": thumb_path}。
        """
        try:
            fn = getattr(self.downloader, "download_video_enhanced", None)
            if callable(fn):
                res = fn(username, int(local_id), shard=shard)
                if res and os.path.exists(res.get("path", "")):
                    return res
            # 原生方法兜底
            vpath = self.downloader.download_video(username, int(local_id), shard=shard)
            if vpath and os.path.exists(vpath):
                return {"type": "video", "path": vpath}
            return None
        except Exception as e:
            print(f"[{self.self_name}] 读取视频文件失败: {e}", flush=True)
            return None

    def download_voice_wav(self, username: str, local_id: int, shard: Optional[str] = None) -> Optional[Dict]:
        """下载语音 Silk 文件并转码为标准 WAV 音频"""
        try:
            silk_path = self.downloader.download_voice(username, int(local_id), shard=shard)
            if not silk_path or not os.path.exists(silk_path):
                return None
            return self.processor.decode_silk_to_wav(silk_path)
        except Exception as e:
            print(f"[{self.self_name}] 读取语音文件失败: {e}", flush=True)
            return None


class MessageIncrementalListener:
    """单个账号的增量消息监听引擎（0.4 秒轮询 sort_seq）"""

    def __init__(
        self,
        reader: WeChatDatabaseReader,
        interval: float = 0.4,
        ignore_self: bool = False,
        duplicate_window_sec: float = 30.0,
    ):
        self.reader = reader
        self.interval = interval
        self.ignore_self = ignore_self
        self.duplicate_window_sec = duplicate_window_sec

        self.start_ts = time.time()
        self._running = False
        self._native_listener = None
        self._guard_lock = threading.Lock()
        self._recent_dup = {}
        self.callbacks: List[Callable[[Dict], None]] = []

    def on_message(self, callback: Callable[[Dict], None]):
        """注册收到新消息时的业务回调函数"""
        self.callbacks.append(callback)

    def _is_duplicate(self, chat_id: str, sender_id: str, content: str) -> bool:
        """防重复投递 / 刷屏守护"""
        now = time.time()
        key = (str(chat_id), str(sender_id), str(content).strip())
        with self._guard_lock:
            last = self._recent_dup.get(key, 0)
            self._recent_dup[key] = now
            if len(self._recent_dup) > 600:
                for k, v in list(self._recent_dup.items()):
                    if now - v > 600:
                        self._recent_dup.pop(k, None)
            return (now - last) < self.duplicate_window_sec

    def _dispatch(self, raw_msg: Dict):
        """核心消息分发与标准化管线"""
        try:
            username = raw_msg.get("username") or ""
            if not username:
                return

            sender = raw_msg.get("sender_username") or ""
            is_group = username.endswith("@chatroom")

            # 判断消息方向（发出还是收到）
            is_from_me = (sender == self.reader.self_wxid)
            if not is_group and not sender:
                # 在私聊数据库记录中，自己发送的消息 sender_username 可能为空或无 real_sender_id
                # 微信 4.x 数据库中，发送者为自己时 sender_id 通常为 0
                if raw_msg.get("sender_id") == 0:
                    is_from_me = True

            if is_from_me and self.ignore_self:
                return

            mtype = raw_msg.get("type") or "未知"
            raw_content = (raw_msg.get("content") or "").strip()
            chat_title = self.reader.get_display_name(username)

            if is_from_me:
                sender_name = self.reader.self_name
                direction = "outgoing"
            else:
                sender_name = self.reader.get_display_name(sender or username) or ("群友" if is_group else chat_title)
                direction = "incoming"

            # 1. 过滤微信官方系统通知、公众号推文
            if not is_from_me and self.reader.processor.is_system_notice(username, sender_name, raw_content):
                return

            # 2. 表情包拦截
            if self.reader.processor.is_emoji_message(mtype, raw_content):
                msg_obj = {
                    "account_name": self.reader.self_name,
                    "account_wxid": self.reader.self_wxid,
                    "direction": direction,
                    "is_from_me": is_from_me,
                    "msg_id": f"{username}:{raw_msg.get('shard') or ''}:{raw_msg.get('local_id')}",
                    "chat_id": username,
                    "chat_title": chat_title,
                    "chat_type": "group" if is_group else "private",
                    "sender_id": sender,
                    "sender_name": sender_name,
                    "msg_type": "表情包",
                    "text": "[表情/动画表情]",
                    "media": None,
                    "create_time": float(raw_msg.get("create_time") or time.time()),
                }
                for cb in self.callbacks:
                    cb(msg_obj)
                return

            # 3. 消息去重
            if mtype == "文本" and self._is_duplicate(username, sender or self.reader.self_wxid, raw_content):
                return

            # 4. 多媒体深度处理
            processed_text = raw_content
            media_info = None

            if mtype == "图片":
                local_id = raw_msg.get("local_id")
                shard = raw_msg.get("shard")
                img_data = self.reader.download_image_bytes(username, local_id, shard=shard)
                media_info = {
                    "type": "image",
                    "url": f"/api/media/image?account={self.reader.account}&chat_id={username}&local_id={local_id}&shard={shard}",
                    "local_path": img_data["local_path"] if img_data else "",
                    "ext": img_data["ext"] if img_data else ".jpg",
                    "size_kb": img_data["size_kb"] if img_data else 0,
                    "slice_count": len(img_data["sliced_parts"]) if img_data else 0,
                }
                processed_text = "[图片]"

            elif mtype == "语音":
                voice_data = self.reader.download_voice_wav(
                    username, raw_msg.get("local_id"), shard=raw_msg.get("shard")
                )
                if voice_data:
                    media_info = {
                        "type": "voice",
                        "url": f"/api/media/voice?account={self.reader.account}&chat_id={username}&local_id={raw_msg.get('local_id')}&shard={raw_msg.get('shard')}",
                        "wav_path": voice_data["wav_path"],
                        "seconds": voice_data["seconds"],
                    }
                    processed_text = f"[语音] (时长: {voice_data['seconds']}s, 转码文件: {os.path.basename(voice_data['wav_path'])})"

            elif mtype == "视频":
                local_id = raw_msg.get("local_id")
                shard = raw_msg.get("shard")
                v_res = self.reader.download_video_media(username, local_id, shard=shard)
                media_info = {
                    "type": "video",
                    "url": f"/api/media/video?account={self.reader.account}&chat_id={username}&local_id={local_id}&shard={shard}",
                    "has_mp4": bool(v_res and v_res.get("type") == "video"),
                }
                processed_text = "[视频]"

            else:
                # 检查是否为引用消息或链接/卡片
                if "<refermsg" in raw_content or "<type>57</type>" in raw_content:
                    ref_data = self.reader.processor.parse_refer_msg(raw_content)
                    if ref_data:
                        mtype = "引用消息"
                        processed_text = ref_data.get("title", "")
                        media_info = {"type": "refer", **ref_data}
                elif "<appmsg" in raw_content:
                    card_data = self.reader.processor.parse_xml_card(raw_content)
                    if card_data:
                        mtype = "链接卡片"
                        processed_text = card_data["summary"]
                        media_info = {"type": "card", **card_data}

            # 5. 构造统一规范结构体
            normalized_msg = {
                "account_name": self.reader.self_name,
                "account_wxid": self.reader.self_wxid,
                "direction": direction,
                "is_from_me": is_from_me,
                "msg_id": f"{username}:{raw_msg.get('shard') or ''}:{raw_msg.get('local_id')}",
                "chat_id": username,
                "chat_title": chat_title,
                "chat_type": "group" if is_group else "private",
                "sender_id": sender,
                "sender_name": sender_name,
                "msg_type": mtype,
                "text": processed_text,
                "media": media_info,
                "sort_seq": int(raw_msg.get("sort_seq") or (time.time() * 1000)),
                "create_time": float(raw_msg.get("create_time") or time.time()),
            }

            # 6. 分发给回调处理函数
            for cb in self.callbacks:
                cb(normalized_msg)

        except Exception as e:
            print(f"[{self.reader.self_name}] 消息处理异常: {e}", flush=True)

    def start(self):
        """启动监听器"""
        if self._running:
            return
        self._running = True

        from wechatauto.db import Listener
        watermark_file = os.path.join(self.reader.workdir, "listener_watermark.json")
        self._native_listener = Listener(self.reader.db, interval=self.interval, watermark_file=watermark_file)
        self._native_listener.add_all(lambda msg, l: self._dispatch(msg))
        self._native_listener.start()

    def stop(self):
        """停止监听器"""
        self._running = False
        if self._native_listener:
            try:
                self._native_listener.stop()
            except Exception:
                pass


class MultiAccountListenerManager:
    """多账号并发监听管理器：统一纳管多开微信实例的消息监听与生命周期"""

    def __init__(
        self,
        db_dir: Optional[str] = None,
        poll_interval: float = 0.4,
        ignore_self: bool = False,
        media_cache_dir: str = "media-cache",
    ):
        self.db_dir = db_dir or resolve_db_dir(verbose=False)
        self.poll_interval = poll_interval
        self.ignore_self = ignore_self
        self.media_cache_dir = media_cache_dir

        self.readers: List[WeChatDatabaseReader] = []
        self.listeners: List[MessageIncrementalListener] = []
        self.callbacks: List[Callable[[Dict], None]] = []

    def on_message(self, callback: Callable[[Dict], None]):
        """注册全局消息回调（所有账号收到的消息都会通过此回调输出）"""
        self.callbacks.append(callback)

    def _broadcast_message(self, msg: Dict):
        for cb in self.callbacks:
            try:
                cb(msg)
            except Exception as e:
                print(f"[MultiAccountManager] 业务回调抛出异常: {e}", flush=True)

    def discover_and_mount(self) -> List[Dict]:
        """
        自动发现系统所有微信账号目录与运行中的进程，并挂载解密数据库。
        返回已就绪账号的摘要列表。
        """
        accounts = find_all_accounts(self.db_dir)
        if not accounts:
            raise RuntimeError(f"未在目录 {self.db_dir} 下发现任何微信账号数据目录！")

        mounted_accounts = []
        from core.path_utils import PROJECT_ROOT
        root_dir = PROJECT_ROOT
        for item in accounts:
            acct = item["account"]
            pid = item.get("pid")
            is_running = item.get("is_running", False)

            # 如果该账号未绑定运行中的微信进程，且没有有效本地缓存，直接跳过避免报错
            if not is_running:
                cache_file = os.path.join(root_dir, "data", "db_cache", acct, "keys.json")
                if not os.path.exists(cache_file) or os.path.getsize(cache_file) < 10:
                    print(f"[-] 忽略未登录的离线账号目录: [{acct}]", flush=True)
                    continue

            try:
                reader = WeChatDatabaseReader(
                    db_dir=self.db_dir,
                    account=acct,
                    target_pid=pid,
                    media_cache_dir=self.media_cache_dir,
                )

                # 校验核心数据库是否成功获取到密钥（必须能解密 session 和 message 核心库）
                has_session = any("session" in k for k in reader.db._keys)
                has_message = any("message" in k for k in reader.db._keys)
                if not (has_session and has_message):
                    print(f"[-] 账号 [{acct}] 缺少核心数据库解密密钥（当前未在微信登录），跳过实时监听。", flush=True)
                    continue

                listener = MessageIncrementalListener(
                    reader=reader,
                    interval=self.poll_interval,
                    ignore_self=self.ignore_self,
                )
                listener.on_message(self._broadcast_message)

                self.readers.append(reader)
                self.listeners.append(listener)

                mounted_accounts.append({
                    "account": acct,
                    "name": reader.self_name,
                    "wxid": reader.self_wxid,
                    "pid": pid,
                    "keys_count": len(reader.db._keys),
                })
            except Exception as e:
                print(f"[!] 挂载账号 [{acct}] 失败 (PID={pid}): {e}", flush=True)

        if not self.readers:
            raise RuntimeError("未能成功挂载任何已登录的微信账号数据库！请检查微信客户端是否已登录。")

        return mounted_accounts

    def start(self):
        """同时启动所有账号的增量监听线程"""
        started = []
        for listener in self.listeners:
            try:
                listener.start()
                started.append(listener)
            except Exception as e:
                print(f"[!] 账号 [{listener.reader.self_name}] 启动增量监听器失败: {e}", flush=True)
        self.listeners = started

    def stop(self):
        """停止所有账号的增量监听器"""
        for listener in self.listeners:
            try:
                listener.stop()
            except Exception:
                pass
