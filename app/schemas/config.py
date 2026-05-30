"""配置管理相关的请求/响应模型"""

from pydantic import BaseModel, Field


class ConfigResponse(BaseModel):
    """配置响应（camelCase alias，与 TypeScript 服务兼容）"""

    model: str = Field("", description="LLM 模型名称")
    api_key: str = Field("", alias="apiKey", description="LLM API 密钥")
    base_url: str = Field("", alias="baseUrl", description="LLM API 基础地址")
    temperature: float = Field(0.7, description="温度参数")
    max_tokens: int = Field(2048, alias="maxTokens", description="最大 token 数")
    embedding_model: str = Field("", alias="embeddingModel", description="Embedding 模型")
    embedding_api_key: str = Field("", alias="embeddingApiKey", description="Embedding API 密钥")
    embedding_base_url: str = Field("", alias="embeddingBaseUrl", description="Embedding API 地址")
    embedding_dimensions: int = Field(2048, alias="embeddingDimensions", description="向量维度")
    top_k: int = Field(5, alias="topK", description="检索 top-k")
    score_threshold: float = Field(0.5, alias="scoreThreshold", description="相似度阈值")
    system_prompt: str = Field("", alias="systemPrompt", description="系统提示词")
    query_rewrite_enabled: bool = Field(True, alias="queryRewriteEnabled", description="是否启用查询改写")
    content_filter_enabled: bool = Field(True, alias="contentFilterEnabled", description="是否启用内容过滤")

    model_config = {"populate_by_name": True}


class ConfigUpdateRequest(BaseModel):
    """配置更新请求（部分字段更新）"""

    model: str | None = None
    api_key: str | None = Field(None, alias="apiKey")
    base_url: str | None = Field(None, alias="baseUrl")
    temperature: float | None = Field(None, ge=0, le=2, description="温度范围 [0, 2]")
    max_tokens: int | None = Field(None, alias="maxTokens", ge=100, le=8192, description="token 数范围 [100, 8192]")
    embedding_model: str | None = Field(None, alias="embeddingModel")
    embedding_api_key: str | None = Field(None, alias="embeddingApiKey")
    embedding_base_url: str | None = Field(None, alias="embeddingBaseUrl")
    embedding_dimensions: int | None = Field(None, alias="embeddingDimensions")
    top_k: int | None = Field(None, alias="topK")
    score_threshold: float | None = Field(None, alias="scoreThreshold")
    system_prompt: str | None = Field(None, alias="systemPrompt")
    query_rewrite_enabled: bool | None = Field(None, alias="queryRewriteEnabled")
    content_filter_enabled: bool | None = Field(None, alias="contentFilterEnabled")

    model_config = {"populate_by_name": True}
