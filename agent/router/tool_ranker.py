"""ToolRanker：多信号加权融合排序（策略模式）。

final_score = embedding*0.10 + reasoning*0.55 + 参数覆盖率*0.20 + 动词匹配*0.10 + 参数模式*0.05

权重为初始建议，通过 golden set 标定；LLM 推理信号占主导，
因此"LLM 选中的工具"必然排在前面，同时保留 embedding 的纠偏能力。
"""
from .models import ProblemType, ToolCall, ToolCandidate, ToolEntry

DEFAULT_WEIGHTS = {
    "embedding": 0.10,
    "reasoning": 0.55,
    "coverage": 0.20,
    "verb": 0.10,
    "pattern": 0.05,
}

# 动词匹配：问题类型对应的动作锚点，命中即 +1
VERB_ANCHORS = {
    ProblemType.ACTION: ["帮我", "我要", "我想", "申请", "投诉", "退款", "提交", "转", "取消"],
    ProblemType.QUERY: ["查", "查询", "看", "了解", "咨询", "进度", "状态", "多少钱", "价格", "有没有"],
    ProblemType.GUIDE: ["怎么", "如何", "步骤", "流程"],
    ProblemType.CHAT: ["你好", "谢谢", "再见"],
}


class ToolRanker:
    def __init__(self, weights: dict[str, float] | None = None):
        self._weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self._weights.update(weights)

    def fuse(
        self,
        *,
        text: str,
        candidates: list[ToolCandidate],
        reasoning_calls: list[ToolCall],
        tools: dict[str, ToolEntry],
        problem_type: ProblemType | None,
    ) -> list[ToolCandidate]:
        reasoning_names = {call.tool for call in reasoning_calls}
        anchors = VERB_ANCHORS.get(problem_type, []) if problem_type else []
        for candidate in candidates:
            tool = tools.get(candidate.name)
            candidate.reasoning_score = 1.0 if candidate.name in reasoning_names else 0.0
            candidate.structural_score = self._coverage(candidate, tool)
            candidate.verb_score = 1.0 if any(a in (text or "") for a in anchors) else 0.0
            candidate.final_score = self._final(candidate)
        return sorted(candidates, key=lambda c: c.final_score, reverse=True)

    @staticmethod
    def _coverage(candidate: ToolCandidate, tool: ToolEntry | None) -> float:
        if tool is None or not tool.parameters:
            return 1.0
        required = [p for p in tool.parameters.values() if p.required]
        if not required:
            return 1.0
        provided = sum(
            1
            for p in required
            if candidate.parameters.get(p.name) not in (None, "")
        )
        return provided / len(required)

    def _final(self, candidate: ToolCandidate) -> float:
        score = (
            candidate.embedding_score * self._weights["embedding"]
            + candidate.reasoning_score * self._weights["reasoning"]
            + candidate.structural_score * self._weights["coverage"]
            + candidate.verb_score * self._weights["verb"]
        )
        return round(score, 6)
