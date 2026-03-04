# core/skill_runtime.py
"""
Skill 运行时外壳：
- 负责启动 UI
- 启动摄像头守护线程
- 启动时间引擎
- 然后进入 Tk 主循环

技能本身的管理（Registry、动态加载等）已经抽离到 core.skill_manager 中。
"""

from __future__ import annotations

from typing import Callable

from capabilities import ui_adapter, vision_service
from core import time_engine


class SkillRuntime:
    """
    整个桌面 AI 内核的运行外壳：
    - 初始化 UI
    - 启动摄像头守护
    - 启动时间引擎
    - 提供 run(on_user_input) 进入主循环
    """

    def __init__(self, window_title: str = "AI Desktop Core"):
        self.window_title = window_title

    def run(self, on_user_input: Callable[[str], None]) -> None:
        """
        框架入口：
        - 初始化 UI
        - 启动全局摄像头守护线程（常驻）
        - 启动时间引擎（常驻）
        - 进入 Tk 主循环
        """
        # 初始化 UI，并把 on_user_input 挂到输入框回调上
        ui_adapter.init_root(self.window_title, on_user_input=on_user_input)

        # 程序一启动就开摄像头守护线程
        try:
            vision_service.start_camera_daemon()
        except Exception as e:
            print("[skill_runtime] failed to start camera daemon:", e)

        # 程序一启动就开时间引擎
        try:
            time_engine.start()
        except Exception as e:
            print("[skill_runtime] failed to start time engine:", e)

        # 进入 Tk 主循环
        root = ui_adapter.get_root()
        root.mainloop()
