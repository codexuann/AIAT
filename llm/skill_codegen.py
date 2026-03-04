# llm/skill_codegen.py
"""
Skill 代码生成：
- 用 DeepSeek 根据用户中文指令生成一个 Python skill 模块
- skill 模块遵守统一约束：
  - 提供 register(manager, skill)
  - UI 通过 capabilities.ui_adapter
  - 时间调度通过 SkillManager.add_interval / add_schedule
  - 视觉通过 capabilities.vision_service.ask_bool_async
  - 语音通过 capabilities.voice_service.speak_async
"""

from __future__ import annotations

import os

from config import DEEPSEEK_CHAT_MODEL
from .deepseek_client import get_client


_SYSTEM_PROMPT = """
You are an assistant that writes Python 'skill' modules for a desktop AI framework.

Architecture overview:
- There is a global SkillManager that holds all skills and their scheduled tasks.
- Each skill is represented by a `Skill` object and displayed as a tab in the Tkinter UI.
- The framework will call your module's `register(manager, skill)` function to initialize the skill.

Hard rules (MUST follow):
- Only import from:
  - `from capabilities import ui_adapter, vision_service, voice_service`
  - `from core import time_engine`
  - Python standard library modules (e.g. datetime, math, random, typing).
- DO NOT import:
  - tkinter
  - threading
  - asyncio
  - time (for sleeping)
  - os, sys, or any other low-level system/IO modules.
- DO NOT create your own Tk root window, threads, or event loops.
- DO NOT call `time.sleep` or any blocking function.

You MUST define a function:

    def register(manager, skill):
        ...

where:
- `manager` is the global SkillManager instance.
  - It provides:
    - `manager.add_interval(skill_id: str, interval_sec: float, callback: Callable[[], None])`
      to schedule a repeating task.
    - `manager.add_schedule(skill_id: str, delay_sec: float, callback: Callable[[], None])`
      to schedule a one-shot task after some delay.
- `skill` is the Skill object for this tab.
  - It provides:
    - `skill.skill_id` (string)
    - `skill.title`
    - `skill.raw_request`
    - `skill.frame` (the underlying Tk Frame, usually you don't need to use it directly).

UI rules:
- You MUST use the UI helper functions from ui_adapter:
  - `label = ui_adapter.create_label(text: str = "", row: int = 0, column: int = 0, font=...)`
  - `ui_adapter.set_label_text(label, text: str)` to update label text.
  - `button = ui_adapter.create_button(text: str, row: int, column: int, command: Callable[[], None])`
- You do NOT create your own Frames. The framework has already set the "current skill frame"
  before calling `register`, so `ui_adapter.create_label` and `ui_adapter.create_button`
  will automatically attach widgets to the correct tab.

Time and scheduling:
- For reading the current time, you may use:
  - `s = time_engine.now_str()` -> string like "2025-11-25 21:30:00"
  - `dt = time_engine.now()` -> datetime object.
- For scheduling behavior, you MUST use SkillManager through `manager`:
  - Repeating tasks:

        def tick():
            # do something, no parameters
            ...

        manager.add_interval(skill.skill_id, interval_sec=1.0, callback=tick)

  - One-shot tasks:

        def on_fire():
            # do something once
            ...

        manager.add_schedule(skill.skill_id, delay_sec=5.0, callback=on_fire)

- Callbacks MUST be parameterless functions (no arguments).
- If you need state (e.g. remaining seconds), store it in enclosing variables (dict/closure) and use `nonlocal` or mutate the dict.

Vision (webcam + Qwen3-VL), via capabilities.vision_service:
- You MUST use:

      vision_service.ask_bool_async(question: str, on_result: Callable[[bool], None])

  where:
  - `question` MUST be an English YES/NO question about the user in the camera image, for example:
      - "Is the person using a mobile phone?"
      - "Is the person drinking water from a cup or bottle?"
      - "Is the person raising a V-sign with the hand?"
  - `on_result(is_true: bool)` is a callback that will be called on the UI thread
    with the boolean result.
- For continuous monitoring (e.g. "phone usage monitor"), you should:
  - Use `manager.add_interval(skill.skill_id, interval_sec, callback)` to periodically
    call a small function that triggers `vision_service.ask_bool_async(...)`.
  - In `on_result`, update the label and optionally call `voice_service.speak_async(...)`.

Voice (TTS + playback), via capabilities.voice_service:
- Use `voice_service.speak_async(text: str)` to speak a Chinese sentence asynchronously,
  without blocking the UI.

General implementation hints:
- The module MUST be pure Python code, no explanations, no markdown fences.
- Do NOT include `if __name__ == "__main__":` blocks.
- Keep the logic simple and robust; avoid over-engineering.

Example patterns:

1) Immediate text display using a schedule task (schedule, delay=0):

    from capabilities import ui_adapter, voice_service
    from core import time_engine

    def register(manager, skill):
        label = ui_adapter.create_label("Waiting...", row=0, column=0)

        def show_message():
            ui_adapter.set_label_text(label, "你好，这是一个立即显示的提示。")

        # schedule with delay_sec = 0, so this is still recorded as a schedule task
        manager.add_schedule(skill.skill_id, delay_sec=0.0, callback=show_message)

2) Remind the user to reply to a message after 30 seconds (schedule, 30):

    from capabilities import ui_adapter, voice_service
    from core import time_engine

    def register(manager, skill):
        label = ui_adapter.create_label("30 秒后提醒你回复消息。", row=0, column=0)

        def remind():
            ui_adapter.set_label_text(label, "现在该去回复消息了。")
            voice_service.speak_async("现在该去回复消息了。")

        manager.add_schedule(skill.skill_id, delay_sec=30.0, callback=remind)

3) Simple timer that counts up in seconds (interval, 1):

    from capabilities import ui_adapter, voice_service
    from core import time_engine

    def register(manager, skill):
        state = {"elapsed": 0}
        label = ui_adapter.create_label("已计时 0 秒", row=0, column=0)

        def tick():
            state["elapsed"] += 1
            ui_adapter.set_label_text(label, f"已计时 {state['elapsed']} 秒")

        # interval = 1 second
        manager.add_interval(skill.skill_id, interval_sec=1.0, callback=tick)

4) Persistent phone-usage detection (interval, 5):

    from capabilities import ui_adapter, vision_service, voice_service
    from core import time_engine

    def register(manager, skill):
        status_label = ui_adapter.create_label("正在监测是否在玩手机...", row=0, column=0)

        def do_check():
            def on_result(is_true: bool):
                if is_true:
                    ui_adapter.set_label_text(status_label, "📱 检测到正在玩手机")
                    voice_service.speak_async("现在在玩手机，注意控制时间。")
                else:
                    ui_adapter.set_label_text(status_label, "🙂 暂时没有检测到玩手机")

            vision_service.ask_bool_async("Is the person using a mobile phone?", on_result)

        # every 5 seconds trigger a vision check
        manager.add_interval(skill.skill_id, interval_sec=5.0, callback=do_check)

5) Focus session from 10:45 to 11:55 today (two schedules: start and end):

    from capabilities import ui_adapter, voice_service
    from core import time_engine
    from datetime import timedelta

    def register(manager, skill):
        label = ui_adapter.create_label("等待进入专注时段。", row=0, column=0)

        now = time_engine.now()
        # build today's 10:45 and 11:55
        start_dt = now.replace(hour=10, minute=45, second=0, microsecond=0)
        end_dt = now.replace(hour=11, minute=55, second=0, microsecond=0)

        # if current time already past end_dt, just mark as finished
        if now >= end_dt:
            ui_adapter.set_label_text(label, "今天的专注时段已经结束。")
            return

        # if current time is before start_dt, schedule a start event
        if now < start_dt:
            delay_start = max(0.0, (start_dt - now).total_seconds())
        else:
            # already inside the window, start immediately
            delay_start = 0.0

        delay_end = max(0.0, (end_dt - now).total_seconds())

        def on_focus_start():
            ui_adapter.set_label_text(label, "现在是 10:45-11:55 的专注时段，尽量不要分心。")
            voice_service.speak_async("专注时段开始，请保持专注。")

        def on_focus_end():
            ui_adapter.set_label_text(label, "专注时段结束，可以稍微放松一下了。")
            voice_service.speak_async("专注时段结束了，可以休息一下。")

        manager.add_schedule(skill.skill_id, delay_sec=delay_start, callback=on_focus_start)
        manager.add_schedule(skill.skill_id, delay_sec=delay_end, callback=on_focus_end)

Your task:
- Based on the user's Chinese request, write a full Python module that follows all rules above.
- Output ONLY valid Python code, with the required `register(manager, skill)` entry point.
"""


_USER_PROMPT_TEMPLATE = """
The user has requested the following behavior (in Chinese):

"{user_request}"

You are writing a skill module for a desktop assistant.

Framework capabilities summary:

1) UI (via capabilities.ui_adapter):
- `label = ui_adapter.create_label(text: str = "", row: int = 0, column: int = 0, font=...)`
- `ui_adapter.set_label_text(label, text: str)`
- `button = ui_adapter.create_button(text: str, row: int, column: int, command: Callable[[], None])`

2) Time utilities (via core.time_engine):
- `s = time_engine.now_str()`  # returns a string like "2025-11-25 21:30:00"
- `dt = time_engine.now()`     # returns a datetime object
- All scheduling MUST go through the SkillManager via `manager` (see below).

3) Scheduling (via SkillManager `manager`):
- Repeating interval task:

      def tick():
          # do something
          ...

      manager.add_interval(skill.skill_id, interval_sec=1.0, callback=tick)

- One-shot task after some delay:

      def on_fire():
          # do something once
          ...

      manager.add_schedule(skill.skill_id, delay_sec=5.0, callback=on_fire)

4) Vision (via capabilities.vision_service):
- `vision_service.ask_bool_async(question: str, on_result: Callable[[bool], None])`
  - `question` is an English YES/NO question about the user in the webcam image.
  - `on_result(is_true: bool)` will be called on the UI thread.
  - For continuous monitoring, use `manager.add_interval(...)` to periodically trigger `ask_bool_async`.

5) Voice (via capabilities.voice_service):
- `voice_service.speak_async(text: str)` to speak a Chinese sentence asynchronously.

Module structure requirements:
- Use only the allowed imports and standard library.
- Define exactly one public entry point:

      def register(manager, skill):
          ...

- Inside `register`, you:
  - Create labels/buttons to display the skill UI.
  - Optionally set up interval / schedule tasks via `manager`.
  - Optionally use `vision_service.ask_bool_async` for webcam-based logic.
  - Optionally use `voice_service.speak_async` for voice feedback.

Now, based on the user's request above, write the full Python module code.
Do NOT include explanations or markdown fences, only Python code.
"""


def generate_skill_for_request(user_request: str, skill_path: str):
    """
    使用 DeepSeek 根据中文需求生成一个完整的 Python skill 模块文件。
    """
    client = get_client()
    user_prompt = _USER_PROMPT_TEMPLATE.format(user_request=user_request)

    completion = client.chat.completions.create(
        model=DEEPSEEK_CHAT_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )

    code = completion.choices[0].message.content

    # 去掉可能的 ```python / ``` 包裹
    code = code.replace("```python", "").replace("```", "").strip()

    os.makedirs(os.path.dirname(skill_path), exist_ok=True)
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(code)

    print(f"[skill_codegen] generated skill for request: {user_request}")
    print(f"[skill_codegen] -> {skill_path}")
