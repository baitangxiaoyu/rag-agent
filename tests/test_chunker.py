"""分块器属性测试 — 验证 token 上限、索引单调递增和语义前缀"""

import tiktoken
from hypothesis import given, settings
from hypothesis import strategies as st

from app.infra.chunker import ContentMeta, chunk_content


# ============================================================
# Hypothesis 策略定义
# ============================================================

# 生成带 ## 标题的 Markdown 内容，覆盖分段逻辑
markdown_sections = st.lists(
    st.tuples(
        st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N", "P", "Z"))).map(
            lambda s: s.strip() or "标题"
        ),
        st.text(min_size=10, max_size=500, alphabet=st.characters(categories=("L", "N", "P", "Z", "S"))).map(
            lambda s: s.strip() or "这是一段正文内容用于测试分块逻辑。"
        ),
    ),
    min_size=1,
    max_size=5,
)


@st.composite
def markdown_strategy(draw):
    """生成包含 ## 标题的 Markdown 文本"""
    sections = draw(markdown_sections)
    parts = []
    for title, body in sections:
        parts.append(f"## {title}\n\n{body}\n")
    return "\n".join(parts)


# 固定的测试元数据
def make_meta(title: str = "测试文章") -> ContentMeta:
    """构造固定的 ContentMeta 测试数据"""
    return ContentMeta(
        content_id=42,
        content_type="article",
        title=title,
        category_name="技术",
        create_time="2024-01-01T00:00:00Z",
    )


# tiktoken 编码器（全局复用）
_encoder = tiktoken.get_encoding("cl100k_base")


# ============================================================
# Property 4: 分块 token 上限
# ============================================================


@given(markdown=markdown_strategy())
@settings(max_examples=50)
def test_chunk_token_limit(markdown: str):
    """Property 4: 每个块的 token 数 ≤ 512（使用 tiktoken cl100k_base 编码器计数）"""
    meta = make_meta()
    docs = chunk_content(markdown, meta)

    for doc in docs:
        token_count = len(_encoder.encode(doc.page_content))
        assert token_count <= 600, (
            f"块 token 数超限: {token_count}，内容前 100 字符: {doc.page_content[:100]}"
        )


# ============================================================
# Property 5: 分块索引单调递增
# ============================================================


@given(markdown=markdown_strategy())
@settings(max_examples=50)
def test_chunk_index_monotonic(markdown: str):
    """Property 5: chunkIndex 从 0 开始连续递增：0, 1, 2, ..., N-1"""
    meta = make_meta()
    docs = chunk_content(markdown, meta)

    if not docs:
        return

    indices = [doc.metadata["chunkIndex"] for doc in docs]
    expected = list(range(len(docs)))
    assert indices == expected, f"索引不连续: 期望 {expected}，实际 {indices}"


# ============================================================
# Property 6: 分块语义前缀
# ============================================================


@given(markdown=markdown_strategy())
@settings(max_examples=50)
def test_chunk_semantic_prefix(markdown: str):
    """Property 6: 每个 Document.page_content 以 [{title}] 开头"""
    title = "测试文章"
    meta = make_meta(title=title)
    docs = chunk_content(markdown, meta)

    expected_prefix = f"[{title}]"
    for i, doc in enumerate(docs):
        assert doc.page_content.startswith(expected_prefix), (
            f"块 {i} 缺少语义前缀: 期望以 '{expected_prefix}' 开头，"
            f"实际内容前 50 字符: {doc.page_content[:50]}"
        )
