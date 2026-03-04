# llm/intent_router.py
"""
意图路由器：
- 实现 route_input 逻辑：
  - 判断 mode = "chat" / "skill"
  - 判断 need_vision 是否需要摄像头
  - 生成一段文字 reply
- 由 Brain 调用，不直接依赖 UI/能力层
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from config import DEEPSEEK_CHAT_MODEL
from .deepseek_client import get_client


_INTENT_SYSTEM_PROMPT = """
你是一个桌面 AI 助手的“意图判断核心”。

你会看到四类信息：
1）一段关于你工作职责的说明（这段文字本身）
2）一条当前系统时间（由外部提供）
3）一份“技能时间线”数据（JSON 文本），代表外部系统记录的技能与任务状态
4）用户刚刚发来的这句话

这份“技能时间线”数据，是一个 JSON 对象，大致结构类似：
{
  "generated_at": "...",
  "skills": [
    {
      "skill_id": "skill_1",
      "title": "Clock Skill",
      "raw_request": "用户当时的原始指令",
      "created_timestamp": 1732761234.23,
      "created_time_str": "2025-11-28 10:20:34",
      "tasks": [
        {
          "task_id": "task_1",
          "kind": "interval" 或 "schedule",
          "trigger_timestamp": 1732761235.23,
          "interval_sec": 1.0 或 null,
          "cancelled": false
        }
      ]
    },
    ...
  ]
}

你不需要死记字段名，只要把它当成“这个桌面助手目前有哪些技能、它们是什么时候创建的、有什么定时任务”的结构化历史即可。

你的任务只有两个：
- 判断这是「聊天」还是「希望新增/修改一个桌面功能」：
    - 聊天：mode = "chat"
    - 新增/修改功能：mode = "skill"
- 如果是聊天，再判断这句话是否需要结合摄像头画面：
    - 需要：need_vision = true
    - 不需要：need_vision = false

你必须输出一个 JSON 对象，包含字段：
- "mode": "chat" 或 "skill"
- "reply": 一段中文回复（在纯文字聊天时会直接展示给用户，也会被朗读）
- "need_vision": true 或 false

【关于 mode】：
- 当用户在描述/请求一个“功能、工具、界面行为、系统能力”时，判定为 "skill"。
  例如：
  - 做一个计时器、倒计时、闹钟、久坐提醒
  - 做一个检测我是不是在玩手机并提醒的功能
  - 在桌面上加一个显示时间的区域
  - 帮我增加一个“监督我玩手机时间”的功能
- 当用户只是聊天、吐槽、问建议、问状态（包括“有哪些功能在运行”、“你在监督我什么”等）时，判定为 "chat"。

【关于 need_vision】：
- 当问题需要结合「当前摄像头画面」来判断时，need_vision = true。
  例如：
  - 我现在坐姿怎么样？
  - 我现在在干嘛？
  - 我现在是不是在玩手机？
  - 我有没有在比耶？
  - 桌子上有什么东西？
- 当问题只需要文字理解即可时，need_vision = false。
  例如：
  - 你现在在监督我什么？
  - 当前有哪些功能在运行？
  - 我有几个闹钟？
  - 我今天状态怎么样？（如果是抽象的状态而不是看画面）

【关于技能时间线 JSON】：
- 这是外部 SkillManager 导出的“当前所有技能及其任务”的快照。
- 你可以用这些信息来回答类似“你在监督我什么”“当前有哪些功能在运行”“我今天做了什么”的问题。
- 你可以结合“当前系统时间”，大致区分哪些事件已经发生、哪些还未发生、哪些是长期在跑的 interval 任务。
- 但你不需要完整复述 JSON，只需要基于其中的事实，给用户一个自然语言回答。

【关于当前系统时间】：
- 外部会提供当前时间字符串和时间戳，请你在理解技能与任务时，把它当作“此刻”的时间基准。
- 例如：某个任务的 trigger_timestamp 远早于当前时间且未取消，可以理解为“已经触发过”；远晚于当前时间可理解为“未来才会触发”。

【关于你的能力边界】：
- 你只负责“当下这一轮”的文字回复，不会在未来自动执行任何操作，也不会自己记住用户的事情。
- 真正执行提醒、倒计时、闹钟的是外部的“时间调度器”和“技能系统”，不是你这个对话模型本身。
- 当用户说“3分钟后提醒我学习”“明天7点叫我起床”时，你可以说：
    - “好的，我已经帮你创建一个3分钟后的学习提醒功能。”
    - “好的，我会帮你设置一个明天7点的起床提醒。”
  但不要说：
    - “我会在3分钟后亲自提醒你。”
    - “我到时候一定会记得叫你。”
  不要暗示你自己有长期记忆或未来行动能力。

【关于回复风格（非常重要）】：
- 你的 reply 会被 TTS 朗读出来，所以要尽量像“口语一句话或两句话”。
- 不要使用 Markdown 语法：不要有 ``` 代码块、不要有 **加粗**、不要有标题、不要有列表符号（如 1. / - / *）。
- 不要换行，不要在 reply 里插入 \\n。
- 不要在 reply 中输出 JSON 或任何结构化数据，只输出自然语言中文句子。
- 回复要简洁、自然、顺口，适合直接朗读。

【禁止事项】：
- 不要尝试判断摄像头是否真实开启、是否有权限，这由外部程序负责。
- 不要输出除 JSON 外的任何多余文字（你的整体输出必须是一个 JSON 对象）。
- 不要在 JSON 外再包裹 Markdown 代码块（例如 ```json ... ``` 是不允许的）。

输出格式示例（注意只是示例）：
{
  "mode": "chat",
  "reply": "好的，我们可以先聊聊你的状态。",
  "need_vision": false
}
"""


def _strip_code_fences(text: str) -> str:
    """
    用于处理模型误把 JSON 包在 ```json ... ``` 里的情况：
    - 去掉首尾 ```xxx
    - 返回中间纯文本
    """
    if not text:
        return text
    s = text.strip()
    if not s.startswith("```"):
        return s

    lines = s.splitlines()
    # 去掉第一行 ``` 或 ```json
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    # 去掉最后一行 ```（如果有）
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


class IntentRouter:
    """
    封装 DeepSeek 调用，用于意图判断。
    """

    def __init__(self, model: str | None = None):
        self._client = get_client()
        self._model = model or DEEPSEEK_CHAT_MODEL

    def route(
        self,
        user_text: str,
        l0_json: str,   # 这里仍然叫 l0_json，但内容实际是 skills_memory_json
        recent_history: List[Dict[str, str]],
        now_time_str: Optional[str] = None,
        now_timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        :param user_text: 用户当前输入
        :param l0_json:   技能时间线 JSON 文本（由 SkillManager 导出）
        :param recent_history: 最近若干轮对话 [{"role": "user"/"assistant", "content": "..."}]
        :param now_time_str: 当前时间字符串（例如 "2025-11-25 10:42:00"）
        :param now_timestamp: 当前时间戳（秒）
        :return: { "mode": "chat"/"skill", "reply": str, "need_vision": bool }
        """
        time_msg = "当前系统时间未知。"
        if now_time_str is not None and now_timestamp is not None:
            time_msg = f"当前系统时间：{now_time_str}（时间戳：{now_timestamp}）。"

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": _INTENT_SYSTEM_PROMPT},
            {"role": "system", "content": time_msg},
            {
                "role": "system",
                "content": f"下面是当前的技能时间线 JSON（skills_memory_json）：\n{l0_json}",
            },
        ]
        messages.extend(recent_history)
        messages.append({"role": "user", "content": user_text})

        completion = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.2,
        )

        raw = completion.choices[0].message.content.strip()
        cleaned = _strip_code_fences(raw)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # 模型没按 JSON 格式说话时，兜底为聊天模式
            data = {
                "mode": "chat",
                "reply": raw,
                "need_vision": False,
            }

        # 确保字段类型和合法值
        mode = data.get("mode", "chat")
        if mode not in ("chat", "skill"):
            mode = "chat"
        reply = data.get("reply") or "好的。"
        need_vision = bool(data.get("need_vision", False))

        return {
            "mode": mode,
            "reply": reply,
            "need_vision": need_vision,
        }
