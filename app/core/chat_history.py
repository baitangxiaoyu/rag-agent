"""Redis 会话存储模块 — 管理聊天会话的持久化和检索"""

import json
import time
import uuid
from dataclasses import dataclass, field

from redis.asyncio import Redis


@dataclass
class ChatMessage:
    """单条聊天消息，每条消息拥有唯一 ID"""

    id: str
    role: str
    content: str
    timestamp: int


@dataclass
class ChatSession:
    """聊天会话，包含完整消息历史"""

    session_id: str
    messages: list[ChatMessage] = field(default_factory=list)
    created_at: int = 0
    last_active_at: int = 0
    client_ip: str = ""


def _session_to_dict(session: ChatSession) -> dict:
    """将 ChatSession 序列化为 camelCase 字典（兼容 TypeScript 服务）"""
    return {
        "sessionId": session.session_id,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp,
            }
            for msg in session.messages
        ],
        "createdAt": session.created_at,
        "lastActiveAt": session.last_active_at,
        "clientIp": session.client_ip,
    }


def _dict_to_session(data: dict) -> ChatSession:
    """将 camelCase 字典反序列化为 ChatSession"""
    messages = [
        ChatMessage(
            id=msg["id"],
            role=msg["role"],
            content=msg["content"],
            timestamp=msg["timestamp"],
        )
        for msg in data.get("messages", [])
    ]
    return ChatSession(
        session_id=data["sessionId"],
        messages=messages,
        created_at=data["createdAt"],
        last_active_at=data["lastActiveAt"],
        client_ip=data.get("clientIp", ""),
    )


def create_message(role: str, content: str) -> ChatMessage:
    """创建带唯一 ID 和当前时间戳的消息（工厂函数）"""
    return ChatMessage(
        id=str(uuid.uuid4()),
        role=role,
        content=content,
        timestamp=int(time.time()),
    )


class RedisChatHistory:
    """基于 Redis 的会话存储，支持 TTL 自动过期

    数据层级：
    - 对话窗口 (session_id) → 包含多条消息
    - 消息 (message.id) → 单条交互记录
    """

    KEY_PREFIX = "chat:session:"
    TTL_SECONDS = 7 * 24 * 3600  # 7 天

    def __init__(self, redis_client: Redis) -> None:
        self.redis_client = redis_client

    async def get_session(self, session_id: str) -> ChatSession | None:
        """根据会话 ID 获取会话，不存在返回 None"""
        raw = await self.redis_client.get(self.KEY_PREFIX + session_id)
        if raw is None:
            return None
        data = json.loads(raw)
        return _dict_to_session(data)

    async def create_session(self, client_ip: str = "") -> ChatSession:
        """创建新会话，生成 UUID v4 作为会话 ID"""
        session_id = str(uuid.uuid4())
        now = int(time.time())
        session = ChatSession(
            session_id=session_id,
            messages=[],
            created_at=now,
            last_active_at=now,
            client_ip=client_ip,
        )
        await self._save_session(session)
        return session

    async def append_message(self, session_id: str, message: ChatMessage) -> None:
        """向会话追加消息，更新 lastActiveAt 并刷新 TTL"""
        session = await self.get_session(session_id)
        if session is None:
            raise ValueError(f"会话不存在: {session_id}")
        session.messages.append(message)
        session.last_active_at = int(time.time())
        await self._save_session(session)

    async def get_or_create(self, session_id: str | None, client_ip: str = "") -> ChatSession:
        """获取已有会话或创建新会话"""
        if session_id:
            session = await self.get_session(session_id)
            if session is not None:
                return session
        return await self.create_session(client_ip)

    async def _save_session(self, session: ChatSession) -> None:
        """将会话序列化为 JSON 写入 Redis，设置 TTL"""
        data = _session_to_dict(session)
        await self.redis_client.setex(
            self.KEY_PREFIX + session.session_id,
            self.TTL_SECONDS,
            json.dumps(data, ensure_ascii=False),
        )
