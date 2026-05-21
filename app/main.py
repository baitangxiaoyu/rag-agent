"""RAG Service - FastAPI 应用入口"""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化资源，关闭时释放连接"""
    logger.info("🚀 RAG Service 启动中...")

    # 初始化 Redis 连接池（decode_responses=False 保持与 bytes 兼容）
    app.state.redis = Redis.from_url(
        settings.redis_url,
        decode_responses=False,
    )
    logger.info(f"✅ Redis 连接池已初始化: {settings.redis_url}")

    # 初始化 Qdrant 异步客户端
    app.state.qdrant = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
    )
    logger.info(f"✅ Qdrant 客户端已初始化: {settings.qdrant_url}")

    yield

    # 关闭 Redis 连接池，释放所有连接
    logger.info("👋 RAG Service 关闭，释放资源...")
    await app.state.redis.close()
    logger.info("✅ Redis 连接池已关闭")

    # 关闭 Qdrant 客户端
    await app.state.qdrant.close()
    logger.info("✅ Qdrant 客户端已关闭")


app = FastAPI(
    title="RAG Agent",
    description="基于 LangChain 的 RAG 检索增强生成服务",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "ok", "service": "rag-service"}
