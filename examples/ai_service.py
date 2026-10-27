# -*- coding: utf-8 -*-
"""
AI 对话副驾驶服务模块 (兼容 OpenAI / DeepSeek / Kimi / 通义千问 / Ollama 本地模型)

功能：
1. 统一标准 OpenAI 格式接口调用；
2. 一次性生成 3 种不同风格的微信回复建议：
   - 💬【得体礼貌】
   - 😄【风趣幽默】
   - ⚡【精简高效】
3. 离线内置兜底回复生成器（未填 API Key 时也能完整体验）；
4. 提供独立的配置持久化 (config_copilot.json)。
"""

import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_copilot.json")

DEFAULT_SYSTEM_PROMPT = """你是一个专业的微信聊天智能助手（AI 对话副驾驶）。
请根据对方发来的最新消息及上下文，提供 3 种不同风格的回复建议：
1. 【得体礼貌】优雅、礼貌、周全，适合长辈、客户或普通朋友；
2. 【风趣幽默】自然、有趣、高情商，适合好友或活跃气氛；
3. 【精简高效】直接、短小精干、清晰了当。

输出格式必须严格如下（每行一条，不要包含其他说明）：
[得体] 回复内容
[幽默] 回复内容
[精简] 回复内容"""


def load_copilot_config() -> dict:
    default_cfg = {
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "auto_generate": True,
        "dock_width": 340,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default_cfg.update(data)
        except Exception:
            pass
    return default_cfg


def save_copilot_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[AIService] 保存配置失败: {e}", flush=True)


class AISuggestionWorker(QThread):
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        context_msg: str,
        sender_name: str = "",
        custom_instruction: str = "",
        cfg: Optional[dict] = None,
    ):
        super().__init__()
        self.context_msg = context_msg
        self.sender_name = sender_name or "对方"
        self.custom_instruction = custom_instruction.strip()
        self.cfg = cfg or load_copilot_config()

    def run(self):
        api_key = (self.cfg.get("api_key") or "").strip()
        base_url = (self.cfg.get("base_url") or "https://api.deepseek.com/v1").rstrip("/")
        model = self.cfg.get("model") or "deepseek-chat"
        system_prompt = self.cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT

        # 若未填入 API Key，自动启用高质量本地规则模拟生成
        if not api_key:
            results = self._generate_offline_mock(self.context_msg, self.custom_instruction)
            self.finished.emit(results)
            return

        # 构造请求 Prompt
        user_prompt = f"【当前联系人】: {self.sender_name}\n【收到的消息】: \"{self.context_msg}\""
        if self.custom_instruction:
            user_prompt += f"\n【额外要求/意图】: {self.custom_instruction}"

        endpoint = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 500,
        }

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "WeChatCopilot/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))

            content = resp_json["choices"][0]["message"]["content"].strip()
            parsed = self._parse_candidates(content)
            if not parsed:
                parsed = [
                    {"style": "建议 1", "text": content[:120]},
                    {"style": "建议 2", "text": "收到，我稍后处理回复你~"},
                    {"style": "建议 3", "text": "好的！"},
                ]
            self.finished.emit(parsed)

        except urllib.error.HTTPError as e:
            err_body = e.read().decode(errors="ignore") if hasattr(e, "read") else str(e)
            print(f"[AIService] API 响应错误 ({e.code}): {err_body}", flush=True)
            # 降级到本地回复并提醒
            mock = self._generate_offline_mock(self.context_msg, self.custom_instruction)
            self.failed.emit(f"接口调用失败 ({e.code})，已自动切换本地建议")
            self.finished.emit(mock)

        except Exception as e:
            print(f"[AIService] 网络请求异常: {e}", flush=True)
            mock = self._generate_offline_mock(self.context_msg, self.custom_instruction)
            self.failed.emit(f"网络异常: {e}")
            self.finished.emit(mock)

    def _parse_candidates(self, raw_text: str) -> List[Dict[str, str]]:
        """从模型回复中提取 [得体]、[幽默]、[精简] 三行"""
        results = []
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        for line in lines:
            m = re.match(r"^\[?(得体|幽默|精简|正式|礼貌|调侃|风趣|干练)\]?[\s:：、]*(.*)$", line)
            if m:
                tag = m.group(1)
                text = m.group(2).strip()
                if text:
                    results.append({"style": tag, "text": text})
            elif len(line) > 2 and len(results) < 3:
                # 兼容普通编号格式
                clean = re.sub(r"^[0-9]+[\.、\s]+", "", line).strip()
                results.append({"style": f"选项 {len(results)+1}", "text": clean})

        return results[:3]

    def _generate_offline_mock(self, msg: str, instruction: str) -> List[Dict[str, str]]:
        """离线模式下的情境回复模板（无需配置 Key 也可体验流畅闭环）"""
        m = msg.strip()
        if "在吗" in m or "在不在" in m:
            return [
                {"style": "得体", "text": "在的，请问有什么事我可以帮您？"},
                {"style": "幽默", "text": "呼叫成功！野生客服已上线，请讲~"},
                {"style": "精简", "text": "在的，你说。"},
            ]
        elif "吃" in m or "饭" in m:
            return [
                {"style": "得体", "text": "还没呢，准备一会儿去吃，你吃了吗？"},
                {"style": "幽默", "text": "干饭人永不迟到！今天准备去吃顿好的~"},
                {"style": "精简", "text": "刚吃完，你呢？"},
            ]
        elif "什么时候" in m or "时间" in m or "几点" in m:
            return [
                {"style": "得体", "text": "我查看了一下日程，明天下午或者周五上午都比较方便。"},
                {"style": "幽默", "text": "看你时间安排，我随时准备出发！"},
                {"style": "精简", "text": "约明天下午两点如何？"},
            ]
        elif "好的" in m or "收到" in m or "行" in m:
            return [
                {"style": "得体", "text": "好的，后续有任何进展我第一时间同步给您。"},
                {"style": "幽默", "text": "妥妥的，包在我身上！"},
                {"style": "精简", "text": "收到！"},
            ]

        # 通用模板
        if instruction:
            return [
                {"style": "根据要求", "text": f"好的，关于这件事情，{instruction}"},
                {"style": "婉拒/委婉", "text": f"实在抱歉，最近手头有点紧凑，{instruction}"},
                {"style": "精简回复", "text": f"{instruction}，后续再聊！"},
            ]

        return [
            {"style": "得体", "text": "收到您的消息，我梳理一下稍后回复您详细信息。"},
            {"style": "幽默", "text": "收到收到！电波已接收，容我思考三秒钟~"},
            {"style": "精简", "text": "好的，收到！稍后联系。"},
        ]
