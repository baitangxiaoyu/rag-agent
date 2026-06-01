"""配置管理 API — 读写路由"""

from fastapi import APIRouter, Depends

from app.config import AIConfigManager
from app.dependencies import get_config_manager
from app.schemas.config import ConfigResponse, ConfigUpdateRequest

router = APIRouter()


@router.get("", response_model=ConfigResponse)
async def get_config(
    config_manager: AIConfigManager = Depends(get_config_manager),
):
    """获取当前完整配置（camelCase 键名）"""
    data = await config_manager.get_all()
    return ConfigResponse(**data)


@router.put("", response_model=ConfigResponse)
async def update_config(
    body: ConfigUpdateRequest,
    config_manager: AIConfigManager = Depends(get_config_manager),
):
    """
    更新配置（部分字段更新）

    验证规则由 Schema 层保证：
    - temperature: [0, 2]
    - maxTokens: [100, 8192]
    验证失败自动返回 HTTP 422。
    """
    # 只提取非 None 字段
    updates = body.model_dump(exclude_none=True, by_alias=False)
    config = await config_manager.update(updates)

    # 返回更新后的完整配置
    data = await config_manager.get_all()
    return ConfigResponse(**data)
