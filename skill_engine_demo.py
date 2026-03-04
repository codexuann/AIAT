"""
skill_engine_demo.py

目标：
- 使用现有的 ui_adapter + vision_service
- 全局只有一个 skills 表（SkillManager）
- TaskScheduler 统一调度 schedule / interval 任务
- Vision Monitor Skill 通过 vision_service.ask_bool_async 做摄像头检测

技能：
- Skill 1：时钟（每秒更新时间）
- Skill 2：5 秒后提醒一次
- Skill 3：每隔几秒用摄像头判断你是不是在看手机
"""

import json
import time
import threading
import heapq
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import tkinter as tk

from capabilities import ui_adapter, vision_service


# ========== 数据模型 ==========

TaskCallback = Callable[[], None]


@dataclass
class SkillTask:
    task_id: str
    skill_id: str
    kind: str           # "schedule" or "interval"
    trigger_ts: float
    interval_sec: Optional[float]
    callback: TaskCallback
    cancelled: bool = False


@dataclass
class Skill:
    skill_id: str
    title: str
    frame: tk.Frame
    raw_request: str
    created_ts: float
    tasks: List[SkillTask] = field(default_factory=list)


# ========== 调度器：只负责按时执行 ==========

class TaskScheduler:
    """
    只做一件事：按 trigger_ts 调用 callback。
    不保存业务状态，不关心 skill，只认 SkillTask。
    """

    def __init__(self, dispatch_fn: Callable[[TaskCallback], None]):
        """
        dispatch_fn: 用来把 callback 丢到 UI 线程，比如 ui_adapter.run_on_ui_thread。
        """
        self._dispatch_fn = dispatch_fn
        self._lock = threading.Lock()
        self._heap: List[tuple] = []  # (trigger_ts, counter, task)
        self._counter = 0
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        print("[TaskScheduler] started")

    def stop(self):
        self._running = False
        print("[TaskScheduler] stopped")

    def schedule_task(self, task: SkillTask):
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

                # 计算下次睡多久
                if self._heap:
                    next_ts, _, _ = self._heap[0]
                    sleep_sec = max(0.05, min(1.0, next_ts - now))
                else:
                    sleep_sec = 0.3

            # 在锁外执行
            for task in to_run:
                if task.cancelled:
                    continue

                # interval 任务要重排队
                if task.kind == "interval" and task.interval_sec is not None:
                    with self._lock:
                        if not task.cancelled:
                            task.trigger_ts = time.time() + task.interval_sec
                            self._counter += 1
                            heapq.heappush(self._heap, (task.trigger_ts, self._counter, task))

                # 把 callback 丢回 UI 线程
                self._dispatch_fn(task.callback)

            time.sleep(sleep_sec)


# ========== SkillManager：唯一 skills 表 ==========

class SkillManager:
    """
    - 持有全局唯一的 skills 表
    - 负责创建 / 结束 skill
    - 为 skill 创建 schedule / interval 任务
    """

    def __init__(self, scheduler: TaskScheduler):
        self.scheduler = scheduler
        self.skills: Dict[str, Skill] = {}
        self.skill_counter = 0
        self.task_counter = 0

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
        - 用 ui_adapter 创建对应的 Tab + Frame
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

    def end_skill(self, skill_id: str):
        """
        结束 skill：
        - 取消该 skill 所有任务
        - 删除 UI 容器（frame + Tab 按钮）
        - 从 skills 表里删掉
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

    def add_interval(self, skill_id: str, interval_sec: float, callback: TaskCallback) -> SkillTask:
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
        self.scheduler.schedule_task(task)
        return task

    def add_schedule(self, skill_id: str, delay_sec: float, callback: TaskCallback) -> SkillTask:
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
        self.scheduler.schedule_task(task)
        return task

    def _skill_to_dict(self, skill: Skill) -> dict:
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

    def get_all_skills_data(self) -> dict:
        return {
            "skills": [self._skill_to_dict(skill) for skill in self.skills.values()],
        }

    def export_skills_json(self, pretty: bool = True) -> str:
        data = self.get_all_skills_data()
        if pretty:
            return json.dumps(data, ensure_ascii=False, indent=2)
        else:
            return json.dumps(data, ensure_ascii=False)


# ========== DEMO 入口 ==========

def run_demo():
    # 1. 初始化 UI（用你真实工程的 ui_adapter）
    root = ui_adapter.init_root(title="Skill Engine Demo (integrated)")

    # 2. 启动摄像头守护线程
    try:
        vision_service.start_camera_daemon()
    except Exception as e:
        print("[demo] start_camera_daemon error:", e)

    # 3. 初始化调度器 & manager（所有回调都通过 run_on_ui_thread 回到 Tk 主线程）
    scheduler = TaskScheduler(dispatch_fn=ui_adapter.run_on_ui_thread)
    scheduler.start()
    manager = SkillManager(scheduler=scheduler)

    # ========== Skill 1：时钟（interval） ==========

    clock_skill = manager.create_skill("Clock Skill", raw_request="每秒更新时间")
    # 在这个 skill 的 frame 上放一个 Label
    clock_label = tk.Label(clock_skill.frame, text="--:--:--", font=("Consolas", 20))
    clock_label.pack(padx=10, pady=10, anchor="w")

    def update_clock():
        clock_label.config(text=time.strftime("%H:%M:%S"))

    manager.add_interval(clock_skill.skill_id, interval_sec=1.0, callback=update_clock)

    # ========== Skill 2：一次性提醒（schedule） ==========

    reminder_skill = manager.create_skill("Reminder Skill", raw_request="5 秒后提醒我")
    reminder_label = tk.Label(reminder_skill.frame, text="等待 5 秒后触发提醒...", font=("Consolas", 14))
    reminder_label.pack(padx=10, pady=10, anchor="w")

    def remind_once():
        reminder_label.config(text="✅ Reminder triggered by schedule task")

    manager.add_schedule(reminder_skill.skill_id, delay_sec=5.0, callback=remind_once)

    # ========== Skill 3：摄像头检测（interval + vision） ==========

    vision_skill = manager.create_skill("Vision Monitor Skill", raw_request="我在不在比耶")

    vision_status_label = tk.Label(vision_skill.frame, text="Waiting for first detection...", font=("Consolas", 14))
    vision_status_label.pack(padx=10, pady=8, anchor="w")

    vision_detail_label = tk.Label(vision_skill.frame, text="", font=("Consolas", 11))
    vision_detail_label.pack(padx=10, pady=4, anchor="w")

    def detect_phone():
        """
        每次 interval 触发：
        - 用 vision_service.ask_bool_async 基于当前画面 + 问题做一次 YES/NO 判断
        - ask_bool_async 内部应使用 ui_adapter.run_on_ui_thread 回调 on_result
        """
        def on_result(is_true: bool):
            # 这个回调会在 UI 线程里执行（由 vision_service 保证）
            text = "📱 看起来你在看手机" if is_true else "🙂 暂时没检测到你在看手机"
            vision_status_label.config(text=text)
            # 这里可以加点 debug 信息，比如时间戳
            vision_detail_label.config(text=f"Last checked at: {time.strftime('%H:%M:%S')}")

        try:
            vision_service.ask_bool_async(
                "Is the user drink water?",
                on_result=on_result,
            )
        except AttributeError:
            # 如果你还没重构 vision_service，没有 ask_bool_async，会走这里
            vision_status_label.config(text="❌ vision_service.ask_bool_async() 不存在，请先重构 VisionService。")
        except Exception as e:
            vision_status_label.config(text=f"❌ Vision error: {e}")

    # 每 4 秒检测一次
    manager.add_interval(vision_skill.skill_id, interval_sec=4.0, callback=detect_phone)

    def export_memory():
        json_text = manager.export_skills_json()
        print(json_text)

    ui_adapter.create_button(
        text="导出 Skills Memory",
        row=0,
        column=1,
        command=export_memory
    )

    # 默认激活第一个 skill 的 Tab
    ui_adapter.activate_skill(clock_skill.skill_id)

    # 关闭窗口时，把 scheduler 和摄像头都停掉
    def on_close():
        scheduler.stop()
        try:
            vision_service.stop_camera_daemon()
        except Exception:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    run_demo()
