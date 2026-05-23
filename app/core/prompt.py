"""提示词模板构建模块 — 使用 LangChain ChatPromptTemplate 组装消息"""

from typing import List

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


# 默认系统提示词，可通过配置动态更新
DEFAULT_SYSTEM_PROMPT = """你是一个博客助手,基于提供的博客内容回答用户问题。回答时请遵守以下规则:
1. 引用或提及文章时,必须使用参考内容中标注的原始标题(《》内的文字),禁止自行改写、缩写或编造标题。
2. 如果参考内容中没有相关信息,请如实告知,不要编造不存在的文章。
3. 回答应基于参考内容的实际文本,不要臆测内容中未提及的信息。"""


def _format_documents(documents: List[Document]) -> str:
    """
    将检索到的文档格式化为上下文文本

    每个文档显示标题和内容，便于 LLM 引用来源。
    """
    if not documents:
        return ""

    formatted_parts: List[str] = []
    for doc in documents:
        # 从 metadata 中获取标题，兜底使用"未知标题"
        title = doc.metadata.get("title", "未知标题")
        # 优先使用 chunkText（原始文本），否则使用 page_content
        content = doc.metadata.get("chunkText", doc.page_content)
        formatted_parts.append(f"《{title}》\n{content}")

    return "\n\n---\n\n".join(formatted_parts)


def build_prompt_template(system_prompt: str | None = None) -> ChatPromptTemplate:
    """
    构建 ChatPromptTemplate，可直接参与 LCEL 链式组合

    模板变量:
        - system_with_context: 包含文档上下文的系统提示词
        - history: 对话历史（MessagesPlaceholder）
        - query: 用户当前查询

    用法:
        prompt = build_prompt_template()
        chain = prompt | llm | StrOutputParser()
        result = chain.invoke({"system_with_context": "...", "history": [...], "query": "..."})
    """
    return ChatPromptTemplate.from_messages([
        ("system", "{system_with_context}"),
        MessagesPlaceholder(variable_name="history", optional=True),
        ("human", "{query}"),
    ])


def build_messages(
    query: str,
    documents: List[Document],
    history: list | None = None,
    system_prompt: str | None = None,
) -> dict:
    """
    构建 prompt template 所需的输入字典

    参数:
        query: 用户当前查询
        documents: 检索到的相关文档列表
        history: 对话历史，支持 ChatMessage dataclass / dict / tuple 格式
        system_prompt: 系统提示词，为 None 时使用 DEFAULT_SYSTEM_PROMPT

    返回:
        dict — 可直接传入 ChatPromptTemplate.invoke() 的输入字典
    """
    # 1. 构建系统提示词（含文档上下文）
    effective_prompt = system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
    context_text = _format_documents(documents)

    if context_text:
        system_with_context = f"{effective_prompt}\n\n以下是参考内容:\n\n{context_text}"
    else:
        system_with_context = effective_prompt

    # 2. 将对话历史转换为 LangChain Message 对象
    messages: List[HumanMessage | AIMessage] = []
    if history:
        for item in history:
            if isinstance(item, tuple):
                role, content = item
            elif isinstance(item, dict):
                role = item.get("role", "")
                content = item.get("content", "")
            else:
                # 支持具有 role/content 属性的对象（如 ChatMessage dataclass）
                role = getattr(item, "role", "")
                content = getattr(item, "content", "")

            if role in ("user", "human"):
                messages.append(HumanMessage(content=content))
            elif role in ("assistant", "ai"):
                messages.append(AIMessage(content=content))

    # 3. 返回模板输入字典
    return {
        "system_with_context": system_with_context,
        "history": messages,
        "query": query,
    }
