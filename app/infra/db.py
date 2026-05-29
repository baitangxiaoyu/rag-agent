"""数据库访问模块 — 使用 SQLAlchemy AsyncSession 读取 MySQL 内容"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.chunker import ContentMeta

logger = logging.getLogger(__name__)


async def get_content(
    database_url: str,
    content_id: int,
    content_type: str,
) -> tuple[ContentMeta, str] | None:
    """
    根据 content_id 和 content_type 从 MySQL 读取内容。

    参数:
        database_url: 数据库连接 URL（mysql+aiomysql://...）
        content_id: 内容 ID
        content_type: 内容类型（"article" 或 "note"）

    返回:
        (ContentMeta, markdown) 元组，未找到时返回 None
    """
    engine = create_async_engine(database_url, pool_pre_ping=True)

    try:
        async with AsyncSession(engine) as session:
            if content_type == "article":
                query = text(
                    "SELECT id, title, category_name, content, create_time "
                    "FROM articles WHERE id = :content_id"
                )
            elif content_type == "note":
                query = text(
                    "SELECT id, title, category_name, content, create_time "
                    "FROM notes WHERE id = :content_id"
                )
            else:
                logger.error(f"不支持的内容类型: {content_type}")
                return None

            result = await session.execute(query, {"content_id": content_id})
            row = result.fetchone()

            if row is None:
                return None

            meta = ContentMeta(
                content_id=row[0],
                content_type=content_type,
                title=row[1] or "",
                category_name=row[2] or "",
                create_time=str(row[4]) if row[4] else "",
            )
            markdown = row[3] or ""

            return meta, markdown
    finally:
        await engine.dispose()


async def get_all_contents(database_url: str) -> list[tuple[int, str]]:
    """
    获取所有内容的 (content_id, content_type) 列表（用于全量重建索引）。

    返回:
        [(content_id, content_type), ...] 列表
    """
    engine = create_async_engine(database_url, pool_pre_ping=True)

    try:
        async with AsyncSession(engine) as session:
            contents: list[tuple[int, str]] = []

            # 读取所有文章
            articles_result = await session.execute(
                text("SELECT id FROM articles")
            )
            for row in articles_result.fetchall():
                contents.append((row[0], "article"))

            # 读取所有笔记
            notes_result = await session.execute(
                text("SELECT id FROM notes")
            )
            for row in notes_result.fetchall():
                contents.append((row[0], "note"))

            return contents
    finally:
        await engine.dispose()
