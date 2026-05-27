"""会话管理属性测试 — 验证追加一致性和 camelCase 序列化"""

import json
import time
import uuid as uuid_mod

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.chat_history import (
    ChatMessage,
    ChatSession,
    RedisChatHistory,
    _dict_to_session,
    _session_to_dict,
    create_message,
)


# ============================================================
# Hypothesis 策略定义
# ============================================================

roles = st.sampled_from(["user", "assistant"])
message_contents = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())
timestamps = st.integers(min_value=1_600_000_000, max_value=2_000_000_000)

chat_messages = st.builds(
    ChatMessage,
    id=st.uuids().map(str),
    role=roles,
    content=message_contents,
    timestamp=timestamps,
)

chat_sessions = st.builds(
    ChatSession,
    session_id=st.uuids().map(str),
    messages=st.lists(chat_messages, min_size=0, max_size=10),
    created_at=timestamps,
    last_active_at=timestamps,
    client_ip=st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True),
)


# ============================================================
# FakeRedis 模拟
# ============================================================


class FakeRedis:
    """模拟 Redis 客户端"""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value


# ============================================================
# Property 11: 会话追加一致性
# ============================================================


@given(session=chat_sessions, new_message=chat_messages)
@settings(max_examples=50)
def test_append_message_consistency(session: ChatSession, new_message: ChatMessage):
    """Property 11: 追加消息后读取，最后一条消息 ID、内容应与追加的消息一致"""
    import asyncio

    async def _run():
        fake_redis = FakeRedis()
        history = RedisChatHistory(redis_client=fake_redis)

        await history._save_session(session)
        await history.append_message(session.session_id, new_message)

        loaded = await history.get_session(session.session_id)
        assert loaded is not None
        assert len(loaded.messages) == len(session.messages) + 1

        last_msg = loaded.messages[-1]
        assert last_msg.id == new_message.id
        assert last_msg.role == new_message.role
        assert last_msg.content == new_message.content
        assert last_msg.timestamp == new_message.timestamp

    asyncio.run(_run())


# ============================================================
# Property 12: 会话 JSON camelCase 序列化
# ============================================================

ALLOWED_TOP_KEYS = {"sessionId", "messages", "createdAt", "lastActiveAt", "clientIp"}
ALLOWED_MESSAGE_KEYS = {"id", "role", "content", "timestamp"}


@given(session=chat_sessions)
@settings(max_examples=50)
def test_session_json_camel_case(session: ChatSession):
    """Property 12: 序列化后的 JSON 字段名全部为 camelCase"""
    data = _session_to_dict(session)
    assert set(data.keys()) == ALLOWED_TOP_KEYS
    for msg_dict in data["messages"]:
        assert set(msg_dict.keys()) == ALLOWED_MESSAGE_KEYS


@given(session=chat_sessions)
@settings(max_examples=50)
def test_session_serialization_roundtrip(session: ChatSession):
    """序列化 → 反序列化 round-trip 数据一致"""
    data = _session_to_dict(session)
    json_str = json.dumps(data, ensure_ascii=False)
    restored = _dict_to_session(json.loads(json_str))

    assert restored.session_id == session.session_id
    assert restored.created_at == session.created_at
    assert restored.last_active_at == session.last_active_at
    assert restored.client_ip == session.client_ip
    assert len(restored.messages) == len(session.messages)

    for orig, rest in zip(session.messages, restored.messages):
        assert orig.id == rest.id
        assert orig.role == rest.role
        assert orig.content == rest.content
        assert orig.timestamp == rest.timestamp


# ============================================================
# 基础单元测试
# ============================================================


@pytest.mark.asyncio
async def test_create_session_generates_uuid_v4():
    """创建会话应生成有效的 UUID v4"""
    fake_redis = FakeRedis()
    history = RedisChatHistory(redis_client=fake_redis)

    session = await history.create_session(client_ip="192.168.1.1")

    parsed = uuid_mod.UUID(session.session_id)
    assert parsed.version == 4
    assert session.client_ip == "192.168.1.1"
    assert session.messages == []


@pytest.mark.asyncio
async def test_create_message_factory():
    """create_message 工厂函数应生成带唯一 ID 的消息"""
    msg = create_message("user", "你好")

    parsed = uuid_mod.UUID(msg.id)
    assert parsed.version == 4
    assert msg.role == "user"
    assert msg.content == "你好"
    assert msg.timestamp > 0


@pytest.mark.asyncio
async def test_message_ids_are_unique():
    """每条消息的 ID 应唯一"""
    messages = [create_message("user", f"消息{i}") for i in range(100)]
    ids = [m.id for m in messages]
    assert len(set(ids)) == 100


@pytest.mark.asyncio
async def test_get_or_create_returns_existing():
    """get_or_create 在会话存在时返回已有会话"""
    fake_redis = FakeRedis()
    history = RedisChatHistory(redis_client=fake_redis)

    created = await history.create_session()
    fetched = await history.get_or_create(created.session_id)

    assert fetched.session_id == created.session_id


@pytest.mark.asyncio
async def test_get_or_create_creates_new_when_not_found():
    """get_or_create 在会话不存在时创建新会话"""
    fake_redis = FakeRedis()
    history = RedisChatHistory(redis_client=fake_redis)

    session = await history.get_or_create("nonexistent-id", client_ip="127.0.0.1")

    assert session is not None
    assert session.client_ip == "127.0.0.1"


@pytest.mark.asyncio
async def test_append_message_raises_on_missing_session():
    """对不存在的会话追加消息应抛出 ValueError"""
    fake_redis = FakeRedis()
    history = RedisChatHistory(redis_client=fake_redis)

    msg = ChatMessage(id=str(uuid_mod.uuid4()), role="user", content="你好", timestamp=int(time.time()))

    with pytest.raises(ValueError, match="会话不存在"):
        await history.append_message("no-such-session", msg)


@pytest.mark.asyncio
async def test_key_prefix_format():
    """Redis 键前缀应为 chat:session:"""
    fake_redis = FakeRedis()
    history = RedisChatHistory(redis_client=fake_redis)

    session = await history.create_session()

    expected_key = f"chat:session:{session.session_id}"
    assert expected_key in fake_redis.store
