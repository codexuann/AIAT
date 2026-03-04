# llm/deepseek_client.py
"""
DeepSeek 通用客户端封装：
- 统一从 config.py 读取 API Key / Base URL
- 提供 get_client() 拿到全局单例 OpenAI 客户端
"""

from __future__ import annotations

from typing import Optional

from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    """
    获取全局 DeepSeek OpenAI 客户端单例。
    """
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
    return _client
