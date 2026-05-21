"""安全过滤模块 — 输入校验与文本清理"""

import re
from dataclasses import dataclass

# 注入模式正则列表（不区分大小写匹配）
_INJECTION_PATTERNS = [
    re.compile(r"忽略(之前|以上|上面|前面)?(的)?(所有)?(指令|指示|规则|设定|提示)", re.IGNORECASE),
    re.compile(r"扮演|假装(你是|自己是)", re.IGNORECASE),
    re.compile(r"\bsystem\s*:", re.IGNORECASE),
    re.compile(r"\bignore\s+(previous|above|all)\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"\bforget\s+(previous|above|all|your)(\s+\w+)*\s+(instructions?|prompts?|rules?)", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\b", re.IGNORECASE),
    re.compile(r"\bpretend\s+(to\s+be|you\s+are)\b", re.IGNORECASE),
    re.compile(r"<\|system\|>", re.IGNORECASE),
    re.compile(r"###\s*instruction", re.IGNORECASE),
]


@dataclass
class FilterResult:
    """输入过滤结果"""

    passed: bool = False
    reason: str | None = None


def _contains_injection_pattern(text: str) -> bool:
    """检测文本是否包含注入模式"""
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


# 需要从文本中移除的注入标记模式
_SANITIZE_PATTERNS = [
    re.compile(r"<\|system\|>", re.IGNORECASE),
    re.compile(r"<\|user\|>", re.IGNORECASE),
    re.compile(r"<\|assistant\|>", re.IGNORECASE),
    re.compile(r"<\|endoftext\|>", re.IGNORECASE),
    re.compile(r"###\s*instruction\s*###", re.IGNORECASE),
    re.compile(r"###\s*system\s*###", re.IGNORECASE),
    re.compile(r"###\s*end\s*###", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"\[/INST\]", re.IGNORECASE),
    re.compile(r"<<SYS>>", re.IGNORECASE),
    re.compile(r"<</SYS>>", re.IGNORECASE),
]


def sanitize_for_prompt(text: str) -> str:
    """
    清理文本中的潜在注入标记，保留正常内容

    移除的标记包括：
    - 模型特殊 token：<|system|>、<|user|>、<|endoftext|> 等
    - 指令分隔符：###instruction###、###system### 等
    - Llama 格式标记：[INST]、<<SYS>> 等
    """
    result = text
    for pattern in _SANITIZE_PATTERNS:
        result = pattern.sub("", result)
    # 清理多余空白（连续空格合并为单个）
    result = re.sub(r" {2,}", " ", result)
    return result.strip()


def validate_input(message: str) -> FilterResult:
    """
    校验用户输入消息

    规则：
    - 空字符串 → 拒绝
    - 长度 > 2000 → 拒绝
    - 匹配注入模式 → 拒绝
    - 其他 → 通过
    """
    if not message:
        return FilterResult(False, "消息不能为空")
    if len(message) > 2000:
        return FilterResult(False, "消息长度不能超过2000字符")
    if _contains_injection_pattern(message):
        return FilterResult(False, "检测到潜在的注入内容")
    return FilterResult(True)
