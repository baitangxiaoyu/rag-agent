"""查询改写模块 — 结合对话历史改写用户查询以提升检索效果"""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from app.infra.security import _contains_injection_pattern

# 改写提示词模板
REWRITE_SYSTEM_PROMPT = """你是一个查询改写助手。根据对话历史，将用户的当前问题改写为一个独立的、适合向量检索的查询语句。

规则：
1. 保持原始意图不变
2. 补充对话上下文中的指代和省略
3. 输出一句简洁的检索查询，不要解释
4. 如果当前问题已经足够独立，直接返回原文"""


def should_rewrite(query: str, history: list) -> bool:
    """
    判断是否需要改写查询

    规则：
    - 短查询（≤5字符）且无历史 → False（无需改写）
    - 查询包含注入模式 → False（安全回退）
    - 其他情况 → True
    """
    if len(query) <= 5 and len(history) == 0:
        return False
    if contains_injection_pattern(query):
        return False
    return True


def contains_injection_pattern(text: str) -> bool:
    """检测文本是否包含注入模式（委托给安全模块）"""
    return _contains_injection_pattern(text)


def _format_history(history: list) -> str:
    """格式化对话历史为文本"""
    if not history:
        return "无"
    lines = []
    for msg in history:
        role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
        content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
        prefix = "用户" if role == "user" else "助手"
        lines.append(f"{prefix}: {content}")
    return "\n".join(lines)

def create_query_rewriter(config) -> Runnable:
    """
    创建查询改写链

    输入: {"query": str, "history": list}
    输出: str (改写后的查询)

    安全策略:
    - 输入截断: 500 字符上限
    - 注入检测: 正则匹配危险模式
    - 失败回退: 返回原始查询
    - 短查询跳过: ≤5 字符且无历史时直接返回
    """
    from app.core.llm import create_llm

    rewrite_prompt = ChatPromptTemplate.from_messages([
        ("system", REWRITE_SYSTEM_PROMPT),
        ("human", "对话历史:\n{history}\n\n当前问题: {query}\n\n改写后的检索查询:"),
    ])

    llm = create_llm(config)
    chain = rewrite_prompt | llm | StrOutputParser()

    async def _rewrite(inputs: dict) -> str:
        """执行查询改写，包含安全检查和失败回退"""
        query = inputs["query"]
        history = inputs.get("history", [])

        # 输入截断
        truncated_query = query[:500]

        # 判断是否需要改写
        if not should_rewrite(truncated_query, history):
            return truncated_query

        # 只取最近 3 轮对话（6 条消息）
        recent_history = history[-6:]

        try:
            result = await chain.ainvoke({
                "query": truncated_query,
                "history": _format_history(recent_history),
            })
            return result.strip()
        except Exception:
            # 失败回退：返回原始查询（截断后）
            return truncated_query

    return RunnableLambda(_rewrite)
