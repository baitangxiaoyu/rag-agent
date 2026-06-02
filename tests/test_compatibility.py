"""数据格式兼容性验证测试 — 确保 Python 服务与 TypeScript 服务双向兼容

验证内容：
1. Redis Hash 键使用 `ai_chat:config`
2. Redis 会话键使用 `chat:session:{uuid}` 格式
3. Qdrant 集合名 `blog_content_chunks`
4. Point ID 使用 SHA-1 → UUID 确定性算法
5. Redis 和 API 响应统一使用 camelCase 字段名
6. Python 写入 → TypeScript 读取 和 TypeScript 写入 → Python 读取 双向兼容
"""

import json
import uuid

import fakeredis.aioredis
import pytest

from app.config import AIConfigManager, AIChatConfig, parse_redis_value, _CAMEL_TO_SNAKE
from app.core.chat_history import (
    ChatMessage,
    RedisChatHistory,
    _dict_to_session,
    _session_to_dict,
    create_message,
)
from app.core.retriever import COLLECTION_NAME as RETRIEVER_COLLECTION
from app.infra.indexer import COLLECTION_NAME as INDEXER_COLLECTION, generate_point_id


# === 常量兼容性验证 ===


class TestRedisKeyCompatibility:
    """验证 Redis 键名与 TypeScript 服务一致"""

    def test_config_redis_key(self):
        """配置 Hash 键必须为 ai_chat:config"""
        assert AIConfigManager.REDIS_KEY == "ai_chat:config"

    def test_session_key_prefix(self):
        """会话键前缀必须为 chat:session:"""
        assert RedisChatHistory.KEY_PREFIX == "chat:session:"

    def test_session_key_format(self):
        """会话键格式为 chat:session:{uuid}"""
        session_id = str(uuid.uuid4())
        key = RedisChatHistory.KEY_PREFIX + session_id
        assert key == f"chat:session:{session_id}"
        # 验证 UUID 部分可以被解析
        uuid_part = key.replace("chat:session:", "")
        uuid.UUID(uuid_part)  # 不抛异常即为合法 UUID


class TestQdrantCollectionCompatibility:
    """验证 Qdrant 集合名称与 TypeScript 服务一致"""

    def test_retriever_collection_name(self):
        """检索器使用的集合名必须为 blog_content_chunks"""
        assert RETRIEVER_COLLECTION == "blog_content_chunks"

    def test_indexer_collection_name(self):
        """索引器使用的集合名必须为 blog_content_chunks"""
        assert INDEXER_COLLECTION == "blog_content_chunks"

    def test_both_modules_use_same_collection(self):
        """索引器和检索器必须使用相同的集合名"""
        assert RETRIEVER_COLLECTION == INDEXER_COLLECTION


class TestPointIdCompatibility:
    """验证 Point ID 生成算法与 TypeScript 服务一致"""

    def test_deterministic_output(self):
        """相同输入始终生成相同 UUID"""
        id1 = generate_point_id(42, 0)
        id2 = generate_point_id(42, 0)
        assert id1 == id2

    def test_valid_uuid_format(self):
        """输出为合法 UUID 格式"""
        point_id = generate_point_id(1, 0)
        parsed = uuid.UUID(point_id)
        assert str(parsed) == point_id

    def test_different_inputs_different_ids(self):
        """不同输入生成不同 UUID"""
        id1 = generate_point_id(1, 0)
        id2 = generate_point_id(1, 1)
        id3 = generate_point_id(2, 0)
        assert id1 != id2
        assert id1 != id3
        assert id2 != id3

    def test_seed_format(self):
        """验证种子字符串格式为 "{contentId}_chunk_{chunkIndex}" """
        # 通过验证已知输入的输出不变来间接验证种子格式
        # 如果种子格式改变，输出的 UUID 也会改变
        import hashlib
        seed = "123_chunk_0"
        sha1_hash = hashlib.sha1(seed.encode("utf-8")).digest()
        expected = str(uuid.UUID(bytes=sha1_hash[:16]))
        assert generate_point_id(123, 0) == expected


# === camelCase 字段名兼容性验证 ===


class TestCamelCaseCompatibility:
    """验证所有 Redis 数据和 API 响应使用 camelCase 字段名"""

    def test_config_camel_case_mapping_complete(self):
        """配置映射表覆盖所有 AIChatConfig 字段"""
        config = AIChatConfig()
        snake_fields = set(config.__dict__.keys())
        mapped_snakes = set(_CAMEL_TO_SNAKE.values())
        # 所有 AIChatConfig 字段都有 camelCase 映射
        assert snake_fields == mapped_snakes

    def test_session_serialization_camel_case(self):
        """会话序列化为 camelCase 字段名"""
        from app.core.chat_history import ChatSession
        session = ChatSession(
            session_id="test-id",
            messages=[ChatMessage(id="msg-1", role="user", content="你好", timestamp=1000)],
            created_at=1000,
            last_active_at=2000,
            client_ip="127.0.0.1",
        )
        data = _session_to_dict(session)

        # 顶层字段必须为 camelCase
        assert "sessionId" in data
        assert "createdAt" in data
        assert "lastActiveAt" in data
        assert "clientIp" in data
        assert "messages" in data

        # 不应有 snake_case 字段
        assert "session_id" not in data
        assert "created_at" not in data
        assert "last_active_at" not in data
        assert "client_ip" not in data

    def test_message_serialization_camel_case(self):
        """消息序列化为 camelCase 字段名"""
        from app.core.chat_history import ChatSession
        session = ChatSession(
            session_id="test-id",
            messages=[ChatMessage(id="msg-1", role="user", content="hello", timestamp=1000)],
            created_at=1000,
            last_active_at=2000,
        )
        data = _session_to_dict(session)
        msg = data["messages"][0]

        # 消息字段验证
        assert "id" in msg
        assert "role" in msg
        assert "content" in msg
        assert "timestamp" in msg


# === Round-Trip 双向兼容性验证 ===


class TestConfigRoundTrip:
    """验证配置数据 Python 写入 → TypeScript 读取 和 TypeScript 写入 → Python 读取"""

    @pytest.fixture
    async def redis_client(self):
        """使用 fakeredis 模拟 Redis"""
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        yield client
        await client.aclose()

    @pytest.fixture
    async def config_manager(self, redis_client):
        """配置管理器实例"""
        return AIConfigManager(redis_client)

    @pytest.mark.asyncio
    async def test_python_write_typescript_read(self, config_manager, redis_client):
        """Python 写入配置后，TypeScript 应能读取 camelCase 键名的 Redis Hash"""
        # Python 写入配置
        await config_manager.update({
            "temperature": 0.9,
            "max_tokens": 4096,
            "query_rewrite_enabled": False,
        })

        # 模拟 TypeScript 直接读取 Redis Hash
        raw_hash = await redis_client.hgetall(AIConfigManager.REDIS_KEY)
        ts_readable = {
            k.decode() if isinstance(k, bytes) else k: (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw_hash.items()
        }

        # TypeScript 期望读到 camelCase 键名
        assert "temperature" in ts_readable
        assert "maxTokens" in ts_readable
        assert "queryRewriteEnabled" in ts_readable

        # TypeScript 期望的值格式
        assert ts_readable["temperature"] == "0.9"
        assert ts_readable["maxTokens"] == "4096"
        assert ts_readable["queryRewriteEnabled"] == "false"

    @pytest.mark.asyncio
    async def test_typescript_write_python_read(self, config_manager, redis_client):
        """TypeScript 写入 camelCase 配置后，Python 应能正确解析"""
        # 模拟 TypeScript 写入 Redis Hash（camelCase 键名，字符串值）
        ts_config = {
            "model": "gpt-4",
            "temperature": "0.5",
            "maxTokens": "1024",
            "topK": "3",
            "scoreThreshold": "0.7",
            "queryRewriteEnabled": "true",
            "contentFilterEnabled": "false",
            "systemPrompt": "你是一个助手",
        }
        await redis_client.hset(AIConfigManager.REDIS_KEY, mapping=ts_config)

        # Python 读取配置
        config = await config_manager.load()

        # 验证类型转换正确
        assert config.model == "gpt-4"
        assert config.temperature == 0.5
        assert isinstance(config.temperature, float)
        assert config.max_tokens == 1024
        assert isinstance(config.max_tokens, int)
        assert config.top_k == 3
        assert isinstance(config.top_k, int)
        assert config.score_threshold == 0.7
        assert isinstance(config.score_threshold, float)
        assert config.query_rewrite_enabled is True
        assert isinstance(config.query_rewrite_enabled, bool)
        assert config.content_filter_enabled is False
        assert isinstance(config.content_filter_enabled, bool)
        assert config.system_prompt == "你是一个助手"

    @pytest.mark.asyncio
    async def test_config_get_all_returns_camel_case(self, config_manager, redis_client):
        """get_all() 返回 camelCase 键名的字典（供 API 响应使用）"""
        result = await config_manager.get_all()

        # 所有键名必须在 camelCase 映射表中
        camel_keys = set(_CAMEL_TO_SNAKE.keys())
        for key in result.keys():
            assert key in camel_keys, f"键 '{key}' 不在 camelCase 映射表中"


class TestSessionRoundTrip:
    """验证会话数据 Python 写入 → TypeScript 读取 和 TypeScript 写入 → Python 读取"""

    @pytest.fixture
    async def redis_client(self):
        """使用 fakeredis 模拟 Redis"""
        client = fakeredis.aioredis.FakeRedis(decode_responses=False)
        yield client
        await client.aclose()

    @pytest.fixture
    async def chat_history(self, redis_client):
        """会话管理器实例"""
        return RedisChatHistory(redis_client)

    @pytest.mark.asyncio
    async def test_python_write_typescript_read(self, chat_history, redis_client):
        """Python 创建会话后，TypeScript 应能读取 camelCase 格式的 JSON"""
        # Python 创建会话并追加消息
        session = await chat_history.create_session(client_ip="192.168.1.1")
        msg = create_message("user", "你好世界")
        await chat_history.append_message(session.session_id, msg)

        # 模拟 TypeScript 直接读取 Redis
        raw = await redis_client.get(RedisChatHistory.KEY_PREFIX + session.session_id)
        ts_data = json.loads(raw)

        # TypeScript 期望读到 camelCase 字段
        assert "sessionId" in ts_data
        assert "createdAt" in ts_data
        assert "lastActiveAt" in ts_data
        assert "clientIp" in ts_data
        assert "messages" in ts_data

        # 消息格式验证
        assert len(ts_data["messages"]) == 1
        msg_data = ts_data["messages"][0]
        assert "id" in msg_data
        assert "role" in msg_data
        assert "content" in msg_data
        assert "timestamp" in msg_data
        assert msg_data["role"] == "user"
        assert msg_data["content"] == "你好世界"

    @pytest.mark.asyncio
    async def test_typescript_write_python_read(self, chat_history, redis_client):
        """TypeScript 写入 camelCase JSON 后，Python 应能正确反序列化"""
        session_id = str(uuid.uuid4())

        # 模拟 TypeScript 写入的会话数据
        ts_session = {
            "sessionId": session_id,
            "messages": [
                {
                    "id": str(uuid.uuid4()),
                    "role": "user",
                    "content": "Hello from TypeScript",
                    "timestamp": 1700000000,
                },
                {
                    "id": str(uuid.uuid4()),
                    "role": "assistant",
                    "content": "Hi! How can I help?",
                    "timestamp": 1700000001,
                },
            ],
            "createdAt": 1700000000,
            "lastActiveAt": 1700000001,
            "clientIp": "10.0.0.1",
        }
        await redis_client.setex(
            RedisChatHistory.KEY_PREFIX + session_id,
            RedisChatHistory.TTL_SECONDS,
            json.dumps(ts_session),
        )

        # Python 读取会话
        session = await chat_history.get_session(session_id)
        assert session is not None
        assert session.session_id == session_id
        assert len(session.messages) == 2
        assert session.messages[0].role == "user"
        assert session.messages[0].content == "Hello from TypeScript"
        assert session.messages[1].role == "assistant"
        assert session.messages[1].content == "Hi! How can I help?"
        assert session.created_at == 1700000000
        assert session.last_active_at == 1700000001
        assert session.client_ip == "10.0.0.1"

    @pytest.mark.asyncio
    async def test_python_append_to_typescript_session(self, chat_history, redis_client):
        """Python 能向 TypeScript 创建的会话追加消息"""
        session_id = str(uuid.uuid4())

        # TypeScript 创建的会话（1 条消息）
        ts_session = {
            "sessionId": session_id,
            "messages": [
                {
                    "id": str(uuid.uuid4()),
                    "role": "user",
                    "content": "What is RAG?",
                    "timestamp": 1700000000,
                },
            ],
            "createdAt": 1700000000,
            "lastActiveAt": 1700000000,
            "clientIp": "10.0.0.1",
        }
        await redis_client.setex(
            RedisChatHistory.KEY_PREFIX + session_id,
            RedisChatHistory.TTL_SECONDS,
            json.dumps(ts_session),
        )

        # Python 追加 assistant 回复
        reply = create_message("assistant", "RAG 是检索增强生成...")
        await chat_history.append_message(session_id, reply)

        # 验证 TypeScript 能读到更新后的数据
        raw = await redis_client.get(RedisChatHistory.KEY_PREFIX + session_id)
        updated = json.loads(raw)
        assert len(updated["messages"]) == 2
        assert updated["messages"][1]["role"] == "assistant"
        assert updated["messages"][1]["content"] == "RAG 是检索增强生成..."
        # lastActiveAt 应该更新
        assert updated["lastActiveAt"] >= 1700000000


class TestParseRedisValueCompatibility:
    """验证 Redis 值解析与 TypeScript parseRedisHash 一致"""

    def test_float_fields(self):
        """temperature 和 scoreThreshold 解析为 float"""
        assert parse_redis_value("temperature", "0.7") == 0.7
        assert parse_redis_value("scoreThreshold", "0.85") == 0.85
        assert isinstance(parse_redis_value("temperature", "1"), float)

    def test_int_fields(self):
        """maxTokens、topK、embeddingDimensions 解析为 int"""
        assert parse_redis_value("maxTokens", "4096") == 4096
        assert parse_redis_value("topK", "10") == 10
        assert parse_redis_value("embeddingDimensions", "2048") == 2048
        assert isinstance(parse_redis_value("maxTokens", "100"), int)

    def test_bool_fields(self):
        """queryRewriteEnabled 和 contentFilterEnabled 解析为 bool"""
        assert parse_redis_value("queryRewriteEnabled", "true") is True
        assert parse_redis_value("queryRewriteEnabled", "false") is False
        assert parse_redis_value("contentFilterEnabled", "true") is True
        assert parse_redis_value("contentFilterEnabled", "false") is False

    def test_string_fields(self):
        """未知字段保持字符串"""
        assert parse_redis_value("model", "gpt-4") == "gpt-4"
        assert parse_redis_value("systemPrompt", "你好") == "你好"
        assert parse_redis_value("baseUrl", "https://api.example.com") == "https://api.example.com"
