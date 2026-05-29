"""Point ID 生成属性测试 — 验证确定性和 UUID 格式合法性"""

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from app.infra.indexer import generate_point_id


# ============================================================
# Property 1: 确定性 Point ID — 相同输入始终生成相同 UUID
# ============================================================


@given(
    content_id=st.integers(min_value=1, max_value=10_000_000),
    chunk_index=st.integers(min_value=0, max_value=1000),
)
@settings(max_examples=200)
def test_point_id_deterministic(content_id: int, chunk_index: int):
    """Property 1: 相同的 (content_id, chunk_index) 始终生成相同的 UUID"""
    id1 = generate_point_id(content_id, chunk_index)
    id2 = generate_point_id(content_id, chunk_index)
    assert id1 == id2, f"相同输入产生不同 ID: {id1} != {id2}"


# ============================================================
# Property: 输出是合法 UUID 格式
# ============================================================


@given(
    content_id=st.integers(min_value=1, max_value=10_000_000),
    chunk_index=st.integers(min_value=0, max_value=1000),
)
@settings(max_examples=200)
def test_point_id_valid_uuid(content_id: int, chunk_index: int):
    """输出是合法的 UUID 格式字符串"""
    point_id = generate_point_id(content_id, chunk_index)
    # uuid.UUID 会在格式非法时抛出 ValueError
    parsed = uuid.UUID(point_id)
    assert str(parsed) == point_id, f"UUID 格式不规范: {point_id}"


# ============================================================
# Property: 不同输入产生不同 UUID（碰撞极低）
# ============================================================


@given(
    content_id=st.integers(min_value=1, max_value=10_000_000),
    chunk_a=st.integers(min_value=0, max_value=1000),
    chunk_b=st.integers(min_value=0, max_value=1000),
)
@settings(max_examples=100)
def test_point_id_different_chunks_differ(content_id: int, chunk_a: int, chunk_b: int):
    """不同 chunk_index 应产生不同的 Point ID"""
    if chunk_a == chunk_b:
        return
    id_a = generate_point_id(content_id, chunk_a)
    id_b = generate_point_id(content_id, chunk_b)
    assert id_a != id_b, (
        f"不同块索引产生相同 ID: content_id={content_id}, "
        f"chunk {chunk_a} 和 {chunk_b} 都生成了 {id_a}"
    )
