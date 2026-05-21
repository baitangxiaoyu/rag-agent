"""配置管理模块 — 三级优先级：Redis Hash > 环境变量 > 默认值"""
from dataclasses import dataclass
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """环境变量配置（静态），通过 .env 文件或系统环境变量加载"""
    # model_config 代表优先从 .env文件中读取配置
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # === Redis ===
    redis_url: str = "redis://localhost:6379/0"

    # === Qdrant 向量数据库 ===
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None

    # === MySQL 数据库 ===
    database_url: str = "mysql+aiomysql://root:password@localhost:3306/blog"

    # === LLM 配置 ===
    llm_provider: str = "openai-compatible"
    llm_api_key: str = ""
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_model: str = "glm-4-flash"

    # === Embedding 配置 ===
    embedding_api_key: str = ""
    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    embedding_model: str = "embedding-3"
    embedding_dimensions: int = 2048

    # === 服务 ===
    port: int = 8000
# 全局 settings 实例（应用启动时自动从环境变量/.env 加载）
settings = Settings()

@dataclass
class AIChatConfig:
    """动态配置模型（对应 Redis Hash 字段），由 AIConfigManager 加载"""

    # LLM 模型配置
    model: str = "glm-4-flash"  # 主聊天模型名称（智谱 GLM-4-Flash）
    api_key: str = ""  # LLM API 密钥（从环境变量或 Redis 加载）
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"  # LLM API 基础地址
    temperature: float = 0.7  # 温度参数，控制回答随机性（0-1，越高越有创造性）
    max_tokens: int = 2048  # 单次生成最大 token 数（限制回答长度）
    
    # Embedding 向量模型配置
    embedding_model: str = "embedding-3"  # 文本嵌入模型名称（用于向量化）
    embedding_api_key: str = ""  # Embedding API 密钥（可与主模型不同）
    embedding_base_url: str = "https://open.bigmodel.cn/api/paas/v4"  # Embedding API 基础地址
    
    # RAG 检索配置
    top_k: int = 5  # 向量检索返回的最相关文档数量
    score_threshold: float = 0.5  # 相似度分数阈值（低于此值的文档被过滤）
    
    # 系统行为配置
    system_prompt: str = ""  # 系统提示词（定义 AI 助手的行为和角色）
    query_rewrite_enabled: bool = True  # 是否启用查询重写（优化用户问题以提高检索效果）
    content_filter_enabled: bool = True  # 是否启用内容过滤（过滤敏感或不适当的内容）


DEFAULT_SYSTEM_PROMPT = """你是一个智能博客助手，基于检索到的文章内容回答用户问题。
如果检索到的内容不足以回答问题，请诚实地说明。"""


def parse_redis_value(key: str, value: str):
    """
    Redis Hash 值类型转换（与 TypeScript 版 parseRedisHash 兼容）

    规则:
    - temperature, scoreThreshold → float
    - maxTokens, topK, embeddingDimensions → int
    - queryRewriteEnabled, contentFilterEnabled → bool ("true"/"false")
    - 其他 → str
    """
    float_fields = {"temperature", "scoreThreshold"}
    int_fields = {"maxTokens", "topK", "embeddingDimensions"}
    bool_fields = {"queryRewriteEnabled", "contentFilterEnabled"}
    if key in float_fields:
        return float(value)
    if key in int_fields:
        return int(value)
    if key in bool_fields:
        return value == 'true'
    return value


# camelCase(Redis) → snake_case(AIChatConfig) 字段映射
_CAMEL_TO_SNAKE = {
    "model": "model",
    "apiKey": "api_key",
    "baseUrl": "base_url",
    "temperature": "temperature",
    "maxTokens": "max_tokens",
    "embeddingModel": "embedding_model",
    "embeddingApiKey": "embedding_api_key",
    "embeddingBaseUrl": "embedding_base_url",
    "topK": "top_k",
    "scoreThreshold": "score_threshold",
    "systemPrompt": "system_prompt",
    "queryRewriteEnabled": "query_rewrite_enabled",
    "contentFilterEnabled": "content_filter_enabled",
}


class AIConfigManager:
    """配置管理器 — 三级优先级加载：Redis Hash > 环境变量 > 默认值"""

    REDIS_KEY = 'ai_chat:config'

    def __init__(self, redis_client):
        self._redis = redis_client
        self._settings = settings

    async def load(self) -> AIChatConfig:
        """
        加载配置，按优先级合并：
        1. 硬编码默认值（AIChatConfig 的字段默认值）
        2. 环境变量覆盖（从 Settings 读取）
        3. Redis Hash 覆盖（最高优先级）
        """
        # --- 第 1 层：默认值 ---
        config_dict: dict = {
            "model": "glm-4-flash",
            "api_key": "",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "temperature": 0.7,
            "max_tokens": 2048,
            "embedding_model": "embedding-3",
            "embedding_api_key": "",
            "embedding_base_url": "https://open.bigmodel.cn/api/paas/v4",
            "top_k": 5,
            "score_threshold": 0.5,
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
            "query_rewrite_enabled": True,
            "content_filter_enabled": True,
        }

        # --- 第 2 层：环境变量覆盖 ---
        s = self._settings
        env_overrides = {
            "model": s.llm_model,
            "api_key": s.llm_api_key,
            "base_url": s.llm_base_url,
            "embedding_model": s.embedding_model,
            "embedding_api_key": s.embedding_api_key,
            "embedding_base_url": s.embedding_base_url,
        }
        # 仅覆盖非空值
        for k, v in env_overrides.items():
            if v:
                config_dict[k] = v

        # --- 第 3 层：Redis Hash 覆盖（最高优先级）---
        try:
            redis_hash = await self._redis.hgetall(self.REDIS_KEY)
            for raw_key, raw_value in redis_hash.items():
                key_str = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
                val_str = raw_value.decode() if isinstance(raw_value, bytes) else raw_value

                # 类型转换
                typed_value = parse_redis_value(key_str, val_str)

                # camelCase → snake_case 映射
                snake_key = _CAMEL_TO_SNAKE.get(key_str)
                if snake_key:
                    config_dict[snake_key] = typed_value
        except Exception:
            # Redis 不可达时使用前两层配置（优雅降级）
            pass

        return AIChatConfig(**config_dict)

    async def update(self, updates: dict) -> AIChatConfig:
        """
        更新配置到 Redis Hash（camelCase 键名写入，与 TypeScript 服务兼容）

        参数 updates: snake_case 或 camelCase 键名均可，例如：
            {"temperature": 0.9, "max_tokens": 4096}
            或 {"temperature": 0.9, "maxTokens": 4096}

        返回更新后的完整 AIChatConfig
        """
        if not updates:
            return await self.load()

        # snake_case → camelCase 映射（反向）
        snake_to_camel = {v: k for k, v in _CAMEL_TO_SNAKE.items()}

        # 构建要写入 Redis 的 camelCase 键值对
        redis_updates: dict[str, str] = {}
        for key, value in updates.items():
            # 如果传入的是 snake_case，转成 camelCase
            camel_key = snake_to_camel.get(key, key)
            # 确保 camel_key 是已知字段
            if camel_key not in _CAMEL_TO_SNAKE:
                continue
            # bool 转为 "true"/"false" 字符串
            if isinstance(value, bool):
                redis_updates[camel_key] = "true" if value else "false"
            else:
                redis_updates[camel_key] = str(value)

        # 写入 Redis Hash
        if redis_updates:
            await self._redis.hset(self.REDIS_KEY, mapping=redis_updates)

        # 重新加载完整配置并返回
        return await self.load()

    async def get_all(self) -> dict:
        """获取当前完整配置（camelCase 键名，供 GET /config 使用）"""
        config = await self.load()

        # snake_case → camelCase
        snake_to_camel = {v: k for k, v in _CAMEL_TO_SNAKE.items()}
        result = {}
        for snake_key, value in config.__dict__.items():
            camel_key = snake_to_camel.get(snake_key, snake_key)
            result[camel_key] = value

        return result


