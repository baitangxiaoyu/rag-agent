"""RAG Service - FastAPI 应用入口"""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化资源，关闭时释放连接"""
    logger.info("🚀 RAG Service 启动中...")
    # TODO: 初始化 Redis 连接池、Qdrant 客户端
    yield
    logger.info("👋 RAG Service 关闭，释放资源...")
    # TODO: 关闭 Redis 连接池、Qdrant 客户端


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
