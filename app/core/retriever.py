"""向量检索器模块 — 封装 QdrantVectorStore 为 LangChain Retriever"""

import logging
from typing import Optional

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

from app.config import AIChatConfig

logger = logging.getLogger(__name__)

# Qdrant 集合名称（与 TypeScript 服务共享）
COLLECTION_NAME = "blog_content_chunks"

# Qdrant Payload 中需要映射到 Document.metadata 的字段
CONTENT_PAYLOAD_KEY = "chunkText"


class SafeRetriever(VectorStoreRetriever):
    """
    安全检索器 — Qdrant 不可达时返回空列表而非抛出异常

    继承 VectorStoreRetriever，覆写 _get_relevant_documents 方法，
    在检索异常时优雅降级为空列表。
    """

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        """同步检索，异常时返回空列表"""
        try:
            return super()._get_relevant_documents(query, run_manager=run_manager)
        except Exception as e:
            logger.warning(f"Qdrant 检索失败，降级为空列表: {e}")
            return []

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager=None,
        **kwargs,
    ) -> list[Document]:
        """异步检索，异常时返回空列表"""
        try:
            return await super()._aget_relevant_documents(
                query, run_manager=run_manager, **kwargs
            )
        except Exception as e:
            logger.warning(f"Qdrant 异步检索失败，降级为空列表: {e}")
            return []


def create_retriever(
    embeddings: OpenAIEmbeddings,
    config: AIChatConfig,
    qdrant_url: str,
    qdrant_api_key: Optional[str] = None,
) -> SafeRetriever:
    """
    创建带阈值过滤和异常降级的向量检索器

    复用现有 Qdrant 集合 blog_content_chunks，
    Payload 字段: sourceId, sourceType, title, categoryName, chunkIndex, chunkText

    参数:
        embeddings: OpenAIEmbeddings 实例（用于查询向量化）
        config: 动态配置（包含 top_k 和 score_threshold）
        qdrant_url: Qdrant 服务地址
        qdrant_api_key: Qdrant API 密钥（可选）

    返回:
        SafeRetriever — Qdrant 不可达时返回空列表
    """
    # 使用 from_existing_collection 连接已有集合
    vector_store = QdrantVectorStore.from_existing_collection(
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        url=qdrant_url,
        api_key=qdrant_api_key,
        # 指定 Payload 中存储文本内容的字段名
        content_payload_key=CONTENT_PAYLOAD_KEY,
    )

    # 创建检索器：相似度分数阈值过滤 + top_k 限制
    retriever = vector_store.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={
            "k": config.top_k,
            "score_threshold": config.score_threshold,
        },
    )
    # 将标准 VectorStoreRetriever 替换为带异常降级的 SafeRetriever
    # 使用 SafeRetriever 包装器，在 Qdrant 服务不可达或检索失败时优雅降级
    # 返回空列表而非抛出异常，确保应用稳定性
    safe_retriever = SafeRetriever(
        vectorstore=retriever.vectorstore,  # 复用已配置的 QdrantVectorStore 实例
        search_type=retriever.search_type,  # 保持原有的搜索类型（similarity_score_threshold）
        search_kwargs=retriever.search_kwargs,  # 保持原有的搜索参数（k 和 score_threshold）
    )

    return safe_retriever
