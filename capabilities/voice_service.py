# capabilities/voice_service.py
"""
声音能力（TTS）：
- 调用 Qwen3-TTS 合成语音
- 用 simpleaudio 播放 wav
- 对外提供 speak_async(text) 异步接口
"""

from __future__ import annotations

import os
import tempfile
import threading

import requests
import dashscope
from simpleaudio import WaveObject

from config import (
    QWEN_API_KEY,
    QWEN_DASHSCOPE_BASE_URL,
    QWEN_TTS_MODEL,
    QWEN_TTS_VOICE,
    QWEN_TTS_LANGUAGE,
)

# 配置 DashScope HTTP API 基地址
dashscope.base_http_api_url = QWEN_DASHSCOPE_BASE_URL


class VoiceService:
    def __init__(self):
        self._api_key = QWEN_API_KEY

    def _tts_request(self, text: str) -> bytes:
        """调用 Qwen3-TTS，返回 wav 二进制数据（在子线程里跑）"""
        resp = dashscope.MultiModalConversation.call(
            model=QWEN_TTS_MODEL,
            api_key=self._api_key,
            text=text,
            voice=QWEN_TTS_VOICE,
            language_type=QWEN_TTS_LANGUAGE,
        )

        if not isinstance(resp, dict):
            raise RuntimeError(f"TTS failed with unexpected resp type: {type(resp)}")

        if resp.get("status_code") != 200:
            raise RuntimeError(f"TTS failed: {resp}")

        audio_info = resp.get("output", {}).get("audio")
        if not audio_info or "url" not in audio_info:
            raise RuntimeError(f"TTS failed, no audio url in resp: {resp}")

        audio_url = audio_info["url"]
        audio_data = requests.get(audio_url).content
        return audio_data

    @staticmethod
    def _play_wav_bytes(data: bytes):
        """把 wav 二进制写到临时文件，再用 simpleaudio 播放"""
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                f.write(data)
                tmp_path = f.name

            wave_obj = WaveObject.from_wave_file(tmp_path)
            play_obj = wave_obj.play()
            play_obj.wait_done()
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _worker(self, text: str):
        try:
            data = self._tts_request(text)
            self._play_wav_bytes(data)
        except Exception as e:
            print("[voice_service] speak error:", e)

    def speak_async(self, text: str):
        """
        skill 调用接口：
        - 不阻塞 UI 线程
        - 内部开 daemon 线程做 TTS + 播放
        """
        if not text:
            return
        t = threading.Thread(target=self._worker, args=(text,), daemon=True)
        t.start()


# 单例 + 兼容旧调用方式

_service = VoiceService()

speak_async = _service.speak_async
