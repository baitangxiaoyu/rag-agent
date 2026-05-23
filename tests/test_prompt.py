"""提示词组装属性测试 — 使用 hypothesis 验证 build_messages 的正确性属性

**Property 14: 提示词组装完整性**
**Validates: Requirements 9.1, 9.2**
"""

from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from app.core.prompt import DEFAULT_SYSTEM_PROMPT, build_messages


# ============================================================
# 策略定义
# ============================================================

# 非空查询字符串
query_strategy = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())

# 自定义系统提示词（可选）
system_prompt_strategy = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=500).filter(lambda s: s.strip()),
)

# 文档标题（非空）
title_strategy = st.text(min_size=1, max_size=50).filter(lambda s: s.strip())

# 单个文档
document_strategy = st.builds(
    lambda title, content: Document(
        page_content=content,
        metadata={"title": title, "chunkText": content},
    ),
    title=title_strategy,
    content=st.text(min_size=1, max_size=300).filter(lambda s: s.strip()),
)

# 文档列表（0~5 个）
documents_strategy = st.lists(document_strategy, min_size=0, max_size=5)

# 单条历史消息（dict 格式）
history_message_strategy = st.fixed_dictionaries({
    "role": st.sampled_from(["user", "assistant"]),
    "content": st.text(min_size=1, max_size=100).filter(lambda s: s.strip()),
})

# 历史消息列表（0~6 条）
history_strategy = st.one_of(
    st.none(),
    st.lists(history_message_strategy, min_size=0, max_size=6),
)


# ============================================================
# 属性测试
# ============================================================


class TestPromptAssemblyCompleteness:
    """Property 14: 提示词组装完整性"""

    @given(
        query=query_strategy,
        documents=documents_strategy,
        history=history_strategy,
        system_prompt=system_prompt_strategy,
    )
    @settings(max_examples=100)
    def test_returned_dict_contains_required_keys(
        self, query, documents, history, system_prompt
    ):
        """返回字典必须包含 system_with_context、history、query 三个键"""
        result = build_messages(
            query=query,
            documents=documents,
            history=history,
            system_prompt=system_prompt,
        )

        assert "system_with_context" in result
        assert "history" in result
        assert "query" in result

    @given(
        query=query_strategy,
        documents=documents_strategy,
        history=history_strategy,
        system_prompt=system_prompt_strategy,
    )
    @settings(max_examples=100)
    def test_system_with_context_contains_system_prompt(
        self, query, documents, history, system_prompt
    ):
        """system_with_context 必须包含系统提示词文本（默认或自定义）"""
        result = build_messages(
            query=query,
            documents=documents,
            history=history,
            system_prompt=system_prompt,
        )

        expected_prompt = system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
        assert expected_prompt in result["system_with_context"]

    @given(
        query=query_strategy,
        documents=st.lists(document_strategy, min_size=1, max_size=5),
        history=history_strategy,
        system_prompt=system_prompt_strategy,
    )
    @settings(max_examples=100)
    def test_documents_titles_appear_in_context(
        self, query, documents, history, system_prompt
    ):
        """当提供文档时，system_with_context 必须包含每个文档的标题"""
        result = build_messages(
            query=query,
            documents=documents,
            history=history,
            system_prompt=system_prompt,
        )

        for doc in documents:
            title = doc.metadata["title"]
            # 文档以《title》格式出现在上下文中
            assert f"《{title}》" in result["system_with_context"]

    @given(
        query=query_strategy,
        documents=documents_strategy,
        history=history_strategy,
        system_prompt=system_prompt_strategy,
    )
    @settings(max_examples=100)
    def test_query_equals_input(self, query, documents, history, system_prompt):
        """返回字典中的 query 必须等于输入的 query"""
        result = build_messages(
            query=query,
            documents=documents,
            history=history,
            system_prompt=system_prompt,
        )

        assert result["query"] == query

    @given(
        query=query_strategy,
        documents=documents_strategy,
        history=st.lists(history_message_strategy, min_size=1, max_size=6),
        system_prompt=system_prompt_strategy,
    )
    @settings(max_examples=100)
    def test_history_messages_correctly_converted(
        self, query, documents, history, system_prompt
    ):
        """历史消息必须正确转换为 HumanMessage/AIMessage 对象"""
        result = build_messages(
            query=query,
            documents=documents,
            history=history,
            system_prompt=system_prompt,
        )

        converted = result["history"]
        assert len(converted) == len(history)

        for original, converted_msg in zip(history, converted):
            if original["role"] == "user":
                assert isinstance(converted_msg, HumanMessage)
            elif original["role"] == "assistant":
                assert isinstance(converted_msg, AIMessage)
            assert converted_msg.content == original["content"]
