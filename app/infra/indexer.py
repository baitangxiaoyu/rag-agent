"""内容索引服务 — 管理文档向量化写入 Qdrant"""

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass

from langchain_core.documents import Document
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
)

from app.config import AIChatConfig
from app.core.embeddings import create_embeddings
from app.infra.chunker import ContentMeta, chunk_content
from app.infra.db import get_all_contents, get_content

logger = logging.getLogger(__name__)

# Qdrant 集合名称（与 TypeScript 版保持一致）
COLLECTION_NAME = "blog_content_chunks"


def generate_point_id(content_id: int, chunk_index: int) -> str:
    """
    生成确定性 Point ID — 相同输入始终产生相同 UUID。

    算法：SHA-1("{contentId}_chunk_{chunkIndex}") 取前 16 字节构造 UUID。
    确保与 TypeScript 版本的 Point ID 生成逻辑兼容。

    参数:
        content_id: 内容 ID
        chunk_index: 块索引

    返回:
        UUID 格式字符串
    """
    raw = f"{content_id}_chunk_{chunk_index}"
    sha1_hash = hashlib.sha1(raw.encode("utf-8")).digest()
    # 取前 16 字节构造 UUID
    point_uuid = uuid.UUID(bytes=sha1_hash[:16])
    return str(point_uuid)


@dataclass
class IndexResult:
    """索引操作结果"""

    success: bool
    chunks: int = 0
    message: str = ""


@dataclass
class RebuildResult:
    """全量重建结果"""

    success: bool
    total_contents: int = 0
    total_chunks: int = 0
    failed: int = 0
    message: str = ""


class ContentIndexer:
    """
    内容索引管理器 — 负责文档向量化写入和删除。

    功能：
    - 索引单篇内容（删除旧向量 → 分块 → Embedding → 写入 Qdrant）
    - 删除内容索引（按 sourceId 过滤删除）
    - 全量重建索引
    """

    # Embedding 失败时指数退避重试配置
    MAX_RETRIES = 5
    BASE_DELAY = 1.0  # 基础延迟（秒）

    def __init__(
        self,
        qdrant_client: AsyncQdrantClient,
        config: AIChatConfig,
        database_url: str,
    ):
        self._qdrant = qdrant_client
        self._config = config
        self._database_url = database_url
        self._embeddings = create_embeddings(config)

    async def index_content(self, content_id: int, content_type: str) -> IndexResult:
        """
        索引单篇内容：读取 → 删除旧向量 → 分块 → Embedding → 写入 Qdrant

        参数:
            content_id: 内容 ID
            content_type: 内容类型（"article" 或 "note"）

        返回:
            IndexResult 包含成功状态和块数
        """
        try:
            # 1. 从数据库读取内容
            content_data = await get_content(
                self._database_url, content_id, content_type
            )
            if content_data is None:
                return IndexResult(
                    success=False, message=f"未找到内容: {content_type}/{content_id}"
                )

            meta, markdown = content_data

            # 2. 删除旧向量（如果存在）
            await self._remove_by_source_id(content_id)

            # 3. 分块
            documents = chunk_content(markdown, meta)
            if not documents:
                return IndexResult(
                    success=True, chunks=0, message="内容为空，无需索引"
                )

            # 4. Embedding + 写入 Qdrant
            await self._embed_and_upsert(documents, content_id)

            logger.info(f"索引完成: {content_type}/{content_id}，共 {len(documents)} 个块")
            return IndexResult(success=True, chunks=len(documents))

        except Exception as e:
            logger.error(f"索引失败: {content_type}/{content_id}，错误: {e}")
            return IndexResult(success=False, message=f"索引失败: {e}")

    async def remove_content_index(self, content_id: int) -> bool:
        """
        删除指定内容的所有向量点（按 sourceId 过滤）

        参数:
            content_id: 内容 ID

        返回:
            是否删除成功
        """
        try:
            await self._remove_by_source_id(content_id)
            logger.info(f"已删除内容索引: {content_id}")
            return True
        except Exception as e:
            logger.error(f"删除索引失败: {content_id}，错误: {e}")
            return False

    async def rebuild_index(self) -> RebuildResult:
        """
        全量重建索引：删除集合所有数据并重新索引所有内容

        返回:
            RebuildResult 包含统计信息
        """
        try:
            # 获取所有内容
            all_contents = await get_all_contents(self._database_url)
            if not all_contents:
                return RebuildResult(
                    success=True, message="数据库中无内容，跳过重建"
                )

            # 删除集合中所有向量点
            try:
                await self._qdrant.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=Filter(must=[]),
                )
            except Exception:
                # 集合可能不存在或为空，忽略删除错误
                pass

            total_chunks = 0
            failed = 0

            for content_id, content_type in all_contents:
                result = await self.index_content(content_id, content_type)
                if result.success:
                    total_chunks += result.chunks
                else:
                    failed += 1

            return RebuildResult(
                success=failed == 0,
                total_contents=len(all_contents),
                total_chunks=total_chunks,
                failed=failed,
                message=f"重建完成: {len(all_contents)} 篇内容，{total_chunks} 个块，{failed} 个失败",
            )

        except Exception as e:
            logger.error(f"全量重建失败: {e}")
            return RebuildResult(success=False, message=f"重建失败: {e}")

    async def _remove_by_source_id(self, content_id: int) -> None:
        """按 sourceId 过滤删除所有向量点"""
        await self._qdrant.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="sourceId",
                        match=MatchValue(value=content_id),
                    )
                ]
            ),
        )

    async def _embed_and_upsert(
        self, documents: list[Document], content_id: int
    ) -> None:
        """
        对文档列表进行 Embedding 并写入 Qdrant。
        Embedding 失败时使用指数退避重试（最多 5 次）。
        """
        # 提取文本内容
        texts = [doc.page_content for doc in documents]

        # 带重试的 Embedding
        vectors = await self._embed_with_retry(texts)

        # 构造 Qdrant Point 并写入
        points = []
        for i, doc in enumerate(documents):
            chunk_index = doc.metadata["chunkIndex"]
            point_id = generate_point_id(content_id, chunk_index)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vectors[i],
                    payload=doc.metadata,
                )
            )

        # 批量写入 Qdrant
        await self._qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
        )

    async def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        """
        带指数退避重试的 Embedding 调用。

        最多重试 MAX_RETRIES 次，每次延迟翻倍。
        所有重试失败后抛出最后一次异常。
        """
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                vectors = await self._embeddings.aembed_documents(texts)
                return vectors
            except Exception as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"Embedding 失败（第 {attempt + 1} 次），"
                        f"{delay}s 后重试: {e}"
                    )
                    await asyncio.sleep(delay)

        raise last_error  # type: ignore[misc]
