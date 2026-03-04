# core/skill_manager.py
"""
SkillManager + TaskScheduler

职责：
- 全局唯一的 skills 表（Skill = 记忆单元）
- 内置 TaskScheduler，统一管理 schedule / interval 任务
- 提供 create_and_load_skill(user_request, brain):
    - 调用 llm.skill_codegen 生成 skills/user_skill.py
    - import 这个模块
    - 创建一个新的 Skill（Tab + Frame）
    - 调用模块的 register(manager, skill) 完成 UI 与任务注册
- 提供导出技能记忆的 JSON 接口（给 Brain / LLM 使用）
"""

from __future__ import annotations

import importlib
import json
import time
import threading
import heapq
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import tkinter as tk

from capabilities import ui_adapter
from llm.skill_codegen import generate_skill_for_request

# ==== 路径配置：生成技能模块的位置 ====

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
SKILL_MODULE_NAME = "skills.user_skill"
SKILL_PATH = SKILLS_DIR / "user_skill.py"

TaskCallback = Callable[[], None]


# ==================== Task 调度器 ====================

@dataclass
class SkillTask:
    task_id: str
    skill_id: str
    kind: str           # "schedule" or "interval"
    trigger_ts: float
    interval_sec: Optional[float]
    callback: TaskCallback
    cancelled: bool = False


class TaskScheduler:
    """
    只负责“按时执行任务”的后台线程，不关心业务（不关心 SkillManager）。
    """

    def __init__(self, dispatch_fn: Callable[[TaskCallback], None]):
        """
        dispatch_fn: 把 callback 丢回 UI 线程的函数，比如 ui_adapter.run_on_ui_thread。
        """
        self._dispatch_fn = dispatch_fn
        self._lock = threading.Lock()
        self._heap: List[tuple] = []  # (trigger_ts, counter, SkillTask)
        self._counter = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[TaskScheduler] started")

    def stop(self):
        self._running = False
        print("[TaskScheduler] stopped")

    def schedule_task(self, task: SkillTask) -> None:
        with self._lock:
            self._counter += 1
            heapq.heappush(self._heap, (task.trigger_ts, self._counter, task))

    def _loop(self):
        while self._running:
            now = time.time()
            to_run: List[SkillTask] = []

            with self._lock:
                # 取出所有到点的任务
                while self._heap and self._heap[0][0] <= now:
                    _, _, task = heapq.heappop(self._heap)
                    if not task.cancelled:
                        to_run.append(task)

                # 计算这个循环 sleep 多久
                if self._heap:
                    next_ts, _, _ = self._heap[0]
                    sleep_sec = max(0.05, min(1.0, next_ts - now))
                else:
                    sleep_sec = 0.3

            # 在锁外执行任务
            for task in to_run:
                if task.cancelled:
                    continue

                # interval 任务需要重排队
                if task.kind == "interval" and task.interval_sec is not None:
                    with self._lock:
                        if not task.cancelled:
                            task.trigger_ts = time.time() + task.interval_sec
                            self._counter += 1
                            heapq.heappush(self._heap, (task.trigger_ts, self._counter, task))

                # 把回调丢回 UI 线程
                try:
                    self._dispatch_fn(task.callback)
                except Exception as e:
                    print("[TaskScheduler] dispatch_fn error:", e)

            time.sleep(sleep_sec)


# ==================== Skill / SkillManager ====================

@dataclass
class Skill:
    skill_id: str
    title: str
    frame: tk.Frame
    raw_request: str
    created_ts: float
    tasks: List[SkillTask] = field(default_factory=list)


class SkillManager:
    """
    全局技能管理器：
    - skills 表：skill_id -> Skill
    - 内置 TaskScheduler
    - 提供 create_and_load_skill() 供 main 调用
    - 导出 skills JSON，替代原来的 L0 记忆
    """

    def __init__(self):
        self.skills: Dict[str, Skill] = {}
        self.skill_counter = 0
        self.task_counter = 0

        # 内置调度器：所有时间任务统一走这里
        self._scheduler = TaskScheduler(dispatch_fn=ui_adapter.run_on_ui_thread)
        self._scheduler.start()

    # ---------- Skill 基本操作 ----------

    def _new_skill_id(self) -> str:
        self.skill_counter += 1
        return f"skill_{self.skill_counter}"

    def _new_task_id(self) -> str:
        self.task_counter += 1
        return f"task_{self.task_counter}"

    def create_skill(self, title: str, raw_request: str = "") -> Skill:
        """
        创建一个 skill：
        - 生成 skill_id
        - 创建 Tab + Frame
        - 注册到 skills 表
        """
        skill_id = self._new_skill_id()
        frame = ui_adapter.create_skill_container(skill_id, title)
        skill = Skill(
            skill_id=skill_id,
            title=title,
            frame=frame,
            raw_request=raw_request,
            created_ts=time.time(),
        )
        self.skills[skill_id] = skill
        print(f"[SkillManager] created skill: {skill_id} ({title})")
        return skill

    def end_skill(self, skill_id: str) -> None:
        """
        结束一个 skill：
        - cancel 该 skill 的所有任务
        - 删除 UI 容器
        - 从 skills 表移除
        """
        skill = self.skills.pop(skill_id, None)
        if skill is None:
            return

        for task in skill.tasks:
            task.cancelled = True

        try:
            ui_adapter.remove_skill_container(skill_id)
        except Exception as e:
            print(f"[SkillManager] remove_skill_container error for {skill_id}:", e)

        print(f"[SkillManager] ended skill: {skill_id}")

    # ---------- 时间任务接口（供技能使用） ----------

    def add_interval(self, skill_id: str, interval_sec: float, callback: TaskCallback) -> SkillTask:
        """
        为指定 skill 添加 interval 任务。
        """
        skill = self.skills[skill_id]
        trigger_ts = time.time() + max(0.01, float(interval_sec))
        task = SkillTask(
            task_id=self._new_task_id(),
            skill_id=skill_id,
            kind="interval",
            trigger_ts=trigger_ts,
            interval_sec=float(interval_sec),
            callback=callback,
        )
        skill.tasks.append(task)
        self._scheduler.schedule_task(task)
        return task

    def add_schedule(self, skill_id: str, delay_sec: float, callback: TaskCallback) -> SkillTask:
        """
        为指定 skill 添加一次性 schedule 任务。
        """
        skill = self.skills[skill_id]
        trigger_ts = time.time() + max(0.0, float(delay_sec))
        task = SkillTask(
            task_id=self._new_task_id(),
            skill_id=skill_id,
            kind="schedule",
            trigger_ts=trigger_ts,
            interval_sec=None,
            callback=callback,
        )
        skill.tasks.append(task)
        self._scheduler.schedule_task(task)
        return task

    # ---------- L0 记忆替代：导出 skills JSON ----------

    def _skill_to_dict(self, skill: Skill) -> Dict[str, Any]:
        return {
            "skill_id": skill.skill_id,
            "title": skill.title,
            "raw_request": skill.raw_request,
            "created_timestamp": skill.created_ts,
            "created_time_str": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(skill.created_ts)
            ),
            "tasks": [
                {
                    "task_id": task.task_id,
                    "kind": task.kind,
                    "trigger_timestamp": task.trigger_ts,
                    "interval_sec": task.interval_sec,
                    "cancelled": task.cancelled,
                }
                for task in skill.tasks
            ],
        }

    def get_all_skills_data(self) -> Dict[str, Any]:
        return {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "skills": [self._skill_to_dict(s) for s in self.skills.values()],
        }

    def export_skills_json(self, pretty: bool = False) -> str:
        data = self.get_all_skills_data()
        if pretty:
            return json.dumps(data, ensure_ascii=False, indent=2)
        return json.dumps(data, ensure_ascii=False)

    # ---------- 与 Brain / LLM skill 代码生成集成 ----------

    def create_and_load_skill(self, user_request: str, brain: Any) -> None:
        """
        完整流程：
        1. 调用 LLM 生成 skills/user_skill.py
        2. import 该模块
        3. 由 Brain 派生 Tab 标题
        4. 创建 Skill（Tab + Frame）
        5. 调用模块 register(self, skill) 让技能内部完成 UI 和任务注册
        6. 激活该 Tab
        """

        # 1. 确保 skills 目录存在
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)

        # 2. 让 LLM 生成/覆盖 user_skill.py
        try:
            generate_skill_for_request(user_request, str(SKILL_PATH))
        except Exception as e:
            print("[SkillManager] generate_skill_for_request error:", e)
            ui_adapter.append_chat("System", "生成技能代码时发生错误。")
            return

        # 3. import 模块
        try:
            module = importlib.import_module(SKILL_MODULE_NAME)
            module = importlib.reload(module)
        except ModuleNotFoundError as e:
            print("[SkillManager] cannot import generated skill:", e)
            ui_adapter.append_chat("System", "找不到生成的技能模块。")
            return
        except Exception as e:
            print("[SkillManager] import error:", e)
            ui_adapter.append_chat("System", "加载技能模块时发生错误。")
            return

        # 4. 用 Brain 生成一个 Tab 标题
        try:
            title = brain.derive_title_from_request(user_request)
        except Exception:
            title = "Skill"

        # 5. 创建 Skill + UI Frame
        skill = self.create_skill(title=title, raw_request=user_request)

        # （可选）通知 Brain “记了一条 skill 事件”，现在先做兼容，内部可以是 no-op
        if hasattr(brain, "store_skill_memory"):
            try:
                brain.store_skill_memory(skill.skill_id, title, user_request)
            except Exception as e:
                print("[SkillManager] store_skill_memory error:", e)

        # 6. 调用模块的 register(self, skill)
        if hasattr(module, "register"):
            try:
                # 在当前 skill 的 frame 上挂载控件
                ui_adapter.set_current_skill_frame(skill.frame)
                module.register(self, skill)
                ui_adapter.append_chat("System", f"新的技能已经加载到界面：{title}")
            except Exception as e:
                print("[SkillManager] skill register() error:", e)
                ui_adapter.append_chat("System", "加载技能时发生错误。")
            finally:
                ui_adapter.clear_current_skill_frame()
        else:
            ui_adapter.append_chat("System", "生成的模块没有 register()，无法加载。")

        # 7. 激活该 Tab
        ui_adapter.activate_skill(skill.skill_id)
