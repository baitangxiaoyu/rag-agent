# RAG Agent

基于 Python + FastAPI + LangChain 的检索增强生成（RAG）服务，从 Next.js 项目独立迁出的微服务。

## 技术栈

- **框架**: FastAPI + Uvicorn
- **AI 编排**: LangChain LCEL（支持同步/流式调用）
- **向量数据库**: Qdrant
- **缓存/会话**: Redis
- **数据库**: MySQL（SQLAlchemy AsyncSession）
- **LLM**: OpenAI-compatible API（智谱 GLM-4、Ollama 等）
- **Embedding**: OpenAI-compatible Embedding API

## 项目结构

```
app/
├── main.py              # FastAPI 入口、lifespan 生命周期
├── config.py            # 三级配置管理（默认值 → 环境变量 → Redis）
├── dependencies.py      # 依赖注入（Redis、Qdrant、ConfigManager）
├── core/
│   ├── chain.py         # RAG 链 LCEL 编排
│   ├── chat_history.py  # Redis 会话存储
│   ├── embeddings.py    # Embedding 工厂
│   ├── llm.py           # LLM 工厂（含指数退避重试）
│   ├── prompt.py        # 提示词模板构建
│   ├── query_rewriter.py # 查询改写链
│   └── retriever.py     # Qdrant 向量检索器
├── infra/
│   ├── chunker.py       # Markdown 感知文本分块器
│   ├── db.py            # MySQL 数据读取
│   ├── indexer.py       # 内容索引管理（向量写入/删除/重建）
│   └── security.py      # 输入校验与注入过滤
├── routers/
│   ├── chat.py          # POST /chat — SSE 流式聊天
│   ├── config.py        # GET/PUT /config — 配置读写
│   └── index.py         # POST/DELETE /index — 索引管理
└── schemas/
    ├── chat.py          # 聊天请求/响应模型
    ├── config.py        # 配置请求/响应模型
    └── index.py         # 索引请求/响应模型
```

## 快速开始

### 前置要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) 包管理器
- Redis、Qdrant（可用 Docker 启动）

### 本地开发

```bash
# 安装依赖
make sync

# 复制环境变量配置
cp .env.example .env
# 编辑 .env 填入 API Key 等配置

# 启动开发服务器
make dev

# 运行测试
make test

# 代码检查与格式化
make lint
make format
```

### Docker 部署

```bash
# 启动全部服务（rag-service + redis + qdrant）
docker compose up -d

# 查看健康状态
curl http://localhost:8000/health
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/chat` | SSE 流式聊天 |
| GET | `/config` | 获取配置 |
| PUT | `/config` | 更新配置 |
| POST | `/index` | 索引单篇内容 |
| POST | `/index/rebuild` | 全量重建索引 |
| DELETE | `/index/{content_id}` | 删除内容索引 |

### 聊天 SSE 事件格式

```jsonl
{"type": "token", "content": "你"}
{"type": "token", "content": "好"}
{"type": "sources", "content": [{"sourceId": 1, "title": "..."}]}
{"type": "done", "content": ""}
```

## 配置管理

三级优先级：**Redis Hash** > **环境变量** > **默认值**

运行时可通过 `PUT /config` 动态更新配置（写入 Redis），无需重启服务。

主要配置项：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| model | LLM 模型名称 | glm-4-flash |
| temperature | 温度参数 [0, 2] | 0.7 |
| maxTokens | 最大生成 token [100, 8192] | 2048 |
| topK | 检索文档数 | 5 |
| scoreThreshold | 相似度阈值 | 0.5 |
| queryRewriteEnabled | 是否启用查询改写 | true |

## 降级策略

服务设计了多层降级保障：

- **Qdrant 不可达** → 跳过向量检索，直接用 LLM 回答
- **Redis 不可达** → 使用临时内存会话，不影响聊天功能
- **LLM API 超时** → 指数退避重试（最多 3 次）
- **查询改写失败** → 静默回退原始查询

## 测试

使用 pytest + hypothesis 进行属性测试，覆盖核心算法正确性：

```bash
# 运行全部测试
make test

# 带覆盖率
make test-cov
```

## 数据兼容性

与原 TypeScript 服务完全兼容：
- Redis 键名和数据格式使用 camelCase
- Qdrant 集合名 `blog_content_chunks`
- Point ID 使用 SHA-1 确定性算法生成 UUID
- API 响应统一使用 camelCase 字段名
