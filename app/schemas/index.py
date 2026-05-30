"""索引管理相关的请求/响应模型"""

from typing import Literal

from pydantic import BaseModel, Field


class IndexRequest(BaseModel):
    """索引请求"""

    content_id: int = Field(..., description="内容 ID")
    content_type: Literal["article", "note"] = Field(..., description="内容类型，限定 article 或 note")


class IndexResponse(BaseModel):
    """索引操作响应"""

    success: bool = Field(..., description="操作是否成功")
    chunks: int = Field(0, description="索引的块数量")
    message: str = Field("", description="附加信息")


class RebuildResponse(BaseModel):
    """全量重建响应"""

    success: bool = Field(..., description="操作是否成功")
    total_contents: int = Field(0, alias="totalContents", description="总内容数")
    total_chunks: int = Field(0, alias="totalChunks", description="总块数")
    failed: int = Field(0, description="失败数")
    message: str = Field("", description="附加信息")

    model_config = {"populate_by_name": True}
