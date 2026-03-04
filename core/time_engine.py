# core/time_engine.py
"""
简化版时间引擎：

- 提供时间感知工具函数：now / now_timestamp / now_str / today_str
- start()/stop() 保留为兼容接口，但不再负责调度任务
"""

import time
from datetime import datetime

_running = False


def start():
    """
    兼容旧接口：
    - 目前不再负责任务调度，只标记一下“已启动”，打印一行日志即可。
    """
    global _running
    if _running:
        return
    _running = True
    print("[time_engine] (stub) started: only providing time utilities.")


def stop():
    global _running
    _running = False
    print("[time_engine] (stub) stopped.")


def now() -> datetime:
    """返回当前本地时间（datetime）"""
    return datetime.now()


def now_timestamp() -> float:
    """返回当前时间戳（秒）"""
    return time.time()


def now_str() -> str:
    """返回格式化后的当前时间字符串，例如 '2025-11-28 10:30:00'"""
    return now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    """返回今天日期字符串，例如 '2025-11-28'"""
    return now().strftime("%Y-%m-%d")
