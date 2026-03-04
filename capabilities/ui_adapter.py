# capabilities/ui_adapter.py
"""
UI 适配层：
- 负责 Tk 主窗口、聊天区、多 skill Tab 容器
- 给 skill 提供 create_label / create_button 这些 UI 原语
- 提供 run_on_ui_thread，供后台线程安全更新 UI
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional, Dict, Any

_root: Optional[tk.Tk] = None

_chat_text: Optional[tk.Text] = None
_input_entry: Optional[tk.Entry] = None
_on_user_input_cb: Optional[Callable[[str], None]] = None

_tab_frame: Optional[tk.Frame] = None          # 放 Tab 按钮
_content_frame: Optional[tk.Frame] = None      # 放各个 skill 的 Frame

_skill_frames: Dict[str, tk.Frame] = {}        # skill_id -> Frame
_tab_buttons: Dict[str, tk.Button] = {}        # skill_id -> Button
_active_skill_id: Optional[str] = None

_current_skill_frame: Optional[tk.Frame] = None  # 当前 skill 注册时使用的容器（给 create_label 用）


# ========== 基本输入逻辑 ==========

def _on_send_clicked():
    global _input_entry, _on_user_input_cb
    if _input_entry is None:
        return
    text = _input_entry.get().strip()
    if not text:
        return
    _input_entry.delete(0, tk.END)
    if _on_user_input_cb:
        _on_user_input_cb(text)


def init_root(title: str = "AI Desktop Core", on_user_input=None):
    """
    初始化主窗口：
    - row0: 聊天区 (Text)
    - row1: Tab 栏（每个 skill 一个按钮）
    - row2: 内容区（多个 skill Frame 叠放，按 Tab 切换显示）
    - row3: 输入区（Entry + Send）
    """
    global _root, _chat_text, _input_entry, _on_user_input_cb
    global _tab_frame, _content_frame

    root = tk.Tk()
    root.title(title)

    # 顶部聊天区
    _chat_text = tk.Text(root, height=10, width=80, state="disabled", wrap="word")
    _chat_text.grid(row=0, column=0, padx=10, pady=5, sticky="nsew")

    # Tab 栏
    _tab_frame = tk.Frame(root)
    _tab_frame.grid(row=1, column=0, padx=10, pady=2, sticky="ew")

    # 中间 skill 内容区
    _content_frame = tk.Frame(root)
    _content_frame.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")

    # 底部输入区
    input_frame = tk.Frame(root)
    input_frame.grid(row=3, column=0, padx=10, pady=5, sticky="ew")

    _input_entry = tk.Entry(input_frame)
    _input_entry.pack(side="left", fill="x", expand=True)

    send_btn = tk.Button(input_frame, text="Send", command=_on_send_clicked)
    send_btn.pack(side="left", padx=5)

    _on_user_input_cb = on_user_input

    # 回车发送
    _input_entry.bind("<Return>", lambda event: _on_send_clicked())

    # 总布局自适应
    root.grid_rowconfigure(0, weight=3)  # chat
    root.grid_rowconfigure(1, weight=0)  # tabs
    root.grid_rowconfigure(2, weight=2)  # content
    root.grid_rowconfigure(3, weight=0)  # input
    root.grid_columnconfigure(0, weight=1)

    # 内容区内部也要自适应
    _content_frame.grid_rowconfigure(0, weight=1)
    _content_frame.grid_columnconfigure(0, weight=1)

    _root = root
    return root


def get_root() -> Optional[tk.Tk]:
    return _root


def append_chat(role: str, text: str):
    """在聊天区追加一条信息"""
    global _chat_text
    if _chat_text is None:
        return
    _chat_text.config(state="normal")
    _chat_text.insert("end", f"{role}: {text}\n")
    _chat_text.see("end")
    _chat_text.config(state="disabled")


# ========== 多 skill / Tab 相关 ==========

def create_skill_container(skill_id: str, title: str):
    """
    为一个 skill 创建：
    - 一个内容 Frame（挂在 _content_frame 下）
    - 一个 Tab 按钮（挂在 _tab_frame 下）

    返回这个 Frame，runtime 会在 register() 时把当前 skill 的控件都挂到这里。
    """
    global _skill_frames, _tab_buttons, _tab_frame, _content_frame

    if _content_frame is None or _tab_frame is None:
        raise RuntimeError("init_root() must be called before creating skill containers.")

    # 内容 Frame，先不显示（由 activate_skill 决定）
    frame = tk.Frame(_content_frame, borderwidth=1, relief="groove")
    frame.grid(row=0, column=0, sticky="nsew")
    frame.grid_remove()  # 初始隐藏

    _skill_frames[skill_id] = frame

    # Tab 按钮
    def _on_tab_clicked(sid=skill_id):
        activate_skill(sid)

    btn = tk.Button(_tab_frame, text=title, command=_on_tab_clicked)
    btn.pack(side="left", padx=4)
    _tab_buttons[skill_id] = btn

    return frame


def activate_skill(skill_id: str):
    """
    切换当前显示的 skill：
    - 显示该 skill 对应的 Frame
    - 隐藏其他 skill Frame
    - 更新 Tab 按钮样式
    """
    global _active_skill_id

    if skill_id not in _skill_frames:
        return

    # 显示选中的 frame，隐藏其他
    for sid, frame in _skill_frames.items():
        if sid == skill_id:
            frame.grid(row=0, column=0, sticky="nsew")
            frame.tkraise()
        else:
            frame.grid_remove()

    # 更新 tab 样式
    for sid, btn in _tab_buttons.items():
        if sid == skill_id:
            btn.config(relief="sunken")
        else:
            btn.config(relief="raised")

    _active_skill_id = skill_id


def remove_skill_container(skill_id: str):
    """
    删除某个 skill 的 UI 容器和 Tab。
    当前在主流程中暂未调用，但为未来“关闭 skill”预留。
    """
    frame = _skill_frames.pop(skill_id, None)
    if frame is not None:
        try:
            frame.destroy()
        except tk.TclError:
            pass

    btn = _tab_buttons.pop(skill_id, None)
    if btn is not None:
        try:
            btn.destroy()
        except tk.TclError:
            pass

    # 若当前移除的是 active skill，可以考虑激活其他 skill，这里先不处理。


# ========== 当前 skill 容器上下文（给 create_label 用） ==========

def set_current_skill_frame(frame: tk.Frame):
    """在 runtime 加载某个 skill 时调用，后续 create_label/create_button 都挂在这个 frame 上。"""
    global _current_skill_frame
    _current_skill_frame = frame


def clear_current_skill_frame():
    global _current_skill_frame
    _current_skill_frame = None


def _widget_alive(widget) -> bool:
    """检查控件是否还活着（没有被 destroy）"""
    if widget is None:
        return False
    try:
        exists = widget.winfo_exists()
    except Exception:
        return False
    return bool(exists)


# ========== UI 线程调度工具 ==========

def run_on_ui_thread(callback: Callable[[], None]):
    """
    在 Tk 主线程中执行回调：
    - 供 time_engine 等后台线程安全地更新 UI 使用
    """
    root = get_root()
    if root is None:
        return
    try:
        root.after(0, callback)
    except tk.TclError:
        # 窗口可能已经关闭
        return


# ========== 给 skill 用的 UI 原语 ==========

def create_label(
    text: str = "",
    row: int = 0,
    column: int = 0,
    font=("Consolas", 18),
):
    """
    给 skill 用的 label 创建函数：
    - 优先挂在当前 skill 的 frame 上
    - 如果没有当前 skill，就退回到内容区/根窗口
    """
    parent: Any = _current_skill_frame or _content_frame or _root
    if parent is None:
        raise RuntimeError("UI root is not initialized.")
    label = tk.Label(parent, text=text, font=font)
    label.grid(row=row, column=column, padx=10, pady=10)
    return label


def set_label_text(label, text: str):
    """
    安全更新 Label 文本：
    - 如果控件已经被 destroy 或不再存在，直接忽略，不抛异常。
    """
    if not _widget_alive(label):
        return
    try:
        label.config(text=text)
    except tk.TclError:
        return


def create_button(text: str, row: int, column: int, command: Callable[[], None]):
    parent: Any = _current_skill_frame or _content_frame or _root
    if parent is None:
        raise RuntimeError("UI root is not initialized.")
    btn = tk.Button(parent, text=text, command=command)
    btn.grid(row=row, column=column, padx=5, pady=5)
    return btn


def set_interval(callback: Callable[[], None], ms: int):
    """
    旧版 UI 定时器封装（兼容保留）：
    - 新的时间相关逻辑应尽量使用 time_engine 中的全局时间引擎。
    - 这里仍然通过 root.after 实现，返回 cancel() 用于取消。
    """
    root = get_root()
    if root is None:
        raise RuntimeError("Root window is not initialized.")

    flags = {"cancelled": False}

    def _wrapper():
        if flags["cancelled"]:
            return
        callback()
        try:
            root.after(ms, _wrapper)
        except tk.TclError:
            # 窗口已关闭
            return

    root.after(ms, _wrapper)

    def cancel():
        flags["cancelled"] = True

    return cancel
