"""RAG 链编排模块 — 使用 LCEL 组合查询改写、向量检索、提示词构建、LLM 生成"""

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough

from app.config import AIChatConfig, settings
from app.core.embeddings import create_embeddings
from app.core.llm import create_llm
from app.core.prompt import build_messages, build_prompt_template
from app.core.query_rewriter import create_query_rewriter
from app.core.retriever import create_retriever


@dataclass
class SourceInfo:
    """检索来源信息"""

    title: str
    source_id: int
    source_type: str
    category_name: str

    def to_dict(self) -> dict:
        """转换为字典（camelCase 键名，兼容前端）"""
        return {
            "title": self.title,
            "sourceId": self.source_id,
            "sourceType": self.source_type,
            "categoryName": self.category_name,
        }


def extract_sources(documents: list[Document]) -> list[dict]:
    """
    从检索文档中提取来源信息

    参数:
        documents: 检索到的文档列表

    返回:
        去重后的来源信息列表（字典格式，camelCase 键名）
    """
    if not documents:
        return []

    seen_ids: set[tuple] = set()
    sources: list[dict] = []

    for doc in documents:
        metadata = doc.metadata
        source_id = metadata.get("sourceId", 0)
        source_type = metadata.get("sourceType", "")
        title = metadata.get("title", "")
        category_name = metadata.get("categoryName", "")

        # 按 sourceId + sourceType 去重
        key = (source_id, source_type)
        if key in seen_ids:
            continue
        seen_ids.add(key)

        info = SourceInfo(
            title=title,
            source_id=source_id,
            source_type=source_type,
            category_name=category_name,
        )
        sources.append(info.to_dict())

    return sources


def create_rag_chain(config: AIChatConfig) -> Runnable:
    """
    构建 RAG 链

    输入: {"query": str, "history": list}
    输出: str（纯文本字符串）

    LCEL 编排顺序:
    1. 查询改写（可选）→ 生成 rewritten_query
    2. 向量检索 → 使用 rewritten_query 检索相关文档
    3. 提示词构建 → 组装 system_with_context + history + query
    4. LLM 生成 → 流式输出文本
    5. StrOutputParser → 提取纯文本

    支持 .invoke() 同步调用和 .astream() 流式调用

    未来 LangGraph 迁移时:
        @tool
        def search_blog(query: str) -> str:
            chain = create_rag_chain(config)
            return chain.invoke({"query": query, "history": []})
    """
    # 创建各组件
    llm = create_llm(config)
    embeddings = create_embeddings(config)
    retriever = create_retriever(
        embeddings=embeddings,
        config=config,
        qdrant_url=settings.qdrant_url,
        qdrant_api_key=settings.qdrant_api_key,
    )
    rewriter = create_query_rewriter(config)
    prompt_template = build_prompt_template()

    # Step 1: 查询改写（根据配置决定是否启用）
    async def _rewrite_step(inputs: dict) -> str:
        """执行查询改写，未启用时直接返回原始查询"""
        if config.query_rewrite_enabled:
            return await rewriter.ainvoke({
                "query": inputs["query"],
                "history": inputs.get("history", []),
            })
        return inputs["query"]

    # Step 2: 向量检索
    async def _retrieve_step(inputs: dict) -> list[Document]:
        """使用改写后的查询进行向量检索"""
        rewritten_query = inputs["rewritten_query"]
        return await retriever.ainvoke(rewritten_query)

    # Step 3: 提示词构建
    def _build_prompt_input(inputs: dict) -> dict:
        """构建 ChatPromptTemplate 所需的输入字典"""
        return build_messages(
            query=inputs["query"],
            documents=inputs["documents"],
            history=inputs.get("history", []),
            system_prompt=config.system_prompt or None,
        )

    # 使用 LCEL 编排完整链
    chain: Runnable = (
        # 输入: {"query": str, "history": list}
        RunnablePassthrough.assign(
            rewritten_query=RunnableLambda(_rewrite_step)
        )
        # 添加检索结果
        | RunnablePassthrough.assign(
            documents=RunnableLambda(_retrieve_step)
        )
        # 构建提示词输入并传入 prompt template
        | RunnableLambda(_build_prompt_input)
        # 生成 ChatPromptValue
        | prompt_template
        # LLM 生成（支持流式）
        | llm
        # 提取纯文本
        | StrOutputParser()
    )

    return chain
