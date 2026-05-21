# 设计文档：RAG 服务迁移 (TypeScript → Python + LangChain)

## Overview

本设计文档描述将现有 Next.js 项目中的 RAG 模块（`src/lib/rag/`）迁移为独立 Python 服务的技术方案。服务使用 FastAPI 作为 Web 框架，LangChain LCEL 编排 RAG 流程，Qdrant 作为向量存储，Redis 管理配置与会话，MySQL 读取文章内容。

核心设计目标：
1. **功能等价**：与现有 TypeScript 实现完全兼容，共享 Redis 键、Qdrant 集合
2. **渐进式迁移**：Python 服务可与 TypeScript 服务并存，通过 HTTP 代理无感切换
3. **LangGraph 预留**：`create_rag_chain()` 返回 Runnable，未来可直接包装为 Agent Tool

## Architecture

### 系统全景

```mermaid
graph TB
    subgraph "前端 Next.js 博客"
        FE[前端页面]
        API[Next.js API Routes]
    end

    subgraph "Python RAG Service (FastAPI)"
        subgraph "API 层 (routers/)"
            ChatRouter[POST /chat - SSE 流式]
            IndexRouter[POST /index - 索引管理]
            ConfigRouter[GET/PUT /config]
            HealthRouter[GET /health]
        end

        subgraph "核心层 (core/)"
            Chain[chain.py - RAG 链]
            Retriever[retriever.py - 向量检索]
            Embeddings[embeddings.py - 嵌入模型]
            LLM[llm.py - 大模型]
            Rewriter[query_rewriter.py - 查询改写]
            Prompt[prompt.py - 提示词模板]
            History[chat_history.py - 会话管理]
        end

        subgraph "基础设施层 (infra/)"
            Indexer[indexer.py - 索引构建]
            Chunker[chunker.py - 文本分块]
            Security[security.py - 安全过滤]
            DB[db.py - MySQL 连接]
        end

        Config[config.py - 配置管理]
        Deps[dependencies.py - 依赖注入]
    end

    subgraph "外部服务"
        Redis[(Redis)]
        Qdrant[(Qdrant)]
        MySQL[(MySQL)]
        LLMAPI[LLM API - 智谱/OpenAI]
    end

    FE --> API
    API -->|HTTP/SSE| ChatRouter
    API -->|HTTP| IndexRouter
    API -->|HTTP| ConfigRouter

    ChatRouter --> Chain
    Chain --> Rewriter
    Chain --> Retriever
    Chain --> Prompt
    Chain --> LLM
    Chain --> History

    IndexRouter --> Indexer
    Indexer --> Chunker
    Indexer --> Embeddings
    Indexer --> DB

    ChatRouter --> Security
    ConfigRouter --> Config

    Retriever --> Qdrant
    Embeddings --> LLMAPI
    LLM --> LLMAPI
    History --> Redis
    Config --> Redis
    Indexer --> Qdrant
    DB --> MySQL
```

### 请求处理流程

```mermaid
sequenceDiagram
    participant Client as 前端
    participant API as FastAPI Router
    participant Security as 安全过滤
    participant History as 会话管理
    participant Rewriter as 查询改写
    participant Retriever as 向量检索
    participant Prompt as 提示词构建
    participant LLM as 大模型

    Client->>API: POST /chat {message, sessionId}
    API->>Security: validate_input(message)
    Security-->>API: FilterResult(passed=true)
    
    API->>History: get_session(sessionId)
    History-->>API: ChatSession(messages)
    
    API->>Rewriter: rewrite(query, history)
    Rewriter->>LLM: 生成改写查询
    LLM-->>Rewriter: rewritten_query
    
    Rewriter->>Retriever: search(rewritten_query)
    Retriever-->>API: List[Document]
    
    API->>Prompt: build_messages(query, docs, history)
    Prompt-->>API: messages
    
    API->>LLM: astream(messages)
    
    loop SSE 流式
        LLM-->>API: token chunk
        API-->>Client: SSE event {type: "token", content}
    end
    
    API-->>Client: SSE event {type: "sources", content}
    API->>History: append_message(sessionId, messages)
```

### 索引构建流程

```mermaid
sequenceDiagram
    participant NextJS as Next.js
    participant API as FastAPI /index
    participant DB as MySQL
    participant Chunker as 文本分块
    participant Embed as Embedding
    participant Qdrant as Qdrant

    NextJS->>API: POST /index {contentId, contentType}
    API->>DB: 查询文章/笔记内容
    DB-->>API: 文章 Markdown 内容
    
    API->>Qdrant: 删除该 contentId 已有向量
    
    API->>Chunker: chunk_content(markdown, meta)
    Chunker-->>API: List[Document] (分块结果)
    
    API->>Embed: embed_documents(chunks)
    Embed-->>API: List[Vector]
    
    API->>Qdrant: upsert(points) - 确定性 Point ID
    Qdrant-->>API: success
    
    API-->>NextJS: {success: true, chunks: N}
```

## Components and Interfaces

### 组件 1：配置管理 (`app/config.py`)

**职责**：
- 管理三级配置优先级：Redis Hash > 环境变量 > 默认值
- 与 TypeScript 版共享 Redis 键 `ai_chat:config`
- 支持动态配置热更新

```python
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """环境变量配置（静态）"""
    
    # Redis
    redis_url: str = "redis://localhost:6379"
    
    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    
    # MySQL
    database_url: str = "mysql+aiomysql://user:pass@localhost:3306/blog"
    
    # LLM 默认值
    llm_provider: str = "openai-compatible"
    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4-flash"
    
    # Embedding 默认值
    embedding_api_key: str = ""
    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    embedding_model: str = "embedding-3"
    embedding_dimensions: int = 2048
    
    # 服务
    port: int = 8000
    
    class Config:
        env_file = ".env"


class AIChatConfig:
    """动态配置模型（对应 Redis Hash 字段）"""
    
    # LLM 配置
    model: str
    api_key: str
    base_url: str
    temperature: float
    max_tokens: int
    
    # Embedding 配置
    embedding_model: str
    embedding_api_key: str
    embedding_base_url: str
    
    # 检索配置
    top_k: int
    score_threshold: float
    
    # 提示词
    system_prompt: str
    
    # 功能开关
    query_rewrite_enabled: bool
    content_filter_enabled: bool


class AIConfigManager:
    """配置管理器 — 三级优先级加载"""
    
    REDIS_KEY = "ai_chat:config"
    
    def __init__(self, redis_client, settings: Settings):
        self._redis = redis_client
        self._settings = settings
    
    async def load(self) -> AIChatConfig:
        """加载配置：Redis Hash > 环境变量 > 默认值"""
        ...
    
    async def update(self, updates: dict) -> AIChatConfig:
        """更新 Redis 配置（camelCase 字段名写入）"""
        ...
    
    async def get_all(self) -> dict:
        """获取当前完整配置（供 GET /config 使用）"""
        ...
```

### 组件 2：依赖注入 (`app/dependencies.py`)

**职责**：
- 管理 Redis、Qdrant 客户端生命周期
- 提供 FastAPI Depends 注入点

```python
from functools import lru_cache
from redis.asyncio import Redis
from qdrant_client import AsyncQdrantClient


async def get_redis() -> Redis:
    """获取 Redis 异步客户端（连接池复用）"""
    ...


async def get_qdrant_client() -> AsyncQdrantClient:
    """获取 Qdrant 异步客户端"""
    ...


async def get_config_manager(
    redis: Redis = Depends(get_redis),
) -> AIConfigManager:
    """获取配置管理器实例"""
    ...


async def get_chat_history(
    redis: Redis = Depends(get_redis),
) -> "RedisChatHistory":
    """获取会话管理器实例"""
    ...
```

### 组件 3：RAG 链 (`app/core/chain.py`)

**职责**：
- 使用 LCEL 编排完整 RAG 流程
- 返回 Runnable 对象，支持 `invoke()` 和 `astream()`
- 未来可直接包装为 LangGraph Tool

```python
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.output_parsers import StrOutputParser


def create_rag_chain(config: AIChatConfig) -> Runnable:
    """
    构建 RAG 链
    
    输入: {"query": str, "history": list[ChatMessage]}
    输出: str (流式文本)
    
    未来 LangGraph 迁移时:
        @tool
        def search_blog(query: str) -> str:
            chain = create_rag_chain(config)
            return chain.invoke({"query": query, "history": []})
    """
    ...


class RAGChainResult:
    """RAG 链执行结果（包含来源信息）"""
    answer: str
    sources: list[SourceInfo]
    rewritten_query: str
```

### 组件 4：向量检索 (`app/core/retriever.py`)

**职责**：
- 封装 QdrantVectorStore 为 LangChain Retriever
- 支持相似度阈值过滤
- 兼容现有 Qdrant 集合结构

```python
from langchain_qdrant import QdrantVectorStore
from langchain_core.documents import Document


def create_retriever(
    embeddings: OpenAIEmbeddings,
    config: AIChatConfig,
    qdrant_url: str,
) -> VectorStoreRetriever:
    """
    创建带阈值过滤的 Retriever
    
    复用现有集合 blog_content_chunks，
    Payload 字段: sourceId, sourceType, title, categoryName, chunkIndex, chunkText
    """
    ...
```

### 组件 5：查询改写 (`app/core/query_rewriter.py`)

**职责**：
- 结合对话历史将用户查询改写为更适合检索的形式
- 安全防护：长度截断、注入检测、失败回退

```python
from langchain_core.runnables import Runnable


def create_query_rewriter(config: AIChatConfig) -> Runnable:
    """
    创建查询改写链
    
    输入: {"query": str, "history": list}
    输出: str (改写后的查询)
    
    安全策略:
    - 输入截断: 500 字符上限
    - 注入检测: 正则匹配危险模式
    - 失败回退: 返回原始查询
    - 短查询跳过: ≤5 字符且无历史时直接返回
    """
    ...
```

### 组件 6：会话管理 (`app/core/chat_history.py`)

**职责**：
- Redis 持久化会话历史
- 与 TypeScript 版共享数据格式
- 管理 TTL 过期

```python
class RedisChatHistory:
    """
    Redis 会话管理 — 与 TS 版完全兼容
    
    Redis 键: chat:session:{sessionId}
    数据格式: JSON (camelCase 字段名)
    过期时间: 7 天
    """
    
    KEY_PREFIX = "chat:session:"
    TTL_SECONDS = 7 * 24 * 3600  # 7 天
    
    async def get_session(self, session_id: str) -> ChatSession | None:
        """获取会话（不存在返回 None）"""
        ...
    
    async def create_session(self, client_ip: str | None = None) -> ChatSession:
        """创建新会话"""
        ...
    
    async def append_message(self, session_id: str, message: ChatMessage) -> None:
        """追加消息到会话"""
        ...
    
    async def get_or_create(self, session_id: str | None) -> ChatSession:
        """获取或创建会话"""
        ...
```

### 组件 7：索引服务 (`app/infra/indexer.py`)

**职责**：
- 管理文章/笔记的向量化索引
- 支持单篇增量、全量重建、删除
- 确定性 Point ID 生成

```python
class ContentIndexer:
    """文章索引管理"""
    
    async def index_content(
        self, content_id: int, content_type: str
    ) -> IndexResult:
        """单篇索引（发布/更新时调用）"""
        ...
    
    async def remove_content_index(self, content_id: int) -> bool:
        """删除单篇索引"""
        ...
    
    async def rebuild_index(self) -> RebuildResult:
        """全量重建索引"""
        ...
    
    @staticmethod
    def generate_point_id(content_id: int, chunk_index: int) -> str:
        """
        确定性 Point ID 生成
        算法: SHA-1("{contentId}_chunk_{chunkIndex}") → UUID 格式
        与 TypeScript 版一致
        """
        ...
```

### 组件 8：文本分块 (`app/infra/chunker.py`)

**职责**：
- Markdown 感知的智能分块
- token 级精确切分
- 语义前缀注入增强检索

```python
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from langchain_core.documents import Document


def chunk_content(
    markdown: str, meta: ContentMeta
) -> list[Document]:
    """
    文本分块流程:
    1. 按 ## 标题分割为段落组
    2. 对每个段落按 512 token 切分（50 token 重叠）
    3. 注入标题/分类前缀
    """
    ...
```

### 组件 9：安全过滤 (`app/infra/security.py`)

**职责**：
- 输入内容安全验证
- Prompt 注入检测
- 敏感内容过滤

```python
from dataclasses import dataclass


@dataclass
class FilterResult:
    passed: bool
    reason: str | None = None


def validate_input(message: str) -> FilterResult:
    """
    输入安全校验:
    - 空内容检测
    - 长度限制（2000 字符）
    - Prompt 注入模式匹配
    - 敏感词过滤
    """
    ...


def sanitize_for_prompt(text: str) -> str:
    """清理文本中的潜在注入内容"""
    ...
```

## Data Models

### 请求/响应模型 (`app/schemas/`)

```python
# app/schemas/chat.py
from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")
    session_id: Optional[str] = Field(None, description="会话 ID（首次可为空）")


class ChatSSEEvent(BaseModel):
    """SSE 事件数据"""
    type: str  # "token" | "sources" | "error" | "done"
    content: str


class SourceInfo(BaseModel):
    """来源信息"""
    title: str
    source_id: int
    source_type: str  # "article" | "note"
    category_name: str


# app/schemas/index.py
class IndexRequest(BaseModel):
    """索引请求"""
    content_id: int
    content_type: str = Field(..., pattern="^(article|note)$")


class IndexResponse(BaseModel):
    """索引响应"""
    success: bool
    chunks: int = 0
    message: str = ""


class RebuildResponse(BaseModel):
    """全量重建响应"""
    success: bool
    total_articles: int = 0
    total_notes: int = 0
    total_chunks: int = 0
    errors: list[str] = []


# app/schemas/config.py
class ConfigResponse(BaseModel):
    """配置响应（camelCase 输出）"""
    model: str
    temperature: float
    max_tokens: int = Field(alias="maxTokens")
    top_k: int = Field(alias="topK")
    score_threshold: float = Field(alias="scoreThreshold")
    system_prompt: str = Field(alias="systemPrompt")
    query_rewrite_enabled: bool = Field(alias="queryRewriteEnabled")
    content_filter_enabled: bool = Field(alias="contentFilterEnabled")
    
    class Config:
        populate_by_name = True


class ConfigUpdateRequest(BaseModel):
    """配置更新请求（接受 camelCase）"""
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, alias="maxTokens", ge=100, le=8192)
    top_k: Optional[int] = Field(None, alias="topK", ge=1, le=20)
    score_threshold: Optional[float] = Field(None, alias="scoreThreshold", ge=0, le=1)
    system_prompt: Optional[str] = Field(None, alias="systemPrompt")
    query_rewrite_enabled: Optional[bool] = Field(None, alias="queryRewriteEnabled")
    content_filter_enabled: Optional[bool] = Field(None, alias="contentFilterEnabled")
```

### 内部数据模型

```python
# 会话相关
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class ChatMessage:
    """聊天消息"""
    role: Literal["user", "assistant"]
    content: str
    timestamp: str  # ISO 8601 格式


@dataclass
class ChatSession:
    """会话数据（对应 Redis JSON 结构）"""
    session_id: str  # UUID v4
    messages: list[ChatMessage] = field(default_factory=list)
    created_at: str = ""  # ISO 8601
    last_active_at: str = ""  # ISO 8601
    client_ip: str | None = None


# 索引相关
@dataclass
class ContentMeta:
    """内容元信息"""
    content_id: int
    content_type: str  # "article" | "note"
    title: str
    category_name: str
    create_time: str


@dataclass
class IndexResult:
    """单篇索引结果"""
    success: bool
    content_id: int
    chunks: int
    message: str = ""


@dataclass
class RebuildResult:
    """全量重建结果"""
    success: bool
    total_articles: int
    total_notes: int
    total_chunks: int
    errors: list[str] = field(default_factory=list)
```

### Qdrant 向量数据结构

```python
# Qdrant Point 结构（与 TypeScript 版完全一致）
qdrant_point = {
    "id": "sha1-uuid-string",  # 确定性 UUID，基于 "{contentId}_chunk_{index}"
    "vector": [0.1, 0.2, ...],  # embedding_dimensions 维向量
    "payload": {
        "sourceId": 123,          # int - 文章/笔记 ID
        "sourceType": "article",  # str - "article" | "note"
        "title": "文章标题",      # str
        "categoryName": "分类",   # str
        "chunkIndex": 0,          # int - 分块序号
        "chunkText": "分块内容",  # str - 实际文本内容
        "createTime": "2024-01-01T00:00:00Z",  # str - ISO 8601
    }
}
```

### 算法伪代码与形式化规约

### 算法 1：RAG 链执行流程

```python
async def execute_rag_chain(query: str, history: list[ChatMessage], config: AIChatConfig):
    """
    RAG 链核心执行逻辑
    
    前置条件:
    - query 非空且长度 ≤ 2000
    - config 已成功加载
    - 所有外部服务可达（Qdrant, Redis, LLM API）
    
    后置条件:
    - 返回流式文本生成器
    - 来源信息在流结束后返回
    - 会话历史已更新
    
    循环不变量:
    - 每个 token chunk 是 LLM 输出的连续片段
    - full_response 始终等于已输出所有 chunk 的拼接
    """
    
    # Step 1: 查询改写（可选）
    if config.query_rewrite_enabled and should_rewrite(query, history):
        rewritten_query = await rewrite_query(query, history, config)
    else:
        rewritten_query = query
    
    # Step 2: 向量检索
    documents = await retrieve_documents(rewritten_query, config)
    
    # Step 3: 构建提示词
    messages = build_prompt_messages(
        query=query,
        documents=documents,
        history=history,
        system_prompt=config.system_prompt,
    )
    
    # Step 4: LLM 流式生成
    llm = create_llm(config)
    full_response = ""
    
    async for chunk in llm.astream(messages):
        full_response += chunk.content
        yield {"type": "token", "content": chunk.content}
    
    # Step 5: 返回来源
    sources = extract_sources(documents)
    yield {"type": "sources", "content": sources}
    
    # Step 6: 返回完成信号
    yield {"type": "done", "content": ""}
```

### 算法 2：查询改写

```python
def should_rewrite(query: str, history: list[ChatMessage]) -> bool:
    """
    判断是否需要改写
    
    前置条件: query 非空
    后置条件: 返回 bool
    
    规则:
    - 短查询（≤5字符）且无历史 → False
    - 查询包含注入模式 → False（安全回退）
    - 其他情况 → True
    """
    if len(query) <= 5 and len(history) == 0:
        return False
    if contains_injection_pattern(query):
        return False
    return True


async def rewrite_query(
    query: str, history: list[ChatMessage], config: AIChatConfig
) -> str:
    """
    查询改写
    
    前置条件:
    - query 长度 ≤ 500（超过则截断）
    - LLM 服务可达
    
    后置条件:
    - 返回改写后的查询字符串
    - 改写失败时返回原始 query（不抛异常）
    
    算法:
    1. 截断输入至 500 字符
    2. 构建改写提示词（包含最近 N 轮历史）
    3. 调用 LLM 获取改写结果
    4. 异常时 fallback 到原始查询
    """
    truncated_query = query[:500]
    
    # 只取最近 3 轮对话作为上下文
    recent_history = history[-6:]  # 3 轮 = 6 条消息
    
    rewrite_prompt = ChatPromptTemplate.from_messages([
        ("system", REWRITE_SYSTEM_PROMPT),
        ("human", "对话历史:\n{history}\n\n当前问题: {query}\n\n改写后的检索查询:"),
    ])
    
    try:
        chain = rewrite_prompt | create_llm(config) | StrOutputParser()
        result = await chain.ainvoke({
            "query": truncated_query,
            "history": format_history(recent_history),
        })
        return result.strip()
    except Exception:
        return truncated_query  # 失败回退
```

### 算法 3：确定性 Point ID 生成

```python
import hashlib
import uuid


def generate_point_id(content_id: int, chunk_index: int) -> str:
    """
    确定性 Point ID 生成 — 与 TypeScript 版一致
    
    前置条件:
    - content_id > 0
    - chunk_index >= 0
    
    后置条件:
    - 返回合法 UUID 格式字符串
    - 相同输入始终返回相同 UUID
    - 不同输入返回不同 UUID（碰撞概率 < 2^-80）
    
    算法:
    1. 拼接种子字符串: "{contentId}_chunk_{chunkIndex}"
    2. 计算 SHA-1 哈希（20 字节）
    3. 取前 16 字节构造 UUID v5 格式
    """
    seed = f"{content_id}_chunk_{chunk_index}"
    sha1_hash = hashlib.sha1(seed.encode()).digest()
    
    # 使用 SHA-1 前 16 字节构造 UUID
    return str(uuid.UUID(bytes=sha1_hash[:16]))
```

### 算法 4：文本分块

```python
def chunk_content(markdown: str, meta: ContentMeta) -> list[Document]:
    """
    Markdown 感知分块算法
    
    前置条件:
    - markdown 非空
    - meta 包含有效的 content_id, title, category_name
    
    后置条件:
    - 返回 Document 列表，每个 Document:
      - page_content: 实际文本（含语义前缀）
      - metadata: 包含 sourceId, sourceType, title, categoryName, chunkIndex
    - 每个块的 token 数 ≤ 512
    - 相邻块有 50 token 重叠
    
    循环不变量:
    - chunk_index 单调递增
    - 所有已生成的 Document 的 chunkIndex 唯一
    
    算法:
    1. 按 Markdown ## 标题分割为段落组
    2. 对每个段落组按 512 token 切分
    3. 为每个块添加语义前缀: "[{title}] [{section}] "
    4. 构造 Document 对象并附加 metadata
    """
    # Step 1: Markdown 标题分割
    headers_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("##", "section")]
    )
    header_splits = headers_splitter.split_text(markdown)
    
    # Step 2: Token 级别分割
    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=512,
        chunk_overlap=50,
        encoding_name="cl100k_base",
    )
    
    documents = []
    chunk_index = 0
    
    for split in header_splits:
        section = split.metadata.get("section", "")
        sub_chunks = text_splitter.split_text(split.page_content)
        
        for sub_chunk in sub_chunks:
            # 语义前缀注入
            prefix = f"[{meta.title}]"
            if section:
                prefix += f" [{section}]"
            enriched_text = f"{prefix} {sub_chunk}"
            
            doc = Document(
                page_content=enriched_text,
                metadata={
                    "sourceId": meta.content_id,
                    "sourceType": meta.content_type,
                    "title": meta.title,
                    "categoryName": meta.category_name,
                    "chunkIndex": chunk_index,
                    "chunkText": sub_chunk,  # 存储原始文本
                    "createTime": meta.create_time,
                },
            )
            documents.append(doc)
            chunk_index += 1
    
    return documents
```

### 算法 5：配置加载（三级优先级）

```python
async def load_config(redis_client, settings: Settings) -> AIChatConfig:
    """
    三级配置优先级加载
    
    前置条件:
    - Redis 连接可用
    - settings 已从环境变量加载
    
    后置条件:
    - 返回完整的 AIChatConfig
    - Redis 值 > 环境变量 > 默认值
    - 数值类型正确转换（Redis 存储为字符串）
    
    算法:
    1. 设置默认值字典
    2. 用环境变量覆盖
    3. 读取 Redis Hash，逐字段覆盖
    4. 类型转换（str→float, str→int, str→bool）
    5. 构造 AIChatConfig 对象
    """
    # 默认值
    defaults = {
        "model": "glm-4-flash",
        "temperature": 0.7,
        "maxTokens": 2048,
        "topK": 5,
        "scoreThreshold": 0.5,
        "systemPrompt": DEFAULT_SYSTEM_PROMPT,
        "queryRewriteEnabled": True,
        "contentFilterEnabled": True,
    }
    
    # 环境变量覆盖
    env_overrides = {
        "model": settings.llm_model,
        "apiKey": settings.llm_api_key,
        "baseUrl": settings.llm_base_url,
    }
    config_dict = {**defaults, **{k: v for k, v in env_overrides.items() if v}}
    
    # Redis Hash 覆盖
    redis_hash = await redis_client.hgetall("ai_chat:config")
    for key, value in redis_hash.items():
        key_str = key.decode() if isinstance(key, bytes) else key
        val_str = value.decode() if isinstance(value, bytes) else value
        config_dict[key_str] = parse_redis_value(key_str, val_str)
    
    return AIChatConfig(**config_dict)


def parse_redis_value(key: str, value: str):
    """
    Redis 值类型转换（与 TS 版 parseRedisHash 兼容）
    
    规则:
    - temperature, scoreThreshold → float
    - maxTokens, topK → int
    - queryRewriteEnabled, contentFilterEnabled → bool ("true"/"false")
    - 其他 → str
    """
    float_fields = {"temperature", "scoreThreshold"}
    int_fields = {"maxTokens", "topK", "embeddingDimensions"}
    bool_fields = {"queryRewriteEnabled", "contentFilterEnabled"}
    
    if key in float_fields:
        return float(value)
    elif key in int_fields:
        return int(value)
    elif key in bool_fields:
        return value.lower() == "true"
    return value
```

### 关键函数形式化规约

### `create_rag_chain(config) -> Runnable`

```python
def create_rag_chain(config: AIChatConfig) -> Runnable:
    """
    前置条件:
    - config.model 非空
    - config.base_url 是合法 URL
    - Qdrant 服务可达
    
    后置条件:
    - 返回 Runnable 对象
    - 该 Runnable 接受 {"query": str, "history": list} 输入
    - 该 Runnable 支持 .invoke() 和 .astream()
    - 输出为纯文本字符串
    """
    llm = create_llm(config)
    embeddings = create_embeddings(config)
    retriever = create_retriever(embeddings, config, settings.qdrant_url)
    rewrite_chain = create_query_rewriter(config)
    
    # LCEL 编排
    chain = (
        RunnablePassthrough.assign(
            rewritten_query=lambda x: rewrite_chain.invoke({
                "query": x["query"],
                "history": x["history"],
            }) if config.query_rewrite_enabled else x["query"]
        )
        | RunnablePassthrough.assign(
            documents=lambda x: retriever.invoke(x["rewritten_query"])
        )
        | RunnablePassthrough.assign(
            messages=lambda x: build_messages(
                query=x["query"],
                documents=x["documents"],
                history=x["history"],
                system_prompt=config.system_prompt,
            )
        )
        | llm
        | StrOutputParser()
    )
    
    return chain
```

### `create_llm(config) -> BaseChatModel`

```python
from langchain_openai import ChatOpenAI


def create_llm(config: AIChatConfig) -> ChatOpenAI:
    """
    前置条件:
    - config.model 非空
    - config.base_url 是合法的 OpenAI-compatible API URL
    - config.api_key 非空（或目标是本地 Ollama）
    
    后置条件:
    - 返回 ChatOpenAI 实例
    - streaming=True 已启用
    - temperature 在 [0, 2] 范围内
    """
    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        streaming=True,
    )
```

### `create_embeddings(config) -> OpenAIEmbeddings`

```python
from langchain_openai import OpenAIEmbeddings


def create_embeddings(config: AIChatConfig) -> OpenAIEmbeddings:
    """
    前置条件:
    - config.embedding_model 非空
    - config.embedding_base_url 是合法 URL
    
    后置条件:
    - 返回 OpenAIEmbeddings 实例
    - 向量维度 = config.embedding_dimensions
    """
    return OpenAIEmbeddings(
        model=config.embedding_model,
        openai_api_key=config.embedding_api_key or "ollama",
        openai_api_base=config.embedding_base_url,
        dimensions=config.embedding_dimensions,
    )
```

### 示例用法

### 完整聊天流程

```python
# app/routers/chat.py
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
import json

router = APIRouter()


@router.post("/chat")
async def chat(
    request: ChatRequest,
    config_manager: AIConfigManager = Depends(get_config_manager),
    chat_history: RedisChatHistory = Depends(get_chat_history),
):
    # 1. 加载配置
    config = await config_manager.load()
    
    # 2. 安全过滤
    if config.content_filter_enabled:
        filter_result = validate_input(request.message)
        if not filter_result.passed:
            raise HTTPException(status_code=400, detail=filter_result.reason)
    
    # 3. 获取/创建会话
    session = await chat_history.get_or_create(request.session_id)
    
    # 4. 构建 RAG 链
    chain = create_rag_chain(config)
    
    # 5. SSE 流式响应
    async def event_generator():
        full_response = ""
        documents = []
        
        async for chunk in chain.astream({
            "query": request.message,
            "history": session.messages,
        }):
            full_response += chunk
            yield {"data": json.dumps({"type": "token", "content": chunk})}
        
        # 来源信息
        sources = extract_sources(documents)
        yield {"data": json.dumps({"type": "sources", "content": sources})}
        
        # 完成信号
        yield {"data": json.dumps({"type": "done", "content": ""})}
        
        # 保存会话
        await chat_history.append_message(
            session.session_id,
            ChatMessage(role="user", content=request.message, timestamp=now_iso())
        )
        await chat_history.append_message(
            session.session_id,
            ChatMessage(role="assistant", content=full_response, timestamp=now_iso())
        )
    
    return EventSourceResponse(event_generator())
```

### 索引单篇文章

```python
# app/routers/index.py
@router.post("/index")
async def index_content(
    request: IndexRequest,
    indexer: ContentIndexer = Depends(get_indexer),
):
    result = await indexer.index_content(
        content_id=request.content_id,
        content_type=request.content_type,
    )
    
    if not result.success:
        raise HTTPException(status_code=500, detail=result.message)
    
    return IndexResponse(
        success=True,
        chunks=result.chunks,
        message=f"已索引 {result.chunks} 个文本块",
    )
```

### FastAPI 应用入口

```python
# app/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.routers import chat, index, config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动：初始化连接池
    app.state.redis = await create_redis_pool()
    app.state.qdrant = await create_qdrant_client()
    
    yield
    
    # 关闭：清理资源
    await app.state.redis.close()


app = FastAPI(
    title="RAG Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(chat.router, tags=["chat"])
app.include_router(index.router, prefix="/index", tags=["index"])
app.include_router(config.router, prefix="/config", tags=["config"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "rag-service"}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: 确定性 Point ID

*For any* valid content_id (> 0) and chunk_index (>= 0), calling `generate_point_id(content_id, chunk_index)` twice with the same arguments SHALL always produce the same valid UUID string.

**Validates: Requirements 12.5, 12.6**

### Property 2: 配置三级优先级

*For any* configuration field, the loaded value SHALL equal the Redis Hash value if present; otherwise the environment variable value if set; otherwise the hardcoded default value.

**Validates: Requirements 2.2, 2.3, 2.4**

### Property 3: Redis 值类型解析

*For any* valid Redis Hash string representation of a configuration value, `parse_redis_value` SHALL correctly convert it to the expected target type (float for temperature/scoreThreshold, int for maxTokens/topK, bool for queryRewriteEnabled/contentFilterEnabled).

**Validates: Requirement 2.5**

### Property 4: 分块 token 上限

*For any* non-empty Markdown 文本 and valid ContentMeta, every chunk produced by `chunk_content()` SHALL have token count ≤ 512.

**Validates: Requirement 11.2**

### Property 5: 分块索引单调递增

*For any* non-empty Markdown 文本 and valid ContentMeta, the chunkIndex values in the output of `chunk_content()` SHALL form a sequence 0, 1, 2, ..., N-1 (consecutive, starting from 0, no gaps or duplicates).

**Validates: Requirement 11.6**

### Property 6: 分块语义前缀

*For any* non-empty Markdown 文本 and valid ContentMeta, every Document produced by `chunk_content()` SHALL have page_content starting with `[{title}]`.

**Validates: Requirements 11.4, 11.5**

### Property 7: 安全过滤幂等性

*For any* string input, calling `validate_input(message)` multiple times SHALL always return the same FilterResult.passed value.

**Validates: Requirement 3.5**

### Property 8: 长度超限必定拒绝

*For any* string with length > 2000 characters, `validate_input(message)` SHALL return FilterResult(passed=False).

**Validates: Requirement 3.2**

### Property 9: 查询改写安全回退

*For any* query where `len(query) <= 5` and history is empty, the Query_Rewriter SHALL return the original query unchanged. Additionally, *for any* query containing a Prompt injection pattern, the Query_Rewriter SHALL return the original query unchanged.

**Validates: Requirements 6.1, 6.2**

### Property 10: 查询改写失败回退

*For any* query and history, if the LLM call raises an exception during rewriting, the Query_Rewriter SHALL return the original query (truncated to 500 chars if longer) rather than propagating the exception.

**Validates: Requirement 6.4**

### Property 11: 会话追加一致性

*For any* valid session_id and ChatMessage, after calling `append_message(session_id, msg)`, calling `get_session(session_id)` SHALL return a session whose last message equals msg.

**Validates: Requirement 10.4**

### Property 12: 会话 JSON camelCase 序列化

*For any* ChatSession written to Redis, all JSON field names in the serialized data SHALL be in camelCase format (e.g., sessionId, lastActiveAt, not session_id, last_active_at).

**Validates: Requirements 10.2, 18.5**

### Property 13: Redis 数据双向兼容（round-trip）

*For any* configuration or session data, writing from Python and reading from TypeScript format (and vice versa) SHALL produce equivalent data — the serialization format is interoperable.

**Validates: Requirements 18.6, 18.7**

### Property 14: 提示词组装完整性

*For any* combination of query (non-empty string), documents (list of Documents), history (list of ChatMessages), and system_prompt (non-empty string), the output of `build_messages()` SHALL contain the system prompt, the document context, and the user query.

**Validates: Requirements 9.1, 9.2**

## Error Handling

### 场景 1：LLM API 不可达

**条件**：LLM API 请求超时或返回错误
**响应**：返回友好错误 SSE 事件 `{"type": "error", "content": "AI 服务暂时不可用"}`
**恢复**：使用指数退避重试（最多 3 次）

### 场景 2：Qdrant 检索失败

**条件**：Qdrant 连接失败或查询错误
**响应**：跳过检索步骤，直接用 LLM 回答（降级模式）
**恢复**：记录错误日志，下次请求重新尝试连接

### 场景 3：Redis 会话读写失败

**条件**：Redis 连接中断
**响应**：创建临时内存会话，当前请求正常处理
**恢复**：Redis 恢复后自动重连（redis-py 内置重连机制）

### 场景 4：索引 Embedding 失败

**条件**：Embedding API 调用失败（批量处理中）
**响应**：记录失败的块，继续处理其他块
**恢复**：指数退避重试失败的批次（最多 5 次）

### 场景 5：查询改写失败

**条件**：改写 LLM 调用异常
**响应**：静默回退到原始查询，不影响主流程
**恢复**：自动恢复，无需人工干预

### 场景 6：MySQL 数据库连接失败

**条件**：索引时无法读取文章内容
**响应**：返回 500 错误，说明数据源不可用
**恢复**：SQLAlchemy 连接池自动重连

## Testing Strategy

### 单元测试

重点测试纯逻辑组件：
- `generate_point_id()` — 确定性验证
- `chunk_content()` — 分块正确性
- `validate_input()` — 安全规则覆盖
- `parse_redis_value()` — 类型转换正确性
- `should_rewrite()` — 改写判断逻辑
- `load_config()` — 三级优先级验证

### 属性测试 (Property-Based Testing)

**测试库**：hypothesis

```python
from hypothesis import given, strategies as st

@given(content_id=st.integers(min_value=1), chunk_index=st.integers(min_value=0))
def test_point_id_deterministic(content_id, chunk_index):
    """同一输入始终生成相同 Point ID"""
    id1 = generate_point_id(content_id, chunk_index)
    id2 = generate_point_id(content_id, chunk_index)
    assert id1 == id2
    assert is_valid_uuid(id1)

@given(message=st.text(min_size=1, max_size=2000))
def test_validate_input_idempotent(message):
    """安全过滤对同一输入结果一致"""
    r1 = validate_input(message)
    r2 = validate_input(message)
    assert r1.passed == r2.passed
```

### 集成测试

- Redis 读写兼容性测试（Python 写 → Python 读，Python 读 ← TS 写）
- Qdrant 查询端到端测试
- 完整 RAG 链 invoke 测试
- SSE 流式响应解析测试

### 性能考虑

1. **连接池复用**：Redis、Qdrant、MySQL 均使用连接池，避免每次请求创建连接
2. **Embedding 批量处理**：索引时批量调用 Embedding API（每批 20 条），减少网络往返
3. **流式响应**：使用 SSE 逐 token 返回，降低首字节延迟（TTFB）
4. **异步 I/O**：全链路 async/await，FastAPI + asyncio 充分利用并发
5. **配置缓存**：动态配置可加入短期缓存（如 30 秒 TTL），避免每次请求读 Redis

### 安全考虑

1. **Prompt 注入防护**：正则检测 + 输入清理，阻止恶意指令注入
2. **输入长度限制**：聊天消息 2000 字符，查询改写 500 字符
3. **API Key 管理**：所有密钥通过环境变量/Redis 管理，不硬编码
4. **CORS 配置**：仅允许 Next.js 前端域名访问
5. **Rate Limiting**：建议在 Nginx/API Gateway 层实现限流
6. **内容过滤**：敏感词 + 注入模式双重检测

## Dependencies

### Python 包

| 包名 | 版本要求 | 用途 |
|------|---------|------|
| fastapi | >=0.115 | Web 框架 |
| uvicorn[standard] | >=0.30 | ASGI 服务器 |
| langchain-core | >=0.3 | LangChain 核心 |
| langchain-openai | >=0.3 | OpenAI 集成 |
| langchain-qdrant | >=0.2 | Qdrant 向量存储 |
| langchain-community | >=0.3 | 社区集成 |
| sse-starlette | >=2.0 | SSE 流式响应 |
| redis[hiredis] | >=5.0 | Redis 客户端 |
| sqlalchemy[asyncio] | >=2.0 | 数据库 ORM |
| aiomysql | >=0.2 | MySQL 异步驱动 |
| pydantic-settings | >=2.0 | 配置管理 |
| tiktoken | >=0.7 | Token 计数 |
| hypothesis | >=6.0 | 属性测试（dev） |
| pytest | >=8.0 | 测试框架（dev） |
| pytest-asyncio | >=0.23 | 异步测试（dev） |

### 外部服务

| 服务 | 用途 | 备注 |
|------|------|------|
| Redis | 配置 + 会话存储 | 与 TS 服务共享 |
| Qdrant | 向量存储 | 与 TS 服务共享集合 |
| MySQL | 文章/笔记内容源 | 只读访问 |
| 智谱 AI / OpenAI | LLM + Embedding | OpenAI-compatible API |
