# config.py
"""
全局配置 & 常量集中管理：
- 所有 API Key / Base URL / 模型名
- 一些全局行为参数（窗口标题、历史长度等）
"""

import os

# ========= DeepSeek 配置 =========
DEEPSEEK_API_KEY: str = "sk-51f5bd4e093e4777b50282be1bb47392"
DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

# 主聊天模型（意图判断 / 普通对话）
DEEPSEEK_CHAT_MODEL: str = "deepseek-chat"

# 如需思维链模型可以单独开一个（当前暂未使用）
DEEPSEEK_REASONING_MODEL: str = "deepseek-reasoner"

# ========= Qwen / DashScope 配置 =========

# 通用 key（视觉 + TTS 都用这个）
QWEN_API_KEY: str = "sk-a28bff0ab57f48b78d4a3041bbcb44a1"

# OpenAI 兼容模式（视觉问答用）
QWEN_COMPAT_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

QWEN_VISION_MODEL: str = "qwen3-vl-flash"

# DashScope 原生 HTTP API（TTS 用）
QWEN_DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/api/v1"

QWEN_TTS_MODEL: str = "qwen3-tts-flash"

QWEN_TTS_VOICE: str = "Cherry"

QWEN_TTS_LANGUAGE: str = "Chinese"

# ========= UI / 运行参数 =========

UI_WINDOW_TITLE: str = "AI Desktop Core"

# DeepSeek 意图判断时保留的历史轮数
INTENT_HISTORY_LIMIT: int = 6

# 摄像头抓帧间隔（秒），vision_service 会用
CAMERA_CAPTURE_INTERVAL: float = 5.0
