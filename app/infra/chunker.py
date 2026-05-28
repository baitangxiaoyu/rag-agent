"""Markdown 感知文本分块器 — 将长文档按语义分段并切分为适合嵌入的块"""

from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)


@dataclass
class ContentMeta:
    """内容元数据，描述待分块文档的基础信息"""

    content_id: int
    content_type: str  # "article" 或 "note"
    title: str
    category_name: str
    create_time: str


def chunk_content(markdown: str, meta: ContentMeta) -> list[Document]:
    """
    将 Markdown 内容按语义分块，返回带元数据的 Document 列表。

    处理流程：
    1. 按 ## 标题分段
    2. 按 token 数切分（上限 512，重叠 50）
    3. 注入语义前缀 [{title}] [{section}]
    4. 构造 Document，包含完整 metadata

    参数:
        markdown: 原始 Markdown 文本
        meta: 内容元数据

    返回:
        Document 列表，每个 Document 的 page_content 带语义前缀，metadata 包含索引信息
    """
    if not markdown or not markdown.strip():
        return []

    # Step 1: 按 ## 标题分段
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("##", "section")],
        strip_headers=False,
    )
    header_splits = header_splitter.split_text(markdown)

    # Step 2: 按 token 切分
    token_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=512,
        chunk_overlap=50,
    )

    # Step 3 & 4: 注入语义前缀并构造 Document
    documents: list[Document] = []
    chunk_index = 0

    for header_doc in header_splits:
        # 获取 section 标题
        section = header_doc.metadata.get("section", "")

        # 对每个分段进行 token 级别切分
        sub_chunks = token_splitter.split_text(header_doc.page_content)

        for chunk_text in sub_chunks:
            # 构造语义前缀
            if section:
                prefix = f"[{meta.title}] [{section}] "
            else:
                prefix = f"[{meta.title}] "

            page_content = prefix + chunk_text

            doc = Document(
                page_content=page_content,
                metadata={
                    "sourceId": meta.content_id,
                    "sourceType": meta.content_type,
                    "title": meta.title,
                    "categoryName": meta.category_name,
                    "chunkIndex": chunk_index,
                    "chunkText": chunk_text,
                    "createTime": meta.create_time,
                },
            )
            documents.append(doc)
            chunk_index += 1

    return documents
