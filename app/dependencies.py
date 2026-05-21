"""依赖注入模块 — 管理 Redis、Qdrant、ConfigManager 的生命周期和注入"""

from fastapi import Depends, Request
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from app.config import AIConfigManager


def get_redis(request: Request) -> Redis:
    """
    获取 Redis 异步客户端（连接池模式）

    通过 app.state 获取在 lifespan 中初始化的 Redis 连接池实例，
    所有请求共享同一连接池，避免重复创建连接。
    """
    return request.app.state.redis


def get_qdrant_client(request: Request) -> AsyncQdrantClient:
    """
    获取 Qdrant 异步客户端

    通过 app.state 获取在 lifespan 中初始化的 Qdrant 客户端实例，
    所有请求共享同一客户端连接。
    """
    return request.app.state.qdrant


def get_config_manager(
    redis: Redis = Depends(get_redis),
) -> AIConfigManager:
    """
    获取配置管理器实例

    每次请求创建新的 AIConfigManager 实例（轻量对象），
    但底层 Redis 连接复用连接池。
    """
    return AIConfigManager(redis_client=redis)
