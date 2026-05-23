"""LLM 工厂模块 — 创建兼容 OpenAI API 的大模型客户端"""

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.config import AIChatConfig


def create_llm(config: AIChatConfig) -> ChatOpenAI:
    """
    创建 LLM 实例，兼容所有 OpenAI-compatible API（智谱 AI、Ollama 等）

    参数:
        config: 动态配置，包含 model、api_key、base_url、temperature、max_tokens

    返回:
        ChatOpenAI 实例，已启用流式输出（streaming=True）
    """
    return ChatOpenAI(
        model=config.model,
        api_key=SecretStr(config.api_key),
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        streaming=True,
    )
