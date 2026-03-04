# core/brain.py
"""
大脑层（Brain）：

- 负责“这句话是 chat 还是 skill”的意图判断（调用 llm.intent_router）
- 把当前 skills JSON（替代 L0 记忆）注入给大模型
- 维护对话历史（只给 LLM 当短期上下文，不是长期记忆）

说明：
- 旧的 memory_l0 / SkillSummarizer 已移除，统一改用 SkillManager 的 skills JSON 做“外部世界状态”输入。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from config import INTENT_HISTORY_LIMIT
from llm.intent_router import IntentRouter
from core import time_engine


class Brain:
    """
    Brain 封装所有和 LLM 打交道的“高层逻辑”：
    - route_input: 决策 chat / skill + need_vision，并给出文字回复
    - get_l0_json: （其实是 skills JSON）作为当前“世界状态”注入给 LLM
    - store_skill_memory: 先占坑，将来如果需要可以在这里对新 skill 做进一步总结
    """

    def __init__(self, skill_manager: Optional[Any] = None):
        # SkillManager 引用（用于导出 skills JSON）
        self._skill_manager = skill_manager

        # LLM 相关组件
        self._intent_router = IntentRouter()

        # 对话历史（只给意图判断用）
        self._conversation_history: List[Dict[str, str]] = []

    # ---------- SkillManager 注入 / 访问 ----------

    def set_skill_manager(self, skill_manager: Any) -> None:
        """允许在创建 Brain 之后再注入 SkillManager。"""
        self._skill_manager = skill_manager

    def _get_l0_json(self) -> str:
        """
        兼容 IntentRouter 的参数名 l0_json：
        - 实际上传的是 SkillManager.export_skills_json() 的结果
        - 如果暂时没有 SkillManager，则传空列表 "[]"
        """
        if self._skill_manager is None:
            return "[]"

        try:
            if hasattr(self._skill_manager, "export_skills_json"):
                return self._skill_manager.export_skills_json(pretty=False)
        except Exception as e:
            print("[brain] export_skills_json error:", e)

        return "[]"

    # ---------- 意图路由 ----------

    def route_input(self, user_text: str) -> Dict[str, Any]:
        """
        输入一条用户文本：
        - 拉取当前 skills JSON（原来的 L0 记忆位）
        - 截取最近 INTENT_HISTORY_LIMIT 条对话作为历史
        - 注入当前系统时间（字符串 + 时间戳）
        - 调用 IntentRouter 得到结构化结果
        - 更新本地对话历史
        - 返回 {mode, reply, need_vision}
        """
        l0_json = self._get_l0_json()
        recent = self._conversation_history[-INTENT_HISTORY_LIMIT:]

        now_str = time_engine.now_str()
        now_ts = time_engine.now_timestamp()

        result = self._intent_router.route(
            user_text=user_text,
            l0_json=l0_json,              # 内部 prompt 可以后续改为“skills JSON”
            recent_history=recent,
            now_time_str=now_str,
            now_timestamp=now_ts,
        )

        mode = result.get("mode", "chat")
        if mode not in ("chat", "skill"):
            mode = "chat"

        reply = result.get("reply") or "好的。"
        need_vision = bool(result.get("need_vision", False))

        # 维护对话历史
        self._conversation_history.append({"role": "user", "content": user_text})
        self._conversation_history.append({"role": "assistant", "content": reply})

        return {
            "mode": mode,
            "reply": reply,
            "need_vision": need_vision,
        }

    def add_history(self, role: str, content: str) -> None:
        """
        允许外层（比如视觉回答）再补充一条 history。
        """
        if not content:
            return
        self._conversation_history.append({"role": role, "content": content})

    # ---------- Skill 相关辅助 ----------

    @staticmethod
    def derive_title_from_request(user_text: str) -> str:
        """
        从用户输入里提取一个简短标题，用来显示在 Tab 上。
        （逻辑与旧版保持一致）
        """
        t = (user_text or "").strip()
        for prefix in (
            "做一个",
            "做個",
            "帮我做一个",
            "幫我做一個",
            "帮我做個",
            "帮我",
            "幫我",
        ):
            if t.startswith(prefix):
                t = t[len(prefix):].strip()
                break
        if len(t) > 8:
            t = t[:8] + "..."
        return t or "Skill"

    def store_skill_memory(self, skill_id: str, title: str, user_request: str) -> None:
        """
        目前先占位：
        - 将来如果你还想在“新技能创建时，让 LLM 做一条事件总结再写入某个时间轴”，
          可以在这里接上 SkillSummarizer + 某个存储。
        - 现在 skills 本身已经是结构化记忆，所以可以先不做额外的东西。
        """
        # 暂时不做任何事，避免打断主流程。
        return
