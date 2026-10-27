# -*- coding: utf-8 -*-
"""
微信多媒体消息深度识别、转码与内容过滤模块

【核心功能实现】：
1. 图片转码：微信 4.x 图片多为 wxgf（HEVC私有容器），本模块自动探查 ffmpeg 环境，将其转码为标准 JPEG；
2. 长截图智能切片：对手机竖向超长截图，自适应切成 2~3 段并带 8% 重叠缓冲区（Overlap），避免文字断层；
3. 语音解码：通过 pysilk 将 Silk 编码音频转码为标准 PCM/WAV（16kHz，16bit 单声道），便于接入 ASR 识别；
4. 消息过滤与卡片解析：拦截 <emoji> 表情包、拍一拍等系统提示；对分享卡片正则提取 XML 中的 <url> 与 <title>。
"""

import io
import os
import re
import shutil
import subprocess
import time
import wave
from typing import Dict, List, Optional, Tuple

# 常见 ffmpeg 预设检索目录
FFMPEG_CANDIDATE_DIRS = [
    r"C:\ffmpeg\bin",
    r"D:\ffmpeg\bin",
    r"E:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
    r"D:\Program Files\ffmpeg\bin",
    os.path.expanduser(r"~\ffmpeg\bin"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\ffmpeg\bin"),
]

# 系统号、服务号通知与链接正则
SYSTEM_URL_RE = re.compile(r"<a\s+href=|weixin://|&lt;a\s+href=", re.I)
SYSTEM_SENDER_NAMES = {
    "微信团队", "微信支付", "服务通知", "订阅号消息", "文件传输助手",
    "微信运动", "微信公众平台", "腾讯客服", "微信安全中心", "微信广告",
}


def ensure_ffmpeg() -> bool:
    """确保 ffmpeg 在环境变量 PATH 中"""
    if shutil.which("ffmpeg"):
        return True
    for d in FFMPEG_CANDIDATE_DIRS:
        exe = os.path.join(d, "ffmpeg.exe")
        if os.path.isfile(exe):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            return True
    return False


class MediaProcessor:
    def __init__(self, media_cache_dir: str = "media-cache", voice_sample_rate: int = 16000):
        self.media_cache_dir = os.path.abspath(media_cache_dir)
        os.makedirs(self.media_cache_dir, exist_ok=True)
        self.voice_sample_rate = voice_sample_rate
        self.has_ffmpeg = ensure_ffmpeg()

    # ========================== 1. 图片处理 ==========================

    def convert_wxgf_to_jpg(self, raw_bytes: bytes) -> Optional[bytes]:
        """
        利用 ffmpeg 将微信 wxgf (HEVC 容器) 字节流转换为标准 JPEG 字节流
        """
        if not self.has_ffmpeg:
            self.has_ffmpeg = ensure_ffmpeg()
            if not self.has_ffmpeg:
                print("[MediaProcessor 警告] 未找到 ffmpeg，无法直接转码 wxgf 图片")
                return None

        # 从 wxgf 容器中提取 HEVC Annex-B 裸流（首个 NALU 起始码起）
        start = raw_bytes.find(b"\x00\x00\x00\x01")
        hevc = raw_bytes[start:] if start >= 0 else raw_bytes

        try:
            # 启动 ffmpeg 进程，通过管道进行流式转码提取第 1 帧
            p = subprocess.Popen(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "hevc", "-i", "pipe:0", "-frames:v", "1", "-f", "image2", "-vcodec", "mjpeg", "pipe:1"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            out, err = p.communicate(input=hevc, timeout=15)
            if p.returncode == 0 and out and out[:3] == b"\xff\xd8\xff":
                return out
            else:
                # 管道若因格式问题失败，临时写文件兜底
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    src = os.path.join(td, "in.hevc")
                    dst = os.path.join(td, "out.jpg")
                    with open(src, "wb") as f:
                        f.write(hevc)
                    r = subprocess.run(
                        ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-frames:v", "1", dst],
                        capture_output=True, timeout=15
                    )
                    if r.returncode == 0 and os.path.exists(dst):
                        with open(dst, "rb") as f:
                            res = f.read()
                        if res and res[:3] == b"\xff\xd8\xff":
                            return res
                print(f"[MediaProcessor] wxgf 转码失败: {err.decode(errors='ignore')}")
                return None
        except Exception as e:
            print(f"[MediaProcessor] wxgf 转码异常: {e}")
            return None

    def process_image(self, raw_bytes: bytes, filename_hint: str = "image") -> Tuple[Optional[bytes], str, List[bytes]]:
        """
        处理图片原始字节：
        1. 探测真实文件格式（wxgf / png / jpeg / gif）并统一转码；
        2. 如果是竖版超长截图，自适应切成多段以便送入多模态大模型；
        
        返回值: (标准图片字节流, 格式扩展名, [切片字节流列表])
        """
        if not raw_bytes:
            return None, "", []

        # 1. 检查真实魔数并转码
        ext = ".jpg"
        clean_bytes = raw_bytes

        if raw_bytes[:4] == b"wxgf":
            # 微信特有的 wxgf (HEVC) 容器
            converted = self.convert_wxgf_to_jpg(raw_bytes)
            if not converted:
                return None, "wxgf_failed", []
            clean_bytes = converted
            ext = ".jpg"
        elif raw_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            ext = ".png"
        elif raw_bytes[:3] == b"\xff\xd8\xff":
            ext = ".jpg"
        elif raw_bytes[:3] == b"GIF":
            ext = ".gif"
        else:
            ext = ".jpg"

        # 2. 长截图智能切片分析
        sliced_parts: List[bytes] = []
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(clean_bytes))
            img.load()
            w, h = img.size

            # 判定标准：高宽比 > 2.2 且 绝对高度 > 1200 像素
            if w > 0 and (h / float(w)) > 2.2 and h > 1200:
                n = 3 if (h / float(w)) > 4.0 else 2
                overlap = int(h * 0.08)  # 8% 上下重叠区，防止文字正好被拦腰切断
                for i in range(n):
                    top = max(0, int(i * h / n) - (overlap if i > 0 else 0))
                    bottom = min(h, int((i + 1) * h / n) + (overlap if i < n - 1 else 0))
                    seg = img.crop((0, top, w, bottom)).convert("RGB")
                    buf = io.BytesIO()
                    seg.save(buf, format="JPEG", quality=88)
                    sliced_parts.append(buf.getvalue())
            else:
                # 普通图片统一以 JPEG/RGB 格式输出一张
                img_rgb = img.convert("RGB")
                buf = io.BytesIO()
                img_rgb.save(buf, format="JPEG", quality=88)
                sliced_parts.append(buf.getvalue())
        except Exception as e:
            # 如 PIL 出现异常，退回原转码字节
            sliced_parts = [clean_bytes]

        return clean_bytes, ext, sliced_parts

    # ========================== 2. 语音处理 ==========================

    def decode_silk_to_wav(self, silk_path: str, output_wav_path: Optional[str] = None) -> Optional[Dict]:
        """
        将微信 Silk 语音文件转码为标准 WAV 音频文件
        返回值：包含 wav 路径、音频秒数的字典，失败返回 None
        """
        if not os.path.exists(silk_path):
            return None

        try:
            import pysilk
        except ImportError:
            print("[MediaProcessor 提示] 缺少 pysilk (silk-python) 模块，无法将 Silk 语音解码为 WAV")
            print("  可运行: pip install silk-python 安装解码器")
            return None

        try:
            pcm_buf = io.BytesIO()
            with open(silk_path, "rb") as f:
                pysilk.decode(f, pcm_buf, self.voice_sample_rate)
            raw_pcm = pcm_buf.getvalue()

            seconds = len(raw_pcm) / float(self.voice_sample_rate * 2)  # 16bit = 2 bytes/sample
            if seconds < 0.2:
                return None  # 忽略无效短音频

            if not output_wav_path:
                output_wav_path = os.path.splitext(silk_path)[0] + ".wav"

            with wave.open(output_wav_path, "wb") as w:
                w.setnchannels(1)  # 单声道
                w.setsampwidth(2)  # 16-bit
                w.setframerate(self.voice_sample_rate)
                w.writeframes(raw_pcm)

            return {
                "wav_path": output_wav_path,
                "seconds": round(seconds, 2),
                "sample_rate": self.voice_sample_rate,
            }
        except Exception as e:
            print(f"[MediaProcessor] 语音转码异常: {e}")
            return None

    # ========================== 3. 消息过滤与卡片解析 ==========================

    @staticmethod
    def is_emoji_message(msg_type: str, content: str) -> bool:
        """判断是否为微信表情包（动画表情、自定义表情、带有 <emoji> 标签）"""
        if msg_type in ("表情", "动画表情"):
            return True
        if "<emoji" in (content or ""):
            return True
        return False

    @staticmethod
    def is_system_notice(username: str, nickname: str, content: str) -> bool:
        """过滤微信团队、微信支付、服务号通知、拍一拍提示等非真实对话消息"""
        c = str(content or "")
        if "拍了拍" in c and "<url>" not in c:
            return True
        if SYSTEM_URL_RE.search(c):
            return True
        if str(nickname or "").strip() in SYSTEM_SENDER_NAMES:
            return True
        if str(username or "").startswith("gh_"):
            return True
        return False

    @staticmethod
    def parse_refer_msg(content: str) -> Optional[Dict]:
        """解析微信引用/回复消息 (type 57 / refermsg)"""
        if not content or ("<refermsg" not in content and "<type>57</type>" not in content):
            return None

        # 去除群聊前缀 wxid_xxx:\n
        clean = re.sub(r'^[a-zA-Z0-9_\-]+:\s*\n?', '', content.strip())
        start = clean.find("<msg")
        if start < 0:
            start = clean.find("<?xml")
        if start >= 0:
            clean = clean[start:]

        title = ""
        refer_display = ""
        refer_user = ""
        refer_content = ""
        refer_type = 1

        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(clean)
            appmsg = root.find("appmsg") if root.tag != "appmsg" else root
            if appmsg is not None:
                title = (appmsg.findtext("title") or "").strip()
                refer = appmsg.find("refermsg")
                if refer is not None:
                    refer_display = (refer.findtext("displayname") or "").strip()
                    refer_user = (refer.findtext("chatusr") or "").strip()
                    refer_content = (refer.findtext("content") or "").strip()
                    try:
                        ref_t = refer.findtext("type")
                        if ref_t:
                            refer_type = int(ref_t)
                    except Exception:
                        pass
        except Exception:
            pass

        # 正则降级提取
        if not title:
            mt = re.search(r"<title>(.*?)</title>", clean, re.DOTALL)
            if mt:
                title = mt.group(1).strip()
        if not refer_content:
            mc = re.search(r"<refermsg>.*?<content>(.*?)</content>.*?</refermsg>", clean, re.DOTALL)
            if mc:
                refer_content = mc.group(1).strip()
        if not refer_display:
            md = re.search(r"<refermsg>.*?<displayname>(.*?)</displayname>.*?</refermsg>", clean, re.DOTALL)
            if md:
                refer_display = md.group(1).strip()
        if not refer_user:
            mu = re.search(r"<refermsg>.*?<chatusr>(.*?)</chatusr>.*?</refermsg>", clean, re.DOTALL)
            if mu:
                refer_user = mu.group(1).strip()

        # 清洗引用的正文
        refer_content = re.sub(r'^[a-zA-Z0-9_\-]+:\s*\n?', '', refer_content).strip()
        if not refer_content:
            if refer_type == 3:
                refer_content = "[图片]"
            elif refer_type == 43:
                refer_content = "[视频]"
            elif refer_type == 47:
                refer_content = "[动画表情]"
            elif refer_type == 49:
                refer_content = "[链接卡片/文件]"

        if not title and not refer_content:
            return None

        return {
            "title": title,
            "refer_display": refer_display or refer_user or "某人",
            "refer_user": refer_user,
            "refer_content": refer_content,
            "refer_type": refer_type,
            "summary": f"[引用] {title}" if title else "[引用消息]",
        }

    @staticmethod
    def parse_xml_card(content: str) -> Optional[Dict[str, str]]:
        """从微信分享卡片/链接的 XML 数据中提取真实网页标题与 URL（严格排除引用消息与空链接）"""
        if not content:
            return None
        # 如果是引用消息（type 57 或包含 refermsg），绝不是网页链接卡片
        if "<refermsg" in content or "<type>57</type>" in content:
            return None

        # 匹配合法的 http/https 链接
        mu = re.search(r"<url>(https?://[^\s<>\"]+)</url>", content, re.DOTALL | re.IGNORECASE)
        mt = re.search(r"<title>(.*?)</title>", content, re.DOTALL)

        if mu:
            url = mu.group(1).strip()
            title = (mt.group(1).strip() if mt else "")[:80] or url
            return {
                "title": title,
                "url": url,
                "summary": f"[分享卡片] {title}",
            }
        return None
