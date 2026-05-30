"""聊天相关的请求/响应模型"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """聊天请求"""

    message: str = Field(..., description="用户消息内容")
    session_id: str | None = Field(None, description="会话 ID（UUID v4），为空则创建新会话")


class SourceInfo(BaseModel):
    """检索来源信息"""

    source_id: int = Field(..., alias="sourceId", description="内容 ID")
    source_type: str = Field(..., alias="sourceType", description="内容类型")
    title: str = Field("", description="内容标题")
    category_name: str = Field("", alias="categoryName", description="分类名称")
    chunk_index: int = Field(0, alias="chunkIndex", description="块索引")

    model_config = {"populate_by_name": True}


class ChatSSEEvent(BaseModel):
    """SSE 事件数据"""

    type: str = Field(..., description="事件类型: token / sources / done / error")
    content: str | list = Field("", description="事件内容")
