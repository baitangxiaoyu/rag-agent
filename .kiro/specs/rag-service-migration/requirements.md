# Requirements Document

## Introduction

本文档描述将现有 Next.js 项目中的 RAG 模块（`src/lib/rag/`）迁移为独立 Python 服务的功能需求。Python 服务使用 FastAPI 作为 Web 框架，LangChain LCEL 编排 RAG 流程，需与现有 TypeScript 服务共享 Redis 键、Qdrant 集合，实现无缝并存和渐进式迁移。

## Glossary

- **RAG_Service**: 基于 FastAPI 的 Python RAG 服务
- **Config_Manager**: 三级优先级配置管理器（Redis > 环境变量 > 默认值）
- **Security_Filter**: 输入安全过滤模块，负责 Prompt 注入检测和内容校验
- **Embedding_Factory**: 嵌入向量模型工厂，创建 OpenAIEmbeddings 实例
- **Vector_Retriever**: 基于 QdrantVectorStore 的向量检索器
- **Query_Rewriter**: 查询改写链，结合历史对话优化检索查询
- **RAG_Chain**: LCEL RunnableSequence 编排的完整 RAG 流程
- **Chat_History**: Redis 持久化的会话管理模块
- **Content_Indexer**: 文章/笔记向量索引管理器
- **Text_Chunker**: Markdown 感知的文本分块器
- **LLM_Client**: ChatOpenAI 大语言模型客户端
- **Prompt_Builder**: ChatPromptTemplate 提示词构建器
- **SSE**: Server-Sent Events，服务器推送事件流
- **Point_ID**: Qdrant 向量点的唯一标识符
- **LCEL**: LangChain Expression Language
- **camelCase**: 驼峰命名格式（如 `maxTokens`）

## Requirements

### Requirement 1: 项目脚手架与健康检查

**User Story:** 作为开发者，我希望有一个可运行的 FastAPI 项目骨架和健康检查端点，以便验证服务部署是否正常。

#### Acceptance Criteria

1. WHEN RAG_Service 启动完成, THE RAG_Service SHALL 在配置的端口上监听 HTTP 请求
2. WHEN 客户端发送 GET /health 请求, THE RAG_Service SHALL 返回 HTTP 200 状态码和 `{"status": "ok", "service": "rag-service"}` JSON 响应
3. WHEN RAG_Service 启动时, THE RAG_Service SHALL 初始化 Redis 和 Qdrant 连接池
4. WHEN RAG_Service 关闭时, THE RAG_Service SHALL 释放所有连接池资源

---

### Requirement 2: 配置管理

**User Story:** 作为开发者，我希望有一个三级优先级的配置系统（Redis > 环境变量 > 默认值），以便灵活管理服务配置且与现有 TypeScript 服务共享配置。

#### Acceptance Criteria

1. THE Config_Manager SHALL 使用 Redis Hash 键 `ai_chat:config` 存储动态配置
2. WHEN 加载配置时, THE Config_Manager SHALL 按以下优先级合并配置：Redis Hash 字段值 > 环境变量 > 硬编码默认值
3. WHEN Redis Hash 中某字段存在值时, THE Config_Manager SHALL 使用该值覆盖环境变量和默认值
4. WHEN Redis Hash 中某字段不存在但环境变量已设置时, THE Config_Manager SHALL 使用环境变量值覆盖默认值
5. WHEN 解析 Redis Hash 值时, THE Config_Manager SHALL 将字符串值正确转换为目标类型（temperature→float, maxTokens→int, queryRewriteEnabled→bool）
6. WHEN 写入配置到 Redis 时, THE Config_Manager SHALL 使用 camelCase 字段名以兼容 TypeScript 服务
7. WHEN TypeScript 服务通过管理后台写入 Redis 配置后, THE Config_Manager SHALL 能正确读取并解析这些配置

---

### Requirement 3: 安全过滤

**User Story:** 作为开发者，我希望有输入安全校验机制，以便防止 Prompt 注入攻击和恶意内容。

#### Acceptance Criteria

1. WHEN 用户输入为空字符串时, THE Security_Filter SHALL 返回 FilterResult(passed=False, reason="消息不能为空")
2. WHEN 用户输入超过 2000 字符时, THE Security_Filter SHALL 返回 FilterResult(passed=False) 并说明长度超限
3. WHEN 用户输入匹配 Prompt 注入模式时, THE Security_Filter SHALL 返回 FilterResult(passed=False) 并说明检测到注入
4. WHEN 用户输入通过所有检查时, THE Security_Filter SHALL 返回 FilterResult(passed=True)
5. THE Security_Filter SHALL 对相同输入始终返回相同的过滤结果（幂等性）
6. WHEN 对文本执行清理操作时, THE Security_Filter SHALL 移除潜在注入内容但保留正常文本

---

### Requirement 4: 嵌入模型集成

**User Story:** 作为开发者，我希望使用 LangChain OpenAIEmbeddings 生成向量，以便与现有 Qdrant 集合中的向量兼容。

#### Acceptance Criteria

1. THE Embedding_Factory SHALL 创建 OpenAIEmbeddings 实例并配置为与现有 Qdrant 集合兼容的向量维度
2. WHEN 配置中指定 embedding_model、embedding_base_url 和 embedding_api_key 时, THE Embedding_Factory SHALL 使用这些参数创建实例
3. THE Embedding_Factory SHALL 生成与 TypeScript 服务相同维度（默认 2048 维）的嵌入向量

---

### Requirement 5: 向量检索

**User Story:** 作为开发者，我希望能从现有 Qdrant 集合中检索相关文档，以便为 RAG 链提供上下文。

#### Acceptance Criteria

1. THE Vector_Retriever SHALL 连接到现有 Qdrant 集合 `blog_content_chunks`
2. WHEN 执行相似度检索时, THE Vector_Retriever SHALL 返回相似度分数高于 config.score_threshold 的文档
3. WHEN 执行检索时, THE Vector_Retriever SHALL 最多返回 config.top_k 篇文档
4. THE Vector_Retriever SHALL 正确读取 Payload 中的 sourceId、sourceType、title、categoryName、chunkIndex、chunkText 字段
5. WHEN Qdrant 服务不可达时, THE Vector_Retriever SHALL 返回空文档列表而非抛出未处理异常

---

### Requirement 6: 查询改写

**User Story:** 作为开发者，我希望结合对话历史改写用户查询，以便提高向量检索的准确性。

#### Acceptance Criteria

1. WHEN 查询长度 ≤5 字符且对话历史为空时, THE Query_Rewriter SHALL 跳过改写并返回原始查询
2. WHEN 查询包含 Prompt 注入模式时, THE Query_Rewriter SHALL 跳过改写并返回原始查询（安全回退）
3. WHEN 查询长度超过 500 字符时, THE Query_Rewriter SHALL 截断至 500 字符后再执行改写
4. WHEN LLM 调用异常时, THE Query_Rewriter SHALL 返回原始查询而非抛出异常（失败回退）
5. WHEN 执行改写时, THE Query_Rewriter SHALL 仅使用最近 3 轮对话（6 条消息）作为上下文
6. WHEN config.query_rewrite_enabled 为 False 时, THE RAG_Chain SHALL 跳过查询改写步骤

---

### Requirement 7: RAG 链编排

**User Story:** 作为开发者，我希望用 LCEL 编排完整的 RAG 流程并返回 Runnable 对象，以便支持同步调用和流式输出，且未来可直接包装为 LangGraph Tool。

#### Acceptance Criteria

1. THE RAG_Chain SHALL 接受 `{"query": str, "history": list}` 作为输入
2. THE RAG_Chain SHALL 返回 Runnable 对象，支持 `.invoke()` 和 `.astream()` 方法
3. WHEN 执行 RAG_Chain 时, THE RAG_Chain SHALL 按顺序执行：查询改写 → 向量检索 → 提示词构建 → LLM 生成
4. THE RAG_Chain SHALL 输出纯文本字符串作为最终结果
5. WHEN 使用 `.astream()` 时, THE RAG_Chain SHALL 逐 token 流式输出 LLM 生成内容

---

### Requirement 8: LLM 集成

**User Story:** 作为开发者，我希望使用 ChatOpenAI 接入大语言模型 API，以便生成对话回复。

#### Acceptance Criteria

1. THE LLM_Client SHALL 创建 ChatOpenAI 实例并启用 streaming=True
2. WHEN 配置中指定 model、base_url、api_key、temperature、max_tokens 时, THE LLM_Client SHALL 使用这些参数
3. THE LLM_Client SHALL 兼容 OpenAI-compatible API（包括智谱 AI、Ollama 等）

---

### Requirement 9: 提示词模板

**User Story:** 作为开发者，我希望使用 ChatPromptTemplate 构建结构化提示词，以便统一管理系统提示和上下文注入。

#### Acceptance Criteria

1. THE Prompt_Builder SHALL 将系统提示词、检索到的文档上下文、对话历史和用户查询组装为完整消息列表
2. WHEN 检索到文档时, THE Prompt_Builder SHALL 将文档内容格式化后注入到提示词上下文中
3. WHEN 系统提示词通过配置更新时, THE Prompt_Builder SHALL 使用最新的系统提示词

---

### Requirement 10: 会话管理

**User Story:** 作为开发者，我希望使用 Redis 持久化对话历史，以便支持多轮对话且与 TypeScript 服务共享会话数据。

#### Acceptance Criteria

1. THE Chat_History SHALL 使用 Redis 键前缀 `chat:session:` 存储会话数据
2. THE Chat_History SHALL 使用 JSON 序列化且字段名为 camelCase 格式，与 TypeScript 服务兼容
3. WHEN 创建新会话时, THE Chat_History SHALL 生成 UUID v4 作为 session_id
4. WHEN 追加消息到会话时, THE Chat_History SHALL 将消息添加到 messages 数组末尾并更新 lastActiveAt 时间戳
5. THE Chat_History SHALL 为每个会话设置 7 天 TTL 过期时间
6. WHEN 请求中 session_id 为空时, THE Chat_History SHALL 创建新会话
7. WHEN TypeScript 服务创建的会话时, THE Chat_History SHALL 能正确读取和追加消息

---

### Requirement 11: 文本分块

**User Story:** 作为开发者，我希望以 Markdown 感知的方式对文章进行分块，以便保留文档结构并控制每块的 token 数量。

#### Acceptance Criteria

1. WHEN 处理 Markdown 文本时, THE Text_Chunker SHALL 首先按 `##` 标题分割为段落组
2. WHEN 段落组超过 512 token 时, THE Text_Chunker SHALL 使用 RecursiveCharacterTextSplitter 进一步切分
3. THE Text_Chunker SHALL 在相邻分块之间保留 50 token 的重叠
4. WHEN 生成分块时, THE Text_Chunker SHALL 为每个块注入语义前缀 `[标题] [章节名] `
5. THE Text_Chunker SHALL 为每个 Document 附加 metadata：sourceId、sourceType、title、categoryName、chunkIndex、chunkText、createTime
6. THE Text_Chunker SHALL 保证 chunkIndex 从 0 开始单调递增且唯一

---

### Requirement 12: 内容索引管理

**User Story:** 作为开发者，我希望能对文章/笔记进行向量化索引操作（新增、删除、全量重建），以便保持向量库与内容同步。

#### Acceptance Criteria

1. WHEN 调用 index_content(content_id, content_type) 时, THE Content_Indexer SHALL 从 MySQL 读取内容、分块、生成嵌入向量并写入 Qdrant
2. WHEN 索引已存在的内容时, THE Content_Indexer SHALL 先删除该 content_id 的旧向量再写入新向量
3. WHEN 调用 remove_content_index(content_id) 时, THE Content_Indexer SHALL 删除该 content_id 对应的所有 Qdrant 向量点
4. WHEN 调用 rebuild_index() 时, THE Content_Indexer SHALL 重建所有文章和笔记的索引
5. THE Content_Indexer SHALL 使用确定性 Point ID 生成算法：SHA-1("{contentId}_chunk_{chunkIndex}") 取前 16 字节构造 UUID
6. WHEN 相同 content_id 和 chunk_index 输入时, THE Content_Indexer SHALL 始终生成相同的 Point ID
7. WHEN Embedding API 调用失败时, THE Content_Indexer SHALL 使用指数退避重试（最多 5 次）

---

### Requirement 13: SSE 流式聊天 API

**User Story:** 作为开发者，我希望通过 SSE 流式返回聊天回复，以便前端能实时展示 AI 生成的文本。

#### Acceptance Criteria

1. WHEN 客户端发送 POST /chat 请求时, THE RAG_Service SHALL 返回 Content-Type 为 text/event-stream 的 SSE 响应
2. WHEN LLM 生成 token 时, THE RAG_Service SHALL 发送 `{"type": "token", "content": "<token>"}` 事件
3. WHEN LLM 生成完成后, THE RAG_Service SHALL 发送 `{"type": "sources", "content": [...]}` 事件包含检索来源信息
4. WHEN 所有事件发送完毕后, THE RAG_Service SHALL 发送 `{"type": "done", "content": ""}` 结束事件
5. WHEN 输入未通过安全过滤时, THE RAG_Service SHALL 返回 HTTP 400 错误并说明原因
6. WHEN LLM API 不可达时, THE RAG_Service SHALL 发送 `{"type": "error", "content": "AI 服务暂时不可用"}` 错误事件
7. WHEN 聊天完成后, THE RAG_Service SHALL 将用户消息和 AI 回复保存到会话历史

---

### Requirement 14: 索引管理 API

**User Story:** 作为开发者，我希望通过 HTTP API 管理文章索引，以便 Next.js 在文章发布/更新/删除时触发索引操作。

#### Acceptance Criteria

1. WHEN 客户端发送 POST /index 请求含 content_id 和 content_type 时, THE RAG_Service SHALL 执行单篇索引并返回 `{"success": true, "chunks": N}`
2. WHEN 客户端发送 POST /index/rebuild 请求时, THE RAG_Service SHALL 执行全量重建并返回统计信息
3. WHEN 客户端发送 DELETE /index/{content_id} 请求时, THE RAG_Service SHALL 删除对应索引
4. WHEN content_type 不是 "article" 或 "note" 时, THE RAG_Service SHALL 返回 HTTP 422 验证错误
5. WHEN 索引操作失败时, THE RAG_Service SHALL 返回 HTTP 500 错误并说明失败原因

---

### Requirement 15: 配置 API

**User Story:** 作为开发者，我希望通过 HTTP API 读写 RAG 配置，以便在管理后台动态调整服务参数。

#### Acceptance Criteria

1. WHEN 客户端发送 GET /config 请求时, THE RAG_Service SHALL 返回当前完整配置（camelCase 字段名）
2. WHEN 客户端发送 PUT /config 请求含部分字段时, THE RAG_Service SHALL 仅更新指定字段到 Redis
3. WHEN 配置更新请求中 temperature 不在 [0, 2] 范围时, THE RAG_Service SHALL 返回 HTTP 422 验证错误
4. WHEN 配置更新请求中 maxTokens 不在 [100, 8192] 范围时, THE RAG_Service SHALL 返回 HTTP 422 验证错误
5. WHEN 配置更新成功后, THE RAG_Service SHALL 返回更新后的完整配置

---

### Requirement 16: Docker 部署与 Next.js 代理集成

**User Story:** 作为开发者，我希望将 RAG 服务容器化部署，并通过 Next.js API 路由代理请求，以便前端无感知地切换到 Python 服务。

#### Acceptance Criteria

1. THE RAG_Service SHALL 提供 Dockerfile 支持容器化构建和部署
2. THE RAG_Service SHALL 在 docker-compose.yml 中配置健康检查（/health 端点）
3. WHEN Next.js API 路由收到聊天请求时, THE RAG_Service SHALL 通过 HTTP 代理接收并处理请求
4. THE RAG_Service SHALL 支持通过环境变量 RAG_SERVICE_URL 配置服务地址
5. WHEN 代理 SSE 响应时, THE RAG_Service SHALL 保持流式传输不中断

---

### Requirement 17: 错误处理与降级

**User Story:** 作为开发者，我希望服务在外部依赖不可用时能优雅降级，以便提高系统可用性。

#### Acceptance Criteria

1. WHEN Qdrant 检索失败时, THE RAG_Service SHALL 跳过检索步骤并直接用 LLM 回答（降级模式）
2. WHEN Redis 会话读写失败时, THE RAG_Service SHALL 创建临时内存会话保证当前请求正常处理
3. WHEN 查询改写 LLM 调用异常时, THE RAG_Service SHALL 静默回退到原始查询不影响主流程
4. WHEN LLM API 超时时, THE RAG_Service SHALL 使用指数退避重试最多 3 次
5. IF 所有重试都失败, THEN THE RAG_Service SHALL 返回友好错误消息而非技术错误详情

---

### Requirement 18: 数据格式兼容性

**User Story:** 作为开发者，我希望 Python 服务与 TypeScript 服务的数据格式完全兼容，以便两个服务可以并行运行并共享数据。

#### Acceptance Criteria

1. THE RAG_Service SHALL 使用与 TypeScript 服务相同的 Redis Hash 键 `ai_chat:config` 存储配置
2. THE RAG_Service SHALL 使用与 TypeScript 服务相同的 Redis 键格式 `chat:session:{uuid}` 存储会话
3. THE RAG_Service SHALL 使用与 TypeScript 服务相同的 Qdrant 集合名 `blog_content_chunks`
4. THE RAG_Service SHALL 使用与 TypeScript 服务相同的确定性 Point ID 算法（SHA-1 → UUID）
5. THE RAG_Service SHALL 在 Redis 和 API 响应中使用 camelCase 字段名
6. WHEN Python 服务写入 Redis 数据后, THE RAG_Service SHALL 保证 TypeScript 服务能正确读取
7. WHEN TypeScript 服务写入 Redis 数据后, THE RAG_Service SHALL 保证 Python 服务能正确读取
