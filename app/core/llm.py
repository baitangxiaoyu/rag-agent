"""LLM 工厂模块 — 创建兼容 OpenAI API 的大模型客户端，含指数退避重试"""

import asyncio
import logging

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.config import AIChatConfig

logger = logging.getLogger(__name__)

# 重试配置
MAX_RETRIES = 3
BASE_DELAY = 1.0  # 基础延迟（秒）


def create_llm(config: AIChatConfig) -> ChatOpenAI:
    """
    创建 LLM 实例，兼容所有 OpenAI-compatible API（智谱 AI、Ollama 等）

    参数:
        config: 动态配置，包含 model、api_key、base_url、temperature、max_tokens

    返回:
        ChatOpenAI 实例，已启用流式输出（streaming=True），
        配置 max_retries=3 实现 HTTP 层重试
    """
    return ChatOpenAI(
        model=config.model,
        api_key=SecretStr(config.api_key),
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        streaming=True,
        max_retries=MAX_RETRIES,
        request_timeout=30,
    )


async def invoke_with_retry(llm: ChatOpenAI, messages: list, max_retries: int = MAX_RETRIES) -> str:
    """
    带指数退避重试的 LLM 调用（用于非流式场景）。

    最多重试 max_retries 次，每次延迟翻倍。
    所有重试失败后返回友好错误消息。

    参数:
        llm: ChatOpenAI 实例
        messages: 消息列表
        max_retries: 最大重试次数

    返回:
        LLM 响应文本，或错误提示
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            result = await llm.ainvoke(messages)
            return result.content
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(f"LLM 调用失败（第 {attempt + 1} 次），{delay}s 后重试: {e}")
                await asyncio.sleep(delay)

    logger.error(f"LLM 调用最终失败: {last_error}")
    return "抱歉，AI 服务暂时不可用，请稍后重试。"
