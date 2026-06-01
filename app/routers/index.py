"""索引管理 API — CRUD 路由"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from qdrant_client import AsyncQdrantClient

from app.config import AIConfigManager, AIChatConfig, settings
from app.dependencies import get_config_manager, get_qdrant_client
from app.infra.indexer import ContentIndexer
from app.schemas.index import IndexRequest, IndexResponse, RebuildResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_indexer(
    qdrant: AsyncQdrantClient = Depends(get_qdrant_client),
    config_manager: AIConfigManager = Depends(get_config_manager),
) -> ContentIndexer:
    """构造 ContentIndexer 实例（依赖注入辅助）"""
    # 同步加载配置不可行，这里用默认配置初始化
    # 实际调用时会在路由中异步加载
    return ContentIndexer(
        qdrant_client=qdrant,
        config=None,  # type: ignore  # 延迟设置
        database_url=settings.database_url,
    )


@router.post("", response_model=IndexResponse)
async def index_content(
    body: IndexRequest,
    qdrant: AsyncQdrantClient = Depends(get_qdrant_client),
    config_manager: AIConfigManager = Depends(get_config_manager),
):
    """
    索引单篇内容

    将指定内容从数据库读取、分块、向量化后写入 Qdrant。
    content_type 限定为 article 或 note（由 Schema 层验证）。
    """
    config: AIChatConfig = await config_manager.load()
    indexer = ContentIndexer(
        qdrant_client=qdrant,
        config=config,
        database_url=settings.database_url,
    )

    result = await indexer.index_content(body.content_id, body.content_type)

    if not result.success:
        return JSONResponse(
            status_code=500,
            content={"success": False, "chunks": 0, "message": result.message},
        )

    return IndexResponse(success=True, chunks=result.chunks, message=result.message)


@router.post("/rebuild", response_model=RebuildResponse)
async def rebuild_index(
    qdrant: AsyncQdrantClient = Depends(get_qdrant_client),
    config_manager: AIConfigManager = Depends(get_config_manager),
):
    """
    全量重建索引

    删除所有现有向量并从数据库重新索引全部内容。
    """
    config: AIChatConfig = await config_manager.load()
    indexer = ContentIndexer(
        qdrant_client=qdrant,
        config=config,
        database_url=settings.database_url,
    )

    result = await indexer.rebuild_index()

    if not result.success:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "totalContents": result.total_contents,
                "totalChunks": result.total_chunks,
                "failed": result.failed,
                "message": result.message,
            },
        )

    return RebuildResponse(
        success=True,
        total_contents=result.total_contents,
        total_chunks=result.total_chunks,
        failed=result.failed,
        message=result.message,
    )


@router.delete("/{content_id}")
async def delete_index(
    content_id: int,
    qdrant: AsyncQdrantClient = Depends(get_qdrant_client),
    config_manager: AIConfigManager = Depends(get_config_manager),
):
    """
    删除指定内容的索引

    按 sourceId 过滤删除该内容的所有向量点。
    """
    config: AIChatConfig = await config_manager.load()
    indexer = ContentIndexer(
        qdrant_client=qdrant,
        config=config,
        database_url=settings.database_url,
    )

    success = await indexer.remove_content_index(content_id)

    if not success:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"删除索引失败: {content_id}"},
        )

    return {"success": True, "message": f"已删除内容 {content_id} 的索引"}
