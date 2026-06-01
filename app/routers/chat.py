"""SSE 流式聊天 API — POST /chat 端点"""

import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.config import AIConfigManager, AIChatConfig
from app.core.chain import create_rag_chain, extract_sources
from app.core.chat_history import RedisChatHistory, create_message
from app.core.retriever import create_retriever
from app.core.embeddings import create_embeddings
from app.config import settings
from app.dependencies import get_config_manager, get_redis
from app.infra.security import validate_input
from app.schemas.chat import ChatRequest

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat")
async def chat(
    request: Request,
    body: ChatRequest,
    redis: Redis = Depends(get_redis),
    config_manager: AIConfigManager = Depends(get_config_manager),
):
    """
    SSE 流式聊天端点

    流程：安全过滤 → 获取/创建会话 → 构建 RAG 链 → 流式输出
    事件类型：
    - token: 逐个 token 流式输出
    - sources: 检索来源信息
    - done: 流结束标记
    - error: 错误信息
    """
    # 1. 安全过滤
    filter_result = validate_input(body.message)
    if not filter_result.passed:
        return JSONResponse(
            status_code=400,
            content={"error": filter_result.reason},
        )

    # 2. 获取或创建会话
    client_ip = request.client.host if request.client else ""
    chat_history = RedisChatHistory(redis)
    session = await chat_history.get_or_create(body.session_id, client_ip)

    # 3. 加载配置并构建 RAG 链
    config: AIChatConfig = await config_manager.load()

    # 4. 构造历史消息（最近 10 条，即 5 轮对话）
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in session.messages[-10:]
    ]

    async def event_generator() -> AsyncGenerator[dict, None]:
        """SSE 事件生成器"""
        full_response = ""
        documents = []

        try:
            # 构建 RAG 链
            chain = create_rag_chain(config)

            # 先执行检索获取来源（通过中间步骤）
            # 使用 astream_events 获取中间结果和最终输出
            async for event in chain.astream_events(
                {"query": body.message, "history": history},
                version="v2",
            ):
                kind = event["event"]

                # 捕获检索结果（中间步骤）
                if kind == "on_retriever_end":
                    documents = event.get("data", {}).get("output", [])

                # 捕获 LLM 流式输出的 token
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        token = chunk.content
                        full_response += token
                        yield {
                            "data": json.dumps(
                                {"type": "token", "content": token},
                                ensure_ascii=False,
                            )
                        }

        except Exception as e:
            logger.error(f"RAG 链执行失败: {e}")
            yield {
                "data": json.dumps(
                    {"type": "error", "content": "服务暂时不可用，请稍后重试"},
                    ensure_ascii=False,
                )
            }
            return

        # 发送检索来源
        sources = extract_sources(documents)
        if sources:
            yield {
                "data": json.dumps(
                    {"type": "sources", "content": sources},
                    ensure_ascii=False,
                )
            }

        # 发送完成标记
        yield {
            "data": json.dumps(
                {"type": "done", "content": ""},
                ensure_ascii=False,
            )
        }

        # 保存对话历史（用户消息 + AI 回复）
        try:
            user_msg = create_message("user", body.message)
            await chat_history.append_message(session.session_id, user_msg)

            assistant_msg = create_message("assistant", full_response)
            await chat_history.append_message(session.session_id, assistant_msg)
        except Exception as e:
            logger.warning(f"保存对话历史失败（不影响响应）: {e}")

    return EventSourceResponse(event_generator())
