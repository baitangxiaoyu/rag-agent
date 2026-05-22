from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from app.config import AIChatConfig


def create_embeddings(config: AIChatConfig) -> OpenAIEmbeddings:
    """创建 OpenAIEmbeddings 实例，使用配置中的 Embedding 参数"""
    embeddings = OpenAIEmbeddings(
        model=config.embedding_model,
        base_url=config.embedding_base_url,
        api_key=SecretStr(config.embedding_api_key),
        dimensions=config.embedding_dimensions,
    )
    return embeddings
