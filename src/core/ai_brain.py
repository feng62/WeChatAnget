# -*- coding: utf-8 -*-
"""
AI 核心大脑引擎
整合模型接口调用、性格设定渲染、全局与专属记忆注入，以及自动记忆提炼。
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Dict, Any, List, Optional, Tuple

from .ai_config import load_ai_settings
from .persona_manager import build_system_prompt, load_persona
from .memory_manager import MemoryManager


class AIBrain:
    def __init__(self):
        self.memory = MemoryManager()

    def call_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: int = 25,
    ) -> str:
        """调用统一的 OpenAI 规范兼容接口"""
        cfg = load_ai_settings()
        api_key = (cfg.get("api_key") or "").strip()
        base_url = (cfg.get("base_url") or "https://api.deepseek.com/v1").rstrip("/")
        model = cfg.get("model") or "deepseek-chat"
        temp = temperature if temperature is not None else float(cfg.get("temperature", 0.75))
        max_tok = max_tokens if max_tokens is not None else int(cfg.get("max_tokens", 600))

        if not api_key:
            raise ValueError("未配置 API Key，请在「⚙️ 模型设置」中填入大模型密钥！")

        endpoint = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": max_tok,
        }

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "WeChatAutoBrain/1.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_json = json.loads(resp.read().decode("utf-8"))

        return resp_json["choices"][0]["message"]["content"].strip()

    def test_connection(self) -> Tuple[bool, str]:
        """测试模型接口连通性"""
        try:
            res = self.call_llm(
                [{"role": "user", "content": "请回复'pong'测试连通性"}],
                max_tokens=20,
                timeout=10,
            )
            return True, f"连接成功！模型响应: {res[:50]}"
        except Exception as e:
            return False, f"连接失败: {e}"

    def format_chat_history_messages(
        self,
        raw_msgs: List[Dict[str, Any]],
        self_name: str = "我",
    ) -> List[Dict[str, str]]:
        """
        将来自微信本地数据库的原始消息列表转换为 OpenAI 对话 messages 列表
        支持图片、语音、引用、卡片等富文本摘要与发言人标识。
        """
        formatted = []
        for m in raw_msgs:
            is_me = m.get("is_from_me", False) or m.get("direction") == "outgoing"
            speaker = m.get("sender_name") or m.get("contact_name") or ("我" if is_me else "对方")
            mtype = m.get("type") or "文本"
            text = (m.get("content") or m.get("text") or "").strip()

            # 解析各类富媒体摘要
            if mtype == "图片":
                text = "[图片]"
            elif mtype == "语音":
                voice_str = m.get("voice_text") or ""
                text = f"[语音: {voice_str}]" if voice_str else "[语音消息]"
            elif mtype == "视频":
                text = "[视频]"
            elif mtype == "表情":
                text = "[动画表情]"
            elif mtype == "引用消息":
                refer_quote = m.get("refer_quote") or ""
                if refer_quote:
                    text = f"[引用「{refer_quote[:40]}」] {text}"
            elif mtype in ("卡片", "链接卡片"):
                card_title = m.get("card_title") or text
                text = f"[分享卡片: {card_title[:40]}]"

            if not text:
                continue

            if is_me:
                formatted.append({"role": "assistant", "content": text})
            else:
                formatted.append({"role": "user", "content": f"[{speaker}]: {text}"})

        return formatted

    def generate_chat_reply(
        self,
        chat_id: str,
        incoming_text: str,
        sender_name: str = "",
        is_group: bool = False,
        history_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        全自动化单条回复生成：
        1. 注入性格人设 System Prompt；
        2. 注入全局记忆 + 当前联系人专属记忆；
        3. 注入当前聊天最近 10~20 条多轮历史消息；
        4. 生成单条微信风格自然回复。
        """
        cfg = load_ai_settings()
        context_count = int(cfg.get("context_messages_count", 15))

        # 1. 人设系统设定
        system_prompt = build_system_prompt()

        # 2. 记忆上下文增强
        memory_block = self.memory.build_memory_prompt_block(chat_id, sender_name)
        if memory_block:
            system_prompt += f"\n\n{memory_block}"

        messages = [{"role": "system", "content": system_prompt}]

        # 3. 多轮历史对话上下文 (优先使用真实数据库消息)
        has_context = False
        if history_messages and isinstance(history_messages, list):
            sliced = history_messages[-context_count:]
            db_turns = self.format_chat_history_messages(sliced)
            if db_turns:
                messages.extend(db_turns)
                has_context = True

        if not has_context:
            session_mem = self.memory.get_session_memory(chat_id)
            hist = session_mem.get("history", [])[-context_count:]
            for h in hist:
                messages.append({"role": h["role"], "content": h["text"]})

        # 4. 当前消息（若历史末尾尚未包含当前消息，则追加）
        target_hint = f"（来自群友「{sender_name}」）" if is_group and sender_name else ""
        user_content = f"{target_hint} {incoming_text}".strip()
        last_msg_content = messages[-1]["content"] if len(messages) > 1 else ""
        if incoming_text not in last_msg_content:
            messages.append({"role": "user", "content": user_content})

        reply = self.call_llm(messages)

        # 5. 沉淀历史并异步提炼记忆
        self.memory.record_turn(chat_id, incoming_text, reply, title=sender_name)
        self.schedule_memory_extraction(chat_id, incoming_text, reply, sender_name)

        return reply

    def generate_suggestions(
        self,
        chat_id: str,
        incoming_text: str,
        sender_name: str = "",
        custom_instruction: str = "",
        history_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
        """
        生成 3 种不同风格的回复候选建议：
        【得体】、【幽默】、【精简】
        结合当前聊天最近 10~20 条消息上下文进行综合判断。
        """
        # 兜底离线模板
        cfg = load_ai_settings()
        if not (cfg.get("api_key") or "").strip():
            return self._offline_suggestions(incoming_text, custom_instruction)

        context_count = int(cfg.get("context_messages_count", 15))
        system_prompt = build_system_prompt()
        memory_block = self.memory.build_memory_prompt_block(chat_id, sender_name)
        if memory_block:
            system_prompt += f"\n\n{memory_block}"

        system_prompt += """\n
【任务说明】：
请综合参考当前聊天的最近上下文及对方发来的最新消息，提供 3 种不同风格的回复建议：
1. [得体] 优雅、礼貌、周全；
2. [幽默] 自然、有趣、高情商；
3. [精简] 直接、短小精干。

输出格式必须严格如下（每行一条，不要包含其他说明）：
[得体] 回复内容
[幽默] 回复内容
[精简] 回复内容"""

        # 组装上下文提示
        context_lines = []
        if history_messages and isinstance(history_messages, list):
            sliced = history_messages[-context_count:]
            db_turns = self.format_chat_history_messages(sliced)
            for turn in db_turns[-8:]:
                prefix = "对方/群友" if turn["role"] == "user" else "我"
                context_lines.append(f"{prefix}: {turn['content']}")

        context_str = "\n".join(context_lines) if context_lines else "无先前记录"

        user_prompt = f"【当前联系人】: {sender_name or '对方'}\n【最近上下文】:\n{context_str}\n\n【最新收到的消息】: \"{incoming_text}\""
        if custom_instruction:
            user_prompt += f"\n【额外要求/意图】: {custom_instruction}"

        try:
            content = self.call_llm([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ], max_tokens=300)

            results = []
            for line in content.split("\n"):
                line = line.strip()
                m = re.match(r"^\[?(得体|幽默|精简|正式|礼貌|调侃|风趣|干练)\]?[\s:：、]*(.*)$", line)
                if m:
                    results.append({"style": m.group(1), "text": m.group(2).strip()})
                elif len(line) > 2 and len(results) < 3:
                    clean = re.sub(r"^[0-9]+[\.、\s]+", "", line).strip()
                    results.append({"style": f"选项 {len(results)+1}", "text": clean})

            if len(results) >= 2:
                return results[:3]
        except Exception as e:
            print(f"[AIBrain] 生成建议异常: {e}", flush=True)

        return self._offline_suggestions(incoming_text, custom_instruction)

    def generate_copilot_analysis(
        self,
        chat_id: str,
        incoming_text: str,
        sender_name: str = "",
        custom_instruction: str = "",
        history_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        微信副驾驶专属：深度分析近 15~20 轮上下文，输出意图洞察 + 3 种风格回复建议。
        """
        cfg = load_ai_settings()
        api_key = (cfg.get("api_key") or "").strip()
        context_count = int(cfg.get("context_messages_count", 15))

        if not api_key:
            return {
                "intent": f"（离线模拟）对方正在与你交流日常话题",
                "suggestions": self._offline_suggestions(incoming_text, custom_instruction),
            }

        persona = load_persona()
        system_prompt = build_system_prompt()
        memory_block = self.memory.build_memory_prompt_block(chat_id, sender_name)
        if memory_block:
            system_prompt += f"\n\n{memory_block}"

        max_words = persona.get("max_words", 100)
        system_prompt += f"""\n
【微信副驾驶 - 深度意图洞察与分风格回复任务】：
请你以副驾驶专家视角，深入审视分析用户与联系人「{sender_name or '对方'}」的多轮聊天历史与上文脉络。
完成以下两项任务：
1. 【意图洞察】：用 1 句话（不超过30字）精准提炼出「对方的核心诉求、关注重点及当前的情绪态度」；
2. 【3 种风格回复建议】：基于当前人设身份及已知记忆事实，生成 3 种最佳微信自然口吻回复（单条限 {max_words} 字内）：
   - [得体] 自然温暖、得体周全、极具情商
   - [幽默] 轻松风趣、带点俏皮互动、活跃气氛
   - [精简] 言简意赅、短小精干、清晰了当

【输出格式要求】（必须严格按照下列格式输出 4 行，严禁包含任何前缀或开场白）：
[洞察] 对方的核心诉求与情绪态度洞察总结
[得体] 得体回复内容
[幽默] 幽默回复内容
[精简] 精简回复内容"""

        # 整理上下文消息
        context_lines = []
        if history_messages and isinstance(history_messages, list):
            sliced = history_messages[-context_count:]
            db_turns = self.format_chat_history_messages(sliced)
            for turn in db_turns[-12:]:
                prefix = "对方/群友" if turn["role"] == "user" else "我"
                context_lines.append(f"{prefix}: {turn['content']}")

        context_str = "\n".join(context_lines) if context_lines else "（暂无历史记录）"
        user_prompt = f"【当前联系人】: {sender_name or '对方'}\n【近期聊天记录】:\n{context_str}\n\n【最新收到的消息】: \"{incoming_text}\""
        if custom_instruction:
            user_prompt += f"\n【副驾驶微调意图/回复要求】: {custom_instruction}"

        try:
            content = self.call_llm([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ], max_tokens=450)

            intent_summary = ""
            suggestions = []
            for line in content.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("[洞察]") or line.startswith("【洞察】"):
                    intent_summary = line[4:].strip().lstrip(":：、 ")
                else:
                    m = re.match(r"^\[?(得体|幽默|精简|正式|礼貌|调侃|风趣|干练)\]?[\s:：、]*(.*)$", line)
                    if m:
                        style_name = m.group(1)
                        if style_name in ("得体", "正式", "礼貌"):
                            full_style = "得体礼貌"
                            tag = "得体"
                        elif style_name in ("幽默", "调侃", "风趣"):
                            full_style = "风趣幽默"
                            tag = "幽默"
                        else:
                            full_style = "精简高效"
                            tag = "精简"
                        suggestions.append({"style": full_style, "tag": tag, "text": m.group(2).strip()})

            if not intent_summary:
                intent_summary = f"正在与「{sender_name or '对方'}」进行微信多轮对话沟通"

            if len(suggestions) < 2:
                suggestions = self._offline_suggestions(incoming_text, custom_instruction)

            return {
                "intent": intent_summary,
                "suggestions": suggestions[:3],
            }
        except Exception as e:
            print(f"[AIBrain] generate_copilot_analysis 异常: {e}", flush=True)
            return {
                "intent": f"与「{sender_name or '对方'}」的日常交流",
                "suggestions": self._offline_suggestions(incoming_text, custom_instruction),
            }

    def _offline_suggestions(self, msg: str, instruction: str = "") -> List[Dict[str, str]]:
        """离线模式下的情境回复模板"""
        if instruction:
            return [
                {"style": "得体", "text": f"好的，关于这件事情，{instruction}"},
                {"style": "幽默", "text": f"收到指令！{instruction}，咱们随时保持联络~"},
                {"style": "精简", "text": f"{instruction}。"},
            ]
        if "在吗" in msg:
            return [
                {"style": "得体", "text": "在的，请问有什么事我可以帮您？"},
                {"style": "幽默", "text": "呼叫成功！野生好友已上线，请讲~"},
                {"style": "精简", "text": "在的，你说。"},
            ]
        return [
            {"style": "得体", "text": "收到您的消息，我梳理一下稍后回复您详细信息。"},
            {"style": "幽默", "text": "收到收到！电波已接收，容我思考三秒钟~"},
            {"style": "精简", "text": "好的，收到！稍后联系。"},
        ]

    def schedule_memory_extraction(self, chat_id: str, user_text: str, assistant_text: str, sender_name: str = ""):
        """后台异步提炼对话中关于该联系人的新事实"""
        cfg = load_ai_settings()
        if not cfg.get("auto_extract_memory", True) or not (cfg.get("api_key") or "").strip():
            return

        def _worker():
            try:
                prompt = f"""请分析以下对话，提取出关于联系人「{sender_name or chat_id}」的新个人事实、偏好、职业、常住地、特定约定或核心特征：
用户: {user_text}
我: {assistant_text}

要求：
1. 仅提取有价值的长期记忆事实（例如：对方喜欢喝乌龙茶、对方常住北京亦庄、约定周五开会）；
2. 严禁提取闲聊无意义的话（如在吗、吃了没）；
3. 必须输出 JSON 数组格式字符串，如：["喜欢骑摩托车", "常住亦庄"]；若无可提取事实，直接输出 []。"""

                res = self.call_llm([{"role": "user", "content": prompt}], max_tokens=150, temperature=0.3)
                m = re.search(r"\[.*\]", res, re.DOTALL)
                if m:
                    facts = json.loads(m.group(0))
                    for f in facts:
                        if isinstance(f, str) and len(f) > 2:
                            self.memory.add_session_note(chat_id, f, title=sender_name)
                            print(f"[AIBrain] 智能提炼沉淀联系人专属记忆 [{sender_name}]: {f}", flush=True)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()
