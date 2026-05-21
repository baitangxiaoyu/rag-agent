"""配置管理模块单元测试 — 验证三级优先级和类型转换"""

import pytest
import fakeredis.aioredis

from app.config import AIConfigManager, AIChatConfig, parse_redis_value, settings


@pytest.fixture
async def redis_client():
    """创建 fakeredis 异步实例用于测试"""
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield client
    await client.flushall()
    await client.aclose()


@pytest.fixture
async def config_manager(redis_client):
    """创建配置管理器实例"""
    return AIConfigManager(redis_client=redis_client)


# ============================================================
# Property 2: 配置三级优先级
# ============================================================


class TestConfigPriority:
    """测试三级优先级：Redis Hash > 环境变量 > 默认值"""

    async def test_default_values_when_redis_empty(self, config_manager):
        """Redis 无值时使用默认值/环境变量"""
        config = await config_manager.load()

        assert isinstance(config, AIChatConfig)
        # 默认值字段
        assert config.temperature == 0.7
        assert config.max_tokens == 2048
        assert config.top_k == 5
        assert config.score_threshold == 0.5
        assert config.query_rewrite_enabled is True
        assert config.content_filter_enabled is True

    async def test_env_overrides_default(self, config_manager):
        """环境变量覆盖默认值（Settings 中 llm_model 有值时覆盖 model 字段）"""
        config = await config_manager.load()

        # Settings 的 llm_model 默认为 "glm-4-flash"，与 AIChatConfig 默认值一致
        # 验证环境变量层正确注入
        assert config.model == settings.llm_model

    async def test_redis_overrides_env(self, redis_client, config_manager):
        """Redis Hash 值覆盖环境变量（最高优先级）"""
        # 写入 Redis Hash（camelCase 键名）
        await redis_client.hset(
            AIConfigManager.REDIS_KEY,
            mapping={
                b"temperature": b"0.3",
                b"maxTokens": b"4096",
                b"topK": b"10",
                b"scoreThreshold": b"0.8",
                b"queryRewriteEnabled": b"false",
                b"contentFilterEnabled": b"false",
                b"model": b"gpt-4o",
                b"systemPrompt": b"custom prompt",
            },
        )

        config = await config_manager.load()

        # Redis 值覆盖默认值和环境变量
        assert config.temperature == 0.3
        assert config.max_tokens == 4096
        assert config.top_k == 10
        assert config.score_threshold == 0.8
        assert config.query_rewrite_enabled is False
        assert config.content_filter_enabled is False
        assert config.model == "gpt-4o"
        assert config.system_prompt == "custom prompt"

    async def test_partial_redis_override(self, redis_client, config_manager):
        """Redis 仅部分字段有值时，未覆盖的字段保留环境变量/默认值"""
        await redis_client.hset(
            AIConfigManager.REDIS_KEY,
            mapping={b"temperature": b"0.9"},
        )

        config = await config_manager.load()

        # Redis 覆盖的字段
        assert config.temperature == 0.9
        # 未覆盖的字段保留默认值
        assert config.max_tokens == 2048
        assert config.top_k == 5

    async def test_redis_unavailable_graceful_degradation(self, config_manager):
        """Redis 不可达时优雅降级，使用环境变量/默认值"""
        # 关闭连接模拟不可达
        await config_manager._redis.aclose()

        config = await config_manager.load()

        # 应该返回有效配置（来自默认值和环境变量）
        assert isinstance(config, AIChatConfig)
        assert config.temperature == 0.7
        assert config.max_tokens == 2048


# ============================================================
# Property 3: Redis 值类型解析
# ============================================================


class TestParseRedisValue:
    """测试 parse_redis_value 类型转换正确性"""

    # --- float 类型字段 ---

    def test_temperature_to_float(self):
        assert parse_redis_value("temperature", "0.5") == 0.5
        assert isinstance(parse_redis_value("temperature", "0.5"), float)

    def test_score_threshold_to_float(self):
        assert parse_redis_value("scoreThreshold", "0.75") == 0.75
        assert isinstance(parse_redis_value("scoreThreshold", "0.75"), float)

    # --- int 类型字段 ---

    def test_max_tokens_to_int(self):
        assert parse_redis_value("maxTokens", "4096") == 4096
        assert isinstance(parse_redis_value("maxTokens", "4096"), int)

    def test_top_k_to_int(self):
        assert parse_redis_value("topK", "10") == 10
        assert isinstance(parse_redis_value("topK", "10"), int)

    def test_embedding_dimensions_to_int(self):
        assert parse_redis_value("embeddingDimensions", "1536") == 1536
        assert isinstance(parse_redis_value("embeddingDimensions", "1536"), int)

    # --- bool 类型字段 ---

    def test_query_rewrite_enabled_true(self):
        assert parse_redis_value("queryRewriteEnabled", "true") is True

    def test_query_rewrite_enabled_false(self):
        assert parse_redis_value("queryRewriteEnabled", "false") is False

    def test_content_filter_enabled_true(self):
        assert parse_redis_value("contentFilterEnabled", "true") is True

    def test_content_filter_enabled_false(self):
        assert parse_redis_value("contentFilterEnabled", "false") is False

    # --- str 类型字段（默认） ---

    def test_model_as_string(self):
        assert parse_redis_value("model", "gpt-4o") == "gpt-4o"
        assert isinstance(parse_redis_value("model", "gpt-4o"), str)

    def test_unknown_key_as_string(self):
        assert parse_redis_value("unknownKey", "someValue") == "someValue"
        assert isinstance(parse_redis_value("unknownKey", "someValue"), str)


# ============================================================
# 配置更新测试
# ============================================================


class TestConfigUpdate:
    """测试配置更新功能"""

    async def test_update_writes_to_redis(self, redis_client, config_manager):
        """update() 将值写入 Redis Hash（camelCase 键名）"""
        await config_manager.update({"temperature": 0.9, "max_tokens": 4096})

        # 验证 Redis 中存储的值
        raw = await redis_client.hget(AIConfigManager.REDIS_KEY, "temperature")
        assert raw == b"0.9"

        raw = await redis_client.hget(AIConfigManager.REDIS_KEY, "maxTokens")
        assert raw == b"4096"

    async def test_update_returns_merged_config(self, config_manager):
        """update() 返回合并后的完整配置"""
        config = await config_manager.update({"temperature": 0.1})

        assert isinstance(config, AIChatConfig)
        assert config.temperature == 0.1
        # 其他字段保持默认
        assert config.max_tokens == 2048

    async def test_update_bool_stored_as_string(self, redis_client, config_manager):
        """bool 值存储为 "true"/"false" 字符串"""
        await config_manager.update({"query_rewrite_enabled": False})

        raw = await redis_client.hget(AIConfigManager.REDIS_KEY, "queryRewriteEnabled")
        assert raw == b"false"

    async def test_get_all_returns_camel_case(self, config_manager):
        """get_all() 返回 camelCase 键名字典"""
        result = await config_manager.get_all()

        assert "temperature" in result
        assert "maxTokens" in result
        assert "topK" in result
        assert "queryRewriteEnabled" in result
        # 不应有 snake_case 键
        assert "max_tokens" not in result
        assert "top_k" not in result
