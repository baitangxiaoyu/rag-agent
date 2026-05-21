# RAG 服务迁移规划：TypeScript → Python + LangChain

## 1. 背景

将现有 Next.js 项目中的 RAG 模块（`src/lib/rag/`）迁移为独立的 Python 服务，使用 LangChain 框架实现，同时为未来 LangGraph Agent 架构预留扩展空间。

### 现有模块映射

| 现有模块 (TypeScript) | Python 对应 | LangChain 组件 |
|---|---|---|
| `config.ts` | `app/config.py` | — |
| `embedding.ts` | `app/core/embeddings.py` | `OpenAIEmbeddings` |
| `vectorStore.ts` | `app/core/retriever.py` | `QdrantVectorStore` |
| `queryRewriter.ts` | `app/core/query_rewriter.py` | 自定义 LCEL Chain |
| `promptBuilder.ts` | `app/core/prompt.py` | `ChatPromptTemplate` |
| `llmClient.ts` | `app/core/llm.py` | `ChatOpenAI` |
| `pipeline.ts` | `app/core/chain.py` | LCEL RunnableSequence |
| `session.ts` | `app/core/chat_history.py` | Redis 会话管理 |
| `chunker.ts` | `app/infra/chunker.py` | `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter` |
| `indexer.ts` | `app/infra/indexer.py` | — |
| `contentFilter.ts` | `app/infra/security.py` | — |

---

## 2. 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Next.js 博客应用                                  │
│                                                                         │
│  /api/chat/route.ts ──── HTTP(SSE) ────►  Python RAG Service            │
│  /api/chat/index/route.ts ── HTTP ────►   (独立进程)                     │
│  /api/chat/config/route.ts ─ HTTP ────►                                 │
└─────────────────────────────────────────────────────────────────────────┘
                                                │
                                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Python RAG Service (FastAPI)                          │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                       API 层 (routers/)                          │   │
│  │  POST /chat          ← 聊天（SSE 流式）                         │   │
│  │  POST /index         ← 单篇索引                                 │   │
│  │  POST /index/rebuild ← 全量重建                                  │   │
│  │  DELETE /index/{id}  ← 删除索引                                  │   │
│  │  GET  /config        ← 读取配置                                  │   │
│  │  PUT  /config        ← 更新配置                                  │   │
│  │  GET  /health        ← 健康检查                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │                                        │
│  ┌─────────────────────────────┴───────────────────────────────────┐   │
│  │                      核心层 (core/)                               │   │
│  │                                                                   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────┐   │   │
│  │  │ chain.py │  │ retriever│  │ embedding │  │ chat_history │   │   │
│  │  │(RAG链)   │  │  .py     │  │   .py     │  │    .py       │   │   │
│  │  └────┬─────┘  └────┬─────┘  └─────┬─────┘  └──────┬───────┘   │   │
│  │       │              │              │               │            │   │
│  │       ▼              ▼              ▼               ▼            │   │
│  │  ┌──────────────────────────────────────────────────────────┐   │   │
│  │  │              LangChain 抽象层                              │   │   │
│  │  │  ChatOpenAI / OpenAIEmbeddings / QdrantVectorStore       │   │   │
│  │  │  RunnablePassthrough / StrOutputParser                    │   │   │
│  │  └──────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │                                        │
│  ┌─────────────────────────────┴───────────────────────────────────┐   │
│  │                      基础设施层 (infra/)                          │   │
│  │  config.py (Redis配置) │ indexer.py │ security.py │ db.py       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└──────────────────────┬──────────────────┬───────────────┬───────────────┘
                       │                  │               │
                       ▼                  ▼               ▼
                    Qdrant            Redis           LLM API
                  (向量存储)        (配置+会话)     (智谱/OpenAI/Ollama)
```

---

## 3. LangGraph 扩展预留设计

```
                    现阶段 (LangChain LCEL)
                    ========================

     query ──► query_rewrite ──► retriever ──► prompt ──► llm ──► output
                    │                                        │
                    └── 用 LCEL (RunnableSequence) 串联 ─────┘


                    未来 (LangGraph Agent)
                    ========================

                         ┌─────────────┐
                         │  Agent Node │ ← LLM 决策调用哪个 Tool
                         └──────┬──────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                  ▼
        ┌───────────┐   ┌───────────┐   ┌──────────────┐
        │ RAG Tool  │   │ DB Tool   │   │ Web Search   │
        │(现有链路) │   │(分类筛选) │   │   Tool       │
        └───────────┘   └───────────┘   └──────────────┘

     关键：现阶段的 RAG 链路封装为一个独立函数/Runnable，
     未来直接作为 LangGraph 的一个 Tool 节点挂载，零重写。
```

**3 个关键扩展接缝：**

1. **`create_rag_chain()` 返回 Runnable** — 未来直接用 `@tool` 包装成 Agent Tool
2. **`core/` 和 `infra/` 分离** — Agent 的新 Tool（如 DB 查询、分类筛选）放 `core/` 下新文件即可
3. **API 层不感知内部实现** — 未来切换到 Agent 模式，只改 `routers/chat.py` 里的调用方式，接口协议不变

---

## 4. 项目目录结构

```
rag-service/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # Pydantic Settings（环境变量 + Redis 动态配置）
│   ├── dependencies.py         # FastAPI 依赖注入（Redis、Qdrant 客户端）
│   │
│   ├── routers/                # API 路由层
│   │   ├── __init__.py
│   │   ├── chat.py             # POST /chat (SSE 流式)
│   │   ├── index.py            # 索引管理 CRUD
│   │   └── config.py           # 配置读写
│   │
│   ├── core/                   # 核心业务逻辑（LangChain 集成）
│   │   ├── __init__.py
│   │   ├── chain.py            # RAG 链（LCEL 编排）← 未来变成 Tool
│   │   ├── retriever.py        # 自定义 Retriever（封装 Qdrant + 阈值过滤）
│   │   ├── embeddings.py       # Embedding 工厂（OpenAI-compatible / Ollama）
│   │   ├── llm.py              # LLM 工厂
│   │   ├── query_rewriter.py   # 查询改写链
│   │   ├── prompt.py           # PromptTemplate 定义
│   │   └── chat_history.py     # Redis 会话管理
│   │
│   ├── infra/                  # 基础设施
│   │   ├── __init__.py
│   │   ├── indexer.py          # 全量/增量索引
│   │   ├── chunker.py          # 文本分块（Markdown 感知）
│   │   ├── security.py         # 输入过滤 + Prompt 注入检测
│   │   └── db.py               # MySQL 连接（读取文章/笔记内容）
│   │
│   └── schemas/                # Pydantic 请求/响应模型
│       ├── __init__.py
│       ├── chat.py
│       ├── index.py
│       └── config.py
│
├── tests/                      # 测试
├── Dockerfile
├── pyproject.toml              # 依赖管理 (uv)
├── .env.example
└── README.md
```

---

## 5. 核心依赖

```toml
[project]
name = "rag-service"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "langchain-core>=0.3",
    "langchain-openai>=0.3",
    "langchain-qdrant>=0.2",
    "langchain-community>=0.3",
    "sse-starlette>=2.0",
    "redis[hiredis]>=5.0",
    "sqlalchemy[asyncio]>=2.0",
    "aiomysql>=0.2",
    "pydantic-settings>=2.0",
    "tiktoken>=0.7",
]
```

---

## 6. 分步实施计划

### 第一步：项目脚手架搭建（0.5 天）

**目标：** 初始化 Python 项目结构、依赖管理、Docker 配置

**做什么：**
- 初始化 `pyproject.toml`，安装所有依赖
- 创建 FastAPI 入口 `app/main.py`
- 编写 `Dockerfile` 和 `docker-compose.yml` 追加配置
- 实现 `GET /health` 健康检查接口

**验证标准：** `uvicorn` 能启动，`/health` 返回 200

---

### 第二步：配置与基础设施层（0.5 天）

**目标：** 实现配置加载（和现有 Redis Hash 完全兼容）+ 安全过滤

**对应现有模块：** `config.ts` → `app/config.py`，`contentFilter.ts` → `app/infra/security.py`

**关键设计：**

```python
# app/config.py — 三级配置优先级完全复用现有 Redis Hash 键
class AIConfigManager:
    """优先级：Redis Hash > 环境变量 > 默认值（和 TS 版完全一致）"""
    
    REDIS_KEY = "ai_chat:config"  # 和现有 TS 版共享同一个 key
    
    async def load(self) -> AIChatConfig:
        # 1. 默认值
        # 2. 环境变量覆盖
        # 3. Redis Hash 覆盖
        ...
```

**兼容要点：**
- Redis Hash 键名 `ai_chat:config` 与 TS 版共享
- 字段名保持一致（camelCase 存储格式）
- 解析逻辑兼容 TS 版 `parseRedisHash()` 写入的格式

**验证标准：** Python 能正确读取 TS 版通过管理后台写入的 Redis 配置

---

### 第三步：Embedding + VectorStore 层（1 天）

**目标：** 接入 LangChain 的 Embeddings 和 QdrantVectorStore

**对应现有模块：** `embedding.ts` → `app/core/embeddings.py`，`vectorStore.ts` → `app/core/retriever.py`

**关键设计：**

```python
# app/core/embeddings.py
from langchain_openai import OpenAIEmbeddings

def create_embeddings(config: AIChatConfig) -> OpenAIEmbeddings:
    """工厂函数：根据配置创建 Embeddings 实例"""
    return OpenAIEmbeddings(
        model=config.embedding_model,
        openai_api_key=config.embedding_api_key or "ollama",
        openai_api_base=config.embedding_base_url,
    )

# app/core/retriever.py
from langchain_qdrant import QdrantVectorStore

def create_retriever(embeddings, config: AIChatConfig):
    """创建带阈值过滤的 Retriever"""
    vector_store = QdrantVectorStore.from_existing_collection(
        embedding=embeddings,
        collection_name="blog_content_chunks",
        url=settings.QDRANT_URL,
    )
    return vector_store.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={
            "k": config.top_k,
            "score_threshold": config.score_threshold,
        },
    )
```

**兼容要点：**
- 集合名 `blog_content_chunks` 与 TS 版一致
- Payload 字段名完全兼容：`sourceId`、`sourceType`、`title`、`categoryName`、`chunkIndex`、`chunkText`、`createTime`
- 距离算法 Cosine 一致
- Python 服务可直接读取 TS 服务已建好的索引

**验证标准：** 能查询现有 Qdrant 集合并返回正确结果

---

### 第四步：查询改写 + RAG 链（1 天）

**目标：** 用 LCEL 编排完整 RAG 流程

**对应现有模块：** `queryRewriter.ts` → `app/core/query_rewriter.py`，`pipeline.ts` + `promptBuilder.ts` → `app/core/chain.py`

**关键设计：**

```python
# app/core/chain.py
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

def create_rag_chain(config: AIChatConfig):
    """
    构建 RAG 链（LCEL）
    
    设计原则：整条链是一个 Runnable，输入 query + history，输出流式文本。
    未来迁移到 LangGraph 时，这个函数直接作为 Tool 的实现体，零修改。
    """
    llm = create_llm(config)
    embeddings = create_embeddings(config)
    retriever = create_retriever(embeddings, config)
    rewrite_chain = create_query_rewriter(config)
    
    chain = (
        RunnablePassthrough.assign(
            rewritten_query=lambda x: rewrite_chain.invoke({
                "query": x["query"],
                "history": x["history"],
            })
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

**查询改写安全策略（移植自 `queryRewriter.ts`）：**
- 输入长度截断（500 字符）
- Prompt 注入模式检测（正则匹配）
- 改写失败自动回退原始查询
- 短查询（≤5 字符）且无历史时跳过改写

**验证标准：** 端到端问答流程跑通（非流式）

---

### 第五步：会话管理（0.5 天）

**目标：** 基于 Redis 的会话存储（和现有 TS 版共享数据）

**对应现有模块：** `session.ts` → `app/core/chat_history.py`

```python
# app/core/chat_history.py
class RedisChatHistory:
    """
    和 TS 版共享 Redis 键格式：chat:session:{sessionId}
    数据结构完全兼容，支持双端读写
    """
    KEY_PREFIX = "chat:session:"
    
    async def get_session(self, session_id: str) -> ChatSession | None: ...
    async def append_message(self, session_id: str, message: ChatMessage): ...
    async def create_session(self, client_ip: str | None = None) -> ChatSession: ...
```

**兼容要点：**
- Redis 键前缀 `chat:session:` 与 TS 版一致
- JSON 序列化格式兼容（字段名 camelCase）
- TTL 策略一致（默认 7 天）
- `sessionId` 使用 UUID v4

**验证标准：** 多轮对话上下文正确，TS 端创建的会话 Python 端能正确读取

---

### 第六步：索引服务（1 天）

**目标：** 实现文章/笔记的分块、向量化、写入 Qdrant

**对应现有模块：** `chunker.ts` + `indexer.ts` → `app/infra/chunker.py` + `app/infra/indexer.py`

**分块策略：**

```python
# app/infra/chunker.py
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

def chunk_content(markdown: str, meta: ContentMeta) -> list[Document]:
    """
    分块流程：
    1. 按 ## 标题分割为段落组
    2. 对每个段落按 512 token 上限切分（含 50 token 重叠）
    3. 注入标题/分类前缀，增强语义检索命中率
    """
    headers_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("##", "section")]
    )
    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=512,
        chunk_overlap=50,
    )
    # ... 组装 Document 并附加 metadata
```

**索引功能：**
- `index_content(content_id, content_type)` — 单篇索引（发布/更新时调用）
- `remove_content_index(content_id)` — 删除单篇索引
- `rebuild_index()` — 全量重建（先删集合再重建）
- 确定性 Point ID 生成（SHA-1 哈希，和 TS 版算法一致）
- 批量 Embedding + 指数退避重试

**触发方式：** Next.js 文章发布/更新时，调用 Python 服务的 `POST /index` 接口

**验证标准：** 全量重建 + 增量索引正常工作

---

### 第七步：SSE 流式 + API 完善（0.5 天）

**目标：** FastAPI 路由 + SSE 流式输出

```python
# app/routers/chat.py
from sse_starlette.sse import EventSourceResponse

@router.post("/chat")
async def chat(request: ChatRequest):
    """聊天接口 — SSE 流式返回"""
    
    # 1. 输入校验 + 安全过滤
    filter_result = validate_input(request.message)
    if not filter_result.passed:
        raise HTTPException(400, filter_result.reason)
    
    # 2. 获取/创建会话
    session = await chat_history.get_or_create(request.session_id)
    
    # 3. 执行 RAG 链（流式）
    chain = create_rag_chain(config)
    
    async def event_generator():
        full_response = ""
        async for chunk in chain.astream({
            "query": request.message,
            "history": session.messages,
        }):
            full_response += chunk
            yield {"data": json.dumps({"type": "token", "content": chunk})}
        
        # 流结束后返回来源信息
        sources = extract_sources(documents)
        yield {"data": json.dumps({"type": "sources", "content": sources})}
        
        # 保存消息到会话
        await chat_history.append_message(session_id, user_msg)
        await chat_history.append_message(session_id, assistant_msg)
    
    return EventSourceResponse(event_generator())
```

**验证标准：** 前端能收到流式响应，来源信息正确返回

---

### 第八步：Docker + 与 Next.js 对接（0.5 天）

**目标：** 容器化部署 + Next.js 端改为 HTTP 代理

**Docker 配置：**

```yaml
# docker-compose.yml 追加
services:
  rag-service:
    build: ./rag-service
    ports:
      - "8100:8000"
    environment:
      - REDIS_URL=${REDIS_URL}
      - QDRANT_URL=${QDRANT_URL}
      - DATABASE_URL=${DATABASE_URL}
    depends_on:
      - redis
      - qdrant
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Next.js 端改造：**

```typescript
// src/app/api/chat/route.ts
// 原来：直接调用 executeRAG()
// 改后：转发到 Python 服务
const response = await fetch(`${process.env.RAG_SERVICE_URL}/chat`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message, sessionId }),
});
// 透传 SSE 流
return new Response(response.body, {
  headers: { 'Content-Type': 'text/event-stream' },
});
```

**验证标准：** 整体端到端跑通，前端无感知切换

---

## 7. 工期估算

| 阶段 | 内容 | 预计工作量 | 验证标准 |
|------|------|-----------|---------|
| 1 | 项目脚手架 + Docker | 0.5 天 | `uvicorn` 能启动，`/health` 返回 200 |
| 2 | 配置层（Redis 兼容） | 0.5 天 | Python 能正确读取 TS 写入的 Redis 配置 |
| 3 | Embedding + Qdrant 检索 | 1 天 | 能查询现有 Qdrant 集合并返回结果 |
| 4 | 查询改写 + RAG 链 | 1 天 | 端到端问答流程跑通（非流式） |
| 5 | 会话管理 | 0.5 天 | 多轮对话上下文正确 |
| 6 | 索引服务 | 1 天 | 全量重建 + 增量索引正常工作 |
| 7 | SSE 流式 + API 完善 | 0.5 天 | 前端能收到流式响应 |
| 8 | Docker + Next.js 对接 | 0.5 天 | 整体端到端跑通 |

**总计：约 5-6 天**

---

## 8. 兼容性清单

确保 Python 服务与现有 TypeScript 实现无缝共存：

| 共享资源 | 键名/格式 | 说明 |
|---|---|---|
| Redis 配置 | `ai_chat:config` (Hash) | 字段名 camelCase，值为字符串 |
| Redis 会话 | `chat:session:{uuid}` (String) | JSON 序列化，字段 camelCase |
| Redis 索引状态 | `ai_chat:index_status` (Hash) | 字段：articleCount、noteCount 等 |
| Qdrant 集合 | `blog_content_chunks` | Cosine 距离，Payload 字段名不变 |
| Qdrant Point ID | SHA-1 确定性 UUID | 基于 `{contentId}_chunk_{index}` 生成 |

---

## 9. 未来 LangGraph 迁移路径

当你熟悉 LangGraph 后，按以下步骤渐进式升级：

### Phase 1：单 Tool Agent（行为等价）

```python
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

@tool
def search_blog(query: str) -> str:
    """从博客知识库检索并回答问题"""
    chain = create_rag_chain(config)
    return chain.invoke({"query": query, "history": []})

agent = create_react_agent(llm, tools=[search_blog])
```

此阶段行为与纯 LCEL 一致，验证 Agent 框架工作正常。

### Phase 2：多 Tool Agent（能力扩展）

```python
@tool
def filter_by_tag(tag: str) -> str:
    """按标签筛选文章列表"""
    ...

@tool
def get_article_summary(article_id: str) -> str:
    """获取指定文章摘要"""
    ...

@tool
def web_search(query: str) -> str:
    """联网搜索补充知识"""
    ...

agent = create_react_agent(llm, tools=[search_blog, filter_by_tag, get_article_summary, web_search])
```

### Phase 3：高级能力

- 长期记忆（用户偏好）
- Multi-Agent 协作（写作助手 + 检索助手）
- Human-in-the-loop（人工审核敏感操作）

---

## 10. 环境变量

```env
# rag-service/.env.example

# Redis
REDIS_URL=redis://localhost:6379

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=

# MySQL（索引时读取文章内容）
DATABASE_URL=mysql+aiomysql://user:pass@localhost:3306/blog

# LLM（默认值，可被 Redis 配置覆盖）
LLM_PROVIDER=openai-compatible
LLM_API_KEY=
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-4-flash

# Embedding（默认值，可被 Redis 配置覆盖）
EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4
EMBEDDING_MODEL=embedding-3
EMBEDDING_DIMENSIONS=2048

# 服务端口
PORT=8000
```
