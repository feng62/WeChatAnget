# -*- coding: utf-8 -*-
"""微信改过「文件保存位置」后图片/视频识别找不到文件 —— 只读兜底与全档位回溯补丁。

参考自 whale_gril 架构并在其基础上扩展增强对视频封面与跨盘视频的探测支持。
"""

from __future__ import annotations

import glob
import os
import re
import time
from typing import Callable, List, Optional

DEFAULT_ROOT_NAMES = ("xwechat_files", "WeChat Files", "xwechat_files_data")
DEFAULT_DRIVES = "CDEFGHIJK"
CACHE_TTL = 300.0


def _norm(path):
    try:
        return os.path.normcase(os.path.abspath(path))
    except (TypeError, ValueError):
        return ""


def data_roots(db, root_names=DEFAULT_ROOT_NAMES, drives=DEFAULT_DRIVES,
               extra_data_roots=None) -> List[str]:
    """列出所有可能装着账号目录的「数据根」（本身含 <账号>/db_storage 的那一层）。"""
    roots = []
    seen = set()

    def add(p):
        if not p or not os.path.isdir(p):
            return
        key = _norm(p)
        if not key or key in seen:
            return
        seen.add(key)
        roots.append(p)

    # 当前绑定的数据根排第一
    add(getattr(db, "db_dir", ""))
    for p in (extra_data_roots or []):
        add(p)

    letters = (drives or "").upper()
    if letters:
        for letter in letters:
            root = letter + ":\\"
            if not os.path.isdir(root):
                continue
            for name in root_names:
                add(os.path.join(root, name))

    try:
        import psutil
        for part in psutil.disk_partitions(all=False):
            mp = str(part.mountpoint or "")
            if not mp or not os.path.isdir(mp):
                continue
            for name in root_names:
                add(os.path.join(mp, name))
    except Exception:
        pass

    return roots


def attach_dirs(db, root_names=DEFAULT_ROOT_NAMES, drives=DEFAULT_DRIVES,
                extra_data_roots=None) -> List[str]:
    """所有 `msg/attach` 目录，当前账号的排第一。"""
    out = []
    seen = set()

    def add(p):
        if not p or not os.path.isdir(p):
            return
        key = _norm(p)
        if not key or key in seen:
            return
        seen.add(key)
        out.append(p)

    add(os.path.join(getattr(db, "account_dir", ""), "msg", "attach"))
    for root in data_roots(db, root_names, drives, extra_data_roots):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            add(os.path.join(root, name, "msg", "attach"))
    return out


def video_dirs(db, root_names=DEFAULT_ROOT_NAMES, drives=DEFAULT_DRIVES,
               extra_data_roots=None) -> List[str]:
    """所有 `msg/video` 目录，当前账号的排第一。"""
    out = []
    seen = set()

    def add(p):
        if not p or not os.path.isdir(p):
            return
        key = _norm(p)
        if not key or key in seen:
            return
        seen.add(key)
        out.append(p)

    add(os.path.join(getattr(db, "account_dir", ""), "msg", "video"))
    for root in data_roots(db, root_names, drives, extra_data_roots):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            add(os.path.join(root, name, "msg", "video"))
    return out


def install_media_fallback(dl, db, log=None, root_names=DEFAULT_ROOT_NAMES,
                           drives=DEFAULT_DRIVES, extra_data_roots=None):
    """
    给 MediaDownloader 实例装上图片与视频目录跨盘/旧目录全档位兜底补丁。
    """
    _log = log or (lambda *a, **k: None)
    cache = {"dirs": [], "video_dirs": [], "ts": 0.0}

    def dirs():
        now = time.time()
        if cache["dirs"] and (now - cache["ts"]) < CACHE_TTL:
            return cache["dirs"]
        cache["dirs"] = attach_dirs(db, root_names, drives, extra_data_roots)
        cache["video_dirs"] = video_dirs(db, root_names, drives, extra_data_roots)
        cache["ts"] = now
        return cache["dirs"]

    def vdirs():
        dirs()
        return cache["video_dirs"]

    installed = 0
    orig_image_files = getattr(dl, "_image_files", None)
    orig_probe = getattr(dl, "_probe_ct", None)
    orig_templates = getattr(dl, "_collect_templates", None)
    orig_download_video = getattr(dl, "download_video", None)

    # 1. 图片跨目录与旧位置匹配兜底
    if callable(orig_image_files):
        def image_files(user, md5):
            files = orig_image_files(user, md5)
            if files:
                return files
            want = {
                md5 + "_h.dat": "original",
                md5 + ".dat": "mid",
                md5 + "_t.dat": "thumb",
            }
            try:
                chat = dl._chat_md5(user)
            except Exception:
                return files

            for root in dirs():
                base = os.path.join(root, chat)
                if not os.path.isdir(base):
                    continue
                for dirpath, _dirnames, names in os.walk(base):
                    for f in names:
                        tier = want.get(f)
                        if tier and tier not in files:
                            p = os.path.join(dirpath, f)
                            try:
                                files[tier] = (p, os.path.getsize(p))
                            except OSError:
                                continue
                if files:
                    _log("[!] 图片不在当前账号目录，已从历史/跨盘目录匹配: %s" % base)
                    break
            return files

        dl._image_files = image_files
        installed += 1

    # 2. 图片探针/校验样本跨目录兜底
    if callable(orig_probe):
        def probe_ct(dat_path=None):
            got = orig_probe(dat_path)
            if got or dat_path:
                return got
            for root in dirs():
                hits = glob.glob(os.path.join(root, "*", "*", "Img", "*.dat"))
                if hits:
                    _log("[!] 当前目录缺少图片样本，改用历史目录样本校验密钥: %s" % root)
                    return orig_probe(hits[0])
            return got

        dl._probe_ct = probe_ct
        installed += 1

    # 3. 模板匹配样本兜底
    if callable(orig_templates):
        def collect_templates(limit=32, keep=16):
            hits = orig_templates(limit, keep)
            if hits:
                return hits
            out = []
            for root in dirs():
                out.extend(glob.glob(os.path.join(root, "*", "*", "Img", "*_t.dat")))
            out.sort(key=lambda p: (os.path.getmtime(p) if os.path.exists(p) else 0), reverse=True)
            return out[:keep]

        dl._collect_templates = collect_templates
        installed += 1

    # 4. 视频与封面跨目录探测增强
    def download_video_enhanced(user: str, local_id: int, save_dir: Optional[str] = None,
                                shard: Optional[str] = None) -> Optional[dict]:
        """
        增强版视频提取：
        若本地存在完整 .mp4，返回 {"type": "video", "path": mp4_path}；
        若微信客户端尚未点击下载该视频，返回已落地的封面缩略图 {"type": "thumb", "path": thumb_path}。
        """
        row = dl.db.get_message_row(user, local_id, local_type=43, shard=shard)
        if not row or row.get("local_type") != 43:
            return None

        pi = row.get("packed_info")
        if not isinstance(pi, bytes):
            return None

        m = re.search(rb"([0-9a-fA-F]{32})", pi)
        vid = m.group(1).decode().lower() if m else None
        if not vid:
            return None

        found_thumb = None
        for vdir in vdirs():
            if not os.path.isdir(vdir):
                continue
            for root, _, files in os.walk(vdir):
                for f in files:
                    # 匹配完整 mp4
                    if f == vid + ".mp4":
                        out = dl._out(save_dir, "%s_%s.mp4" % (user, local_id))
                        try:
                            with open(out, "wb") as w, open(os.path.join(root, f), "rb") as r:
                                w.write(r.read())
                            return {"type": "video", "path": out}
                        except Exception:
                            return {"type": "video", "path": os.path.join(root, f)}

                    # 匹配封面 thumb.jpg
                    if not found_thumb and (f == vid + "_thumb.jpg" or f == vid + ".jpg"):
                        found_thumb = os.path.join(root, f)

        if found_thumb:
            out = dl._out(save_dir, "%s_%s_thumb.jpg" % (user, local_id))
            try:
                with open(out, "wb") as w, open(found_thumb, "rb") as r:
                    w.write(r.read())
                return {"type": "thumb", "path": out}
            except Exception:
                return {"type": "thumb", "path": found_thumb}

        return None

    dl.download_video_enhanced = download_video_enhanced
    installed += 1

    return installed
