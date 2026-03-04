# capabilities/vision_service.py
"""
视觉能力（重构版）：

- 全局摄像头守护线程（只打开一次摄像头）
- get_latest_frame_copy(): 获取最近一帧画面
- ask_bool_async(question, on_result): 基于当前画面做 YES/NO 判定（异步）
- answer_with_vision(question): 基于当前画面做自由视觉问答
"""

from __future__ import annotations

import base64
import threading
import time
from typing import Callable, Optional

import cv2
from openai import OpenAI

from config import (
    QWEN_API_KEY,
    QWEN_COMPAT_BASE_URL,
    QWEN_VISION_MODEL,
    CAMERA_CAPTURE_INTERVAL,
)
from . import ui_adapter


BoolCallback = Callable[[bool], None]


class VisionService:
    def __init__(self):
        self._client = OpenAI(
            api_key=QWEN_API_KEY,
            base_url=QWEN_COMPAT_BASE_URL,
        )

        self._camera_lock = threading.Lock()
        self._camera_thread: Optional[threading.Thread] = None
        self._camera_running: bool = False
        self._last_frame = None  # 最近一次抓到的帧（BGR）
        self._capture_interval: float = CAMERA_CAPTURE_INTERVAL

    # ---------- 摄像头守护 ----------

    @staticmethod
    def _frame_to_base64(frame) -> str:
        """把 OpenCV 图像编码成 JPEG base64 字符串"""
        ok, buffer = cv2.imencode(".jpg", frame)
        if not ok:
            raise RuntimeError("Failed to encode frame to JPEG.")
        return base64.b64encode(buffer).decode("utf-8")

    def _camera_loop(self):
        """全局摄像头守护线程：每 self._capture_interval 秒抓一帧，写入 _last_frame"""
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[vision_service] ERROR: cannot open camera 0")
            self._camera_running = False
            return

        print("[vision_service] camera loop started")

        try:
            while self._camera_running:
                ret, frame = cap.read()
                if ret:
                    with self._camera_lock:
                        self._last_frame = frame
                else:
                    print("[vision_service] WARN: failed to grab frame from camera")
                time.sleep(self._capture_interval)
        finally:
            cap.release()
            print("[vision_service] camera loop stopped")

    def _ensure_camera_started(self):
        """内部使用：确保摄像头守护线程已经启动（懒启动）"""
        if self._camera_thread is not None and self._camera_thread.is_alive():
            return

        self._camera_running = True
        self._camera_thread = threading.Thread(
            target=self._camera_loop,
            daemon=True,
        )
        self._camera_thread.start()

    def start_camera_daemon(self):
        """
        对外接口：
        - 在程序启动时调用，启动全局摄像头守护线程。
        - 如果已经启动，则什么都不做。
        """
        self._ensure_camera_started()

    def stop_camera_daemon(self):
        """
        手动停止全局摄像头守护线程。
        一般不需要主动调用，进程退出时会自动结束。
        """
        self._camera_running = False

    def _get_latest_frame_copy_internal(self):
        """内部方法：获取最近一帧的浅拷贝（可能为 None），不强制启动摄像头"""
        with self._camera_lock:
            if self._last_frame is None:
                return None
            return self._last_frame.copy()

    def get_latest_frame_copy(self):
        """
        对外接口：
        - 确保摄像头已启动
        - 返回最近一帧的拷贝（可能为 None）
        """
        self._ensure_camera_started()
        return self._get_latest_frame_copy_internal()

    # ---------- YES/NO 判定（异步） ----------

    def _ask_qwen_bool(self, frame, question: str) -> bool:
        """
        调用千问多模态，对给定 frame + question 做 YES/NO 判断。
        要求 question 是一个英语是/否问题。
        """
        img_b64 = self._frame_to_base64(frame)

        completion = self._client.chat.completions.create(
            model=QWEN_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "You are an assistant that answers YES or NO only.\n"
                                f"Question: {question}\n"
                                "Answer strictly with a single word: YES or NO."
                            ),
                        },
                    ],
                }
            ],
        )

        text = completion.choices[0].message.content.strip().upper()
        if "YES" in text and "NO" not in text:
            return True
        if "NO" in text and "YES" not in text:
            return False
        return False

    def ask_bool_async(self, question: str, on_result: BoolCallback) -> None:
        """
        对外接口（供 skill 使用）：

        - question: 英语是/否问题
        - on_result(is_true: bool): 回调，会在 UI 线程中被调用

        不再内部维护 interval，谁想循环调用，就在自己的 Skill 任务里加 interval。
        """
        self._ensure_camera_started()

        frame = self._get_latest_frame_copy_internal()
        if frame is None:
            # 还没抓到帧，直接在 UI 线程上回调 False 或忽略
            print("[vision_service] WARN: no frame available yet in ask_bool_async()")

            def _cb_false():
                try:
                    on_result(False)
                except Exception as ex:
                    print("[vision_service] ERROR in on_result callback (no frame):", ex)

            try:
                ui_adapter.run_on_ui_thread(_cb_false)
            except Exception as ex:
                print("[vision_service] ERROR scheduling UI callback (no frame):", ex)
            return

        # 用子线程做网络调用，避免阻塞 Tk 主线程
        def worker(local_frame):
            try:
                result = self._ask_qwen_bool(local_frame, question)
            except Exception as e:
                print("[vision_service] ERROR in _ask_qwen_bool:", e)
                result = False

            def _call_cb():
                try:
                    on_result(result)
                except Exception as ex:
                    print("[vision_service] ERROR in on_result callback:", ex)

            try:
                ui_adapter.run_on_ui_thread(_call_cb)
            except Exception as ex:
                print("[vision_service] ERROR scheduling UI callback:", ex)

        threading.Thread(target=worker, args=(frame,), daemon=True).start()

    # ---------- 普通视觉问答（一次性） ----------

    def answer_with_vision(self, question: str) -> str:
        """
        基于当前摄像头画面 + 自然语言问题，做一次自由问答（非 YES/NO）。
        """
        self._ensure_camera_started()

        frame = self._get_latest_frame_copy_internal()
        if frame is None:
            raise RuntimeError("no camera frame available yet")

        img_b64 = self._frame_to_base64(frame)

        completion = self._client.chat.completions.create(
            model=QWEN_VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个视觉助手，只能根据给出的图片和用户的问题回答。"
                        "请用简洁自然的中文回答，不要编造图片中不存在的内容，回答要简短，"
                        "也不要讨论与你看不到的世界相关的话题。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{img_b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": question,
                        },
                    ],
                },
            ],
        )

        return completion.choices[0].message.content.strip()


# 单例 + 兼容调用方式

_service = VisionService()

start_camera_daemon = _service.start_camera_daemon
stop_camera_daemon = _service.stop_camera_daemon
get_latest_frame_copy = _service.get_latest_frame_copy
ask_bool_async = _service.ask_bool_async
answer_with_vision = _service.answer_with_vision
