# Implementation Plan: RAG 服务迁移 (TypeScript → Python + LangChain)

## Overview

将现有 Next.js RAG 模块迁移为独立 Python FastAPI 服务。按照依赖顺序，从项目脚手架开始，逐步实现配置管理、安全过滤、嵌入检索、LLM 集成、RAG 链编排、会话管理、索引服务，最终实现完整 API 和 Docker 部署。

服务使用 LangChain LCEL 编排 RAG 流程，返回 Runnable 对象支持同步调用和流式输出，为未来 LangGraph 迁移做预留。

## Tasks

- [x] 1. 项目脚手架搭建
  - [x] 1.1 创建项目目录结构和 pyproject.toml
    - 创建完整目录结构：`app/`、`app/routers/`、`app/core/`、`app/infra/`、`app/schemas/`、`tests/`
    - 每个包目录创建 `__init__.py`
    - 编写 `pyproject.toml`，声明所有依赖（fastapi, uvicorn, langchain-core, langchain-openai, langchain-qdrant, sse-starlette, redis, pydantic-settings, tiktoken, hypothesis 等）
    - 创建 `.env.example` 列出所有环境变量
    - _Requirements: 1.1, 1.2_

  - [x] 1.2 实现 FastAPI 入口和健康检查端点
    - 创建 `app/main.py`：初始化 FastAPI 应用实例
    - 实现 `GET /health` 端点，返回 `{"status": "ok", "service": "rag-service"}`
    - 使用 `@asynccontextmanager` 实现 `lifespan` 生命周期管理
    - _Requirements: 1.1, 1.2_

  - [x] 1.3 编写 Dockerfile 和 docker-compose 配置
    - 创建 `Dockerfile`：基于 `python:3.11-slim`，暴露 8000 端口
    - 创建 `docker-compose.yml`：配置 rag-service、redis、qdrant 服务
    - 配置健康检查：`curl -f http://localhost:8000/health`
    - _Requirements: 16.1, 16.2_

- [x] 2. Checkpoint - 确保项目能启动
  - 运行 `uvicorn app.main:app --reload`，访问 `/health` 确认返回 200
  - 确保所有测试通过，有问题请提问

- [x] 3. 配置管理系统
  - [x] 3.1 实现 Settings 环境变量加载
    - 创建 `app/config.py`
    - 定义 `Settings(BaseSettings)` 类，包含 redis_url、qdrant_url、database_url、llm_provider、llm_api_key、llm_base_url、llm_model、embedding_api_key、embedding_base_url、embedding_model、embedding_dimensions、port 字段
    - 配置 `model_config = SettingsConfigDict(env_file=".env")`
    - _Requirements: 2.2, 2.4_

  - [x] 3.2 实现 AIChatConfig 数据模型
    - 在 `app/config.py` 中定义 `AIChatConfig` dataclass
    - 字段：model、api_key、base_url、temperature(float)、max_tokens(int)、embedding_model、embedding_api_key、embedding_base_url、top_k(int)、score_threshold(float)、system_prompt(str)、query_rewrite_enabled(bool)、content_filter_enabled(bool)
    - _Requirements: 2.1_

  - [x] 3.3 实现 AIConfigManager 三级配置加载
    - 在 `app/config.py` 中实现 `AIConfigManager` 类
    - `REDIS_KEY = "ai_chat:config"`
    - 实现 `async def load() -> AIChatConfig`：默认值 → 环境变量覆盖 → Redis Hash 覆盖
    - 实现 `parse_redis_value(key, value)` 函数：temperature→float, maxTokens→int, queryRewriteEnabled→bool
    - 实现 `async def update(updates: dict) -> AIChatConfig`：写入 Redis Hash（camelCase 键名）
    - 实现 `async def get_all() -> dict`：返回完整配置字典
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 3.4 实现依赖注入模块
    - 创建 `app/dependencies.py`
    - 实现 `get_redis()` → 返回 `redis.asyncio.Redis` 实例（连接池模式）
    - 实现 `get_qdrant_client()` → 返回 `AsyncQdrantClient` 实例
    - 实现 `get_config_manager()` → 返回 `AIConfigManager` 实例
    - 在 `app/main.py` 的 lifespan 中初始化连接池，关闭时释放
    - _Requirements: 1.3, 1.4_

  - [x]* 3.5 编写配置加载属性测试
    - 创建 `tests/test_config.py`
    - 测试三级优先级：模拟 Redis 有值 → 使用 Redis 值；Redis 无值 → 使用环境变量
    - 测试 `parse_redis_value` 类型转换正确性
    - **Property 2: 配置三级优先级**
    - **Property 3: Redis 值类型解析**
    - **Validates: Requirements 2.2, 2.3, 2.4, 2.5**

- [x] 4. 安全过滤模块
  - [x] 4.1 实现 validate_input 输入校验
    - 创建 `app/infra/security.py`
    - 定义 `@dataclass FilterResult: passed: bool, reason: str | None = None`
    - 实现 `validate_input(message: str) -> FilterResult`：
      - 空字符串 → `FilterResult(passed=False, reason="消息不能为空")`
      - 长度 > 2000 → `FilterResult(passed=False, reason="消息长度不能超过2000字符")`
      - 匹配注入模式 → `FilterResult(passed=False, reason="检测到潜在的注入内容")`
      - 通过 → `FilterResult(passed=True)`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 4.2 实现 sanitize_for_prompt 文本清理
    - 在 `app/infra/security.py` 中实现 `sanitize_for_prompt(text: str) -> str`
    - 移除潜在注入标记（如 `<|system|>`、`###instruction###`）但保留正常文本
    - _Requirements: 3.6_

  - [x]* 4.3 编写安全过滤属性测试
    - 创建 `tests/test_security.py`
    - 测试幂等性：相同输入多次调用结果一致
    - 测试长度边界：2001 字符必定拒绝
    - 测试空输入必定拒绝
    - **Property 7: 安全过滤幂等性**
    - **Property 8: 长度超限必定拒绝**
    - **Validates: Requirements 3.2, 3.5**

- [x] 5. Embedding 与向量检索
  - [x] 5.1 实现 Embedding 工厂函数
    - 创建 `app/core/embeddings.py`
    - 实现 `create_embeddings(config: AIChatConfig) -> OpenAIEmbeddings`
    - 使用 `langchain_openai.OpenAIEmbeddings`，传入 model、openai_api_key、openai_api_base、dimensions 参数
    - 确保生成 2048 维向量，与现有 Qdrant 集合兼容
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 5.2 实现 Qdrant 向量检索器
    - 创建 `app/core/retriever.py`
    - 实现 `create_retriever(embeddings, config, qdrant_url) -> VectorStoreRetriever`
    - 使用 `QdrantVectorStore.from_existing_collection()` 连接集合 `blog_content_chunks`
    - 调用 `.as_retriever(search_type="similarity_score_threshold", search_kwargs={"k": config.top_k, "score_threshold": config.score_threshold})`
    - 正确读取 Payload 字段：sourceId、sourceType、title、categoryName、chunkIndex、chunkText
    - 添加异常处理：Qdrant 不可达时返回空列表而非抛出异常
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 6. LLM 客户端与提示词模板
  - [ ] 6.1 实现 LLM 工厂函数
    - 创建 `app/core/llm.py`
    - 实现 `create_llm(config: AIChatConfig) -> ChatOpenAI`
    - 参数：model、api_key、base_url、temperature、max_tokens、streaming=True
    - 兼容 OpenAI-compatible API（智谱 AI、Ollama 等）
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ] 6.2 实现提示词模板构建
    - 创建 `app/core/prompt.py`
    - 定义 `DEFAULT_SYSTEM_PROMPT` 常量
    - 实现 `build_messages(query, documents, history, system_prompt) -> list`
    - 将系统提示词、文档上下文（格式化）、对话历史、用户查询组装为完整消息列表
    - 文档格式化：每个文档显示标题和内容
    - 支持系统提示词通过配置动态更新
    - _Requirements: 9.1, 9.2, 9.3_

  - [ ]* 6.3 编写提示词组装属性测试
    - 创建 `tests/test_prompt.py`
    - 测试组装完整性：输出必须包含系统提示、文档上下文和用户查询
    - **Property 14: 提示词组装完整性**
    - **Validates: Requirements 9.1, 9.2**

- [ ] 7. 查询改写链
  - [ ] 7.1 实现查询改写逻辑
    - 创建 `app/core/query_rewriter.py`
    - 实现 `should_rewrite(query, history) -> bool`：短查询无历史→False，含注入模式→False
    - 实现 `create_query_rewriter(config) -> Runnable`：
      - 输入截断 500 字符
      - 构建改写 prompt：包含最近 3 轮对话（6 条消息）
      - LCEL 链：prompt | llm | StrOutputParser()
      - 异常时返回原始查询（失败回退）
    - 实现辅助函数 `contains_injection_pattern(text) -> bool`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [ ]* 7.2 编写查询改写属性测试
    - 创建 `tests/test_query_rewriter.py`
    - 测试短查询跳过：len ≤ 5 且 history=[] 时返回原始查询
    - 测试注入检测跳过：含注入模式时返回原始查询
    - 测试失败回退：LLM 异常时返回原始查询
    - **Property 9: 查询改写安全回退**
    - **Property 10: 查询改写失败回退**
    - **Validates: Requirements 6.1, 6.2, 6.4**

- [ ] 8. RAG 链编排
  - [ ] 8.1 实现 create_rag_chain 核心函数
    - 创建 `app/core/chain.py`
    - 实现 `create_rag_chain(config: AIChatConfig) -> Runnable`
    - LCEL 编排顺序：查询改写 → 向量检索 → 提示词构建 → LLM 生成 → StrOutputParser
    - 使用 `RunnablePassthrough.assign()` 逐步添加中间结果
    - 输入格式：`{"query": str, "history": list}`
    - 支持 `.invoke()` 和 `.astream()` 两种调用方式
    - 输出纯文本字符串
    - 实现 `extract_sources(documents) -> list[SourceInfo]`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [ ] 9. Checkpoint - 确保 RAG 链可端到端运行
  - 编写简单脚本测试 `create_rag_chain(config).invoke({"query": "测试", "history": []})`
  - 确保所有测试通过，有问题请提问

- [ ] 10. 会话管理
  - [ ] 10.1 实现 Redis 会话存储
    - 创建 `app/core/chat_history.py`
    - 定义 `ChatMessage` dataclass：role、content、timestamp
    - 定义 `ChatSession` dataclass：session_id、messages、created_at、last_active_at、client_ip
    - 实现 `RedisChatHistory` 类：
      - `KEY_PREFIX = "chat:session:"`，`TTL_SECONDS = 7 * 24 * 3600`
      - `async def get_session(session_id) -> ChatSession | None`：从 Redis 读取 JSON
      - `async def create_session(client_ip) -> ChatSession`：生成 UUID v4，写入 Redis
      - `async def append_message(session_id, message)`：追加消息，更新 lastActiveAt，刷新 TTL
      - `async def get_or_create(session_id) -> ChatSession`：有则获取，无则创建
    - JSON 序列化使用 camelCase 字段名（与 TypeScript 版兼容）
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [ ]* 10.2 编写会话管理属性测试
    - 创建 `tests/test_chat_history.py`
    - 测试追加后读取一致性：append_message 后 get_session 最后一条消息匹配
    - 测试 JSON 序列化 camelCase：所有字段名为 camelCase 格式
    - **Property 11: 会话追加一致性**
    - **Property 12: 会话 JSON camelCase 序列化**
    - **Validates: Requirements 10.2, 10.4**

- [ ] 11. 文本分块器
  - [ ] 11.1 实现 Markdown 感知分块
    - 创建 `app/infra/chunker.py`
    - 定义 `ContentMeta` dataclass：content_id、content_type、title、category_name、create_time
    - 实现 `chunk_content(markdown: str, meta: ContentMeta) -> list[Document]`：
      - Step 1: `MarkdownHeaderTextSplitter(headers_to_split_on=[("##", "section")])` 按标题分段
      - Step 2: `RecursiveCharacterTextSplitter.from_tiktoken_encoder(chunk_size=512, chunk_overlap=50)` 按 token 切分
      - Step 3: 注入语义前缀 `[{title}] [{section}] `
      - Step 4: 构造 Document，metadata 包含 sourceId、sourceType、title、categoryName、chunkIndex、chunkText、createTime
    - chunkIndex 从 0 递增，保证唯一
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ]* 11.2 编写分块属性测试
    - 创建 `tests/test_chunker.py`
    - 测试 token 上限：每个块 token ≤ 512
    - 测试 chunkIndex 单调递增：0, 1, 2, ..., N-1
    - 测试语义前缀：每个 Document.page_content 以 `[{title}]` 开头
    - **Property 4: 分块 token 上限**
    - **Property 5: 分块索引单调递增**
    - **Property 6: 分块语义前缀**
    - **Validates: Requirements 11.2, 11.4, 11.6**

- [ ] 12. 内容索引服务
  - [ ] 12.1 实现确定性 Point ID 生成
    - 创建 `app/infra/indexer.py`
    - 实现 `generate_point_id(content_id: int, chunk_index: int) -> str`
    - 算法：`SHA-1("{contentId}_chunk_{chunkIndex}")` 取前 16 字节构造 UUID
    - 使用 `hashlib.sha1` 和 `uuid.UUID(bytes=...)`
    - _Requirements: 12.5, 12.6, 18.4_

  - [ ]* 12.2 编写 Point ID 属性测试
    - 创建 `tests/test_indexer.py`
    - 相同输入始终生成相同 UUID
    - 输出是合法 UUID 格式
    - **Property 1: 确定性 Point ID**
    - **Validates: Requirements 12.5, 12.6**

  - [ ] 12.3 实现 MySQL 数据读取
    - 创建 `app/infra/db.py`
    - 使用 SQLAlchemy AsyncSession 连接 MySQL
    - 实现 `get_content(content_id, content_type) -> ContentMeta + markdown`
    - 实现 `get_all_contents() -> list`（用于全量重建）
    - _Requirements: 12.1_

  - [ ] 12.4 实现 ContentIndexer 索引管理
    - 在 `app/infra/indexer.py` 中实现 `ContentIndexer` 类：
      - `async def index_content(content_id, content_type) -> IndexResult`：读取内容 → 删除旧向量 → 分块 → Embedding → 写入 Qdrant
      - `async def remove_content_index(content_id) -> bool`：按 sourceId 过滤删除所有向量点
      - `async def rebuild_index() -> RebuildResult`：全量删除并重建
    - 使用确定性 Point ID 写入 Qdrant
    - Embedding 失败时指数退避重试（最多 5 次）
    - 索引已存在内容时先删除旧向量再写入新向量
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.7_

- [ ] 13. Checkpoint - 确保索引服务正常
  - 测试 `index_content` 能将文章写入 Qdrant
  - 测试 `remove_content_index` 能删除对应向量
  - 确保所有测试通过，有问题请提问

- [ ] 14. Pydantic 请求/响应模型
  - [ ] 14.1 定义所有 Schema 模型
    - 创建 `app/schemas/chat.py`：定义 ChatRequest（message, session_id）、ChatSSEEvent（type, content）、SourceInfo
    - 创建 `app/schemas/index.py`：定义 IndexRequest（content_id, content_type 限定 article|note）、IndexResponse、RebuildResponse
    - 创建 `app/schemas/config.py`：定义 ConfigResponse（camelCase alias）、ConfigUpdateRequest（temperature [0,2]、maxTokens [100,8192] 范围验证）
    - _Requirements: 13.1, 14.1, 14.4, 15.1, 15.3, 15.4_

- [ ] 15. SSE 流式聊天 API
  - [ ] 15.1 实现 POST /chat SSE 流式端点
    - 创建 `app/routers/chat.py`
    - 实现 `POST /chat` 路由：
      - 安全过滤 → 获取/创建会话 → 构建 RAG 链 → astream 流式输出
      - 使用 `sse_starlette.EventSourceResponse` 包装异步生成器
      - 每个 token 发送 `{"type": "token", "content": chunk}`
      - 流结束发送 `{"type": "sources", "content": [...]}`（包含检索来源信息）
      - 最后发送 `{"type": "done", "content": ""}`
      - 聊天完成后将用户消息和 AI 回复保存到会话历史
    - 错误处理：输入过滤失败返回 HTTP 400，LLM 不可达发送 error 事件
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

- [ ] 16. 索引管理 API
  - [ ] 16.1 实现索引 CRUD 路由
    - 创建 `app/routers/index.py`
    - `POST /index`：调用 indexer.index_content，返回 `{"success": true, "chunks": N}`
    - `POST /index/rebuild`：调用 indexer.rebuild_index，返回统计信息
    - `DELETE /index/{content_id}`：调用 indexer.remove_content_index
    - content_type 不是 article/note 时返回 HTTP 422
    - 索引失败时返回 HTTP 500 并说明失败原因
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

- [ ] 17. 配置 API
  - [ ] 17.1 实现配置读写路由
    - 创建 `app/routers/config.py`
    - `GET /config`：调用 config_manager.get_all()，返回 camelCase 配置
    - `PUT /config`：接受部分字段更新，验证 temperature [0,2]、maxTokens [100,8192]
    - 验证失败返回 HTTP 422，成功返回更新后完整配置
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

- [ ] 18. 错误处理与降级策略
  - [ ] 18.1 实现全局降级逻辑
    - 在 `app/core/chain.py` 中：Qdrant 检索失败时跳过检索，直接用 LLM 回答（降级模式）
    - 在 `app/core/chat_history.py` 中：Redis 读写失败时创建临时内存会话
    - 在 `app/core/query_rewriter.py` 中：LLM 调用异常时静默回退原始查询
    - 在 `app/core/llm.py` 中：LLM API 超时使用指数退避重试（最多 3 次）
    - 所有重试失败返回友好错误消息而非技术错误详情
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5_

- [ ] 19. 数据格式兼容性验证
  - [ ] 19.1 确保 Redis/Qdrant 数据格式与 TypeScript 服务兼容
    - Redis Hash 键使用 `ai_chat:config`，与 TypeScript 服务共享
    - Redis 会话键使用 `chat:session:{uuid}` 格式
    - Qdrant 集合名 `blog_content_chunks`
    - Point ID 使用 SHA-1 → UUID 确定性算法
    - Redis 和 API 响应统一使用 camelCase 字段名
    - 验证 Python 写入 → TypeScript 读取 和 TypeScript 写入 → Python 读取 双向兼容
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7_

  - [ ]* 19.2 编写数据兼容性属性测试
    - 创建 `tests/test_compatibility.py`
    - 测试 round-trip：Python 写入 Redis 后读取数据格式正确
    - 测试 camelCase 一致性
    - **Property 13: Redis 数据双向兼容（round-trip）**
    - **Validates: Requirements 18.6, 18.7**

- [ ] 20. 路由注册与应用集成
  - [ ] 20.1 完善 main.py 注册所有路由
    - 在 `app/main.py` 中：
      - `app.include_router(chat.router, tags=["chat"])`
      - `app.include_router(index.router, prefix="/index", tags=["index"])`
      - `app.include_router(config.router, prefix="/config", tags=["config"])`
    - lifespan 中完整初始化 Redis 连接池和 Qdrant 客户端
    - 关闭时释放所有连接资源
    - _Requirements: 1.1, 1.3, 1.4_

- [ ] 21. Docker 部署与 Next.js 代理集成
  - [ ] 21.1 完善 Docker 配置和代理集成
    - 更新 `Dockerfile`：安装生产依赖、设置 PYTHONPATH、CMD 启动 uvicorn
    - 更新 `docker-compose.yml`：配置 rag-service 服务、环境变量映射、depends_on、healthcheck
    - 支持通过环境变量 `RAG_SERVICE_URL` 配置服务地址
    - 确保 SSE 代理响应保持流式传输不中断
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

- [ ] 22. Final Checkpoint - 端到端验证
  - 启动 Docker 容器，验证所有 API 端点正常
  - 测试聊天 SSE 流式响应
  - 测试索引创建和删除
  - 测试配置读写
  - 确保所有测试通过，有问题请提问

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- 每个任务引用了具体的需求编号，方便追溯
- Checkpoints 确保增量验证，避免问题积累
- Property tests 验证核心算法的正确性属性（共 14 个属性，覆盖设计文档所有 Correctness Properties）
- 所有 Redis 数据格式使用 camelCase 键名，确保与 TypeScript 服务兼容
- RAG 链返回 Runnable 对象，为未来 LangGraph Agent Tool 迁移做预留
- 测试库使用 hypothesis 进行属性测试

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2", "3.4"] },
    { "id": 4, "tasks": ["3.3", "4.1"] },
    { "id": 5, "tasks": ["3.5", "4.2", "4.3"] },
    { "id": 6, "tasks": ["5.1", "6.1"] },
    { "id": 7, "tasks": ["5.2", "6.2"] },
    { "id": 8, "tasks": ["6.3", "7.1"] },
    { "id": 9, "tasks": ["7.2", "8.1"] },
    { "id": 10, "tasks": ["10.1", "11.1", "12.1"] },
    { "id": 11, "tasks": ["10.2", "11.2", "12.2", "12.3"] },
    { "id": 12, "tasks": ["12.4"] },
    { "id": 13, "tasks": ["14.1"] },
    { "id": 14, "tasks": ["15.1", "16.1", "17.1"] },
    { "id": 15, "tasks": ["18.1", "19.1"] },
    { "id": 16, "tasks": ["19.2", "20.1"] },
    { "id": 17, "tasks": ["21.1"] }
  ]
}
```
