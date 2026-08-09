"""工具路由的领域模型。

设计说明：
- 工具（ToolEntry）取代旧的"意图"概念：一个工具 = 一个可执行的能力
  （用户流程 / 知识问答 / 闲聊兜底），带参数 schema，供 LLM 直接填参。
- RoutingResult 是路由层的统一输出，决策由代码做出（三态/四态判决），
  LLM 只负责"这句话涉及哪些工具、填哪些参数"（语言理解）。
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProblemType(str, Enum):
    """问题类型：决定响应方式（不是分类层，只是路由策略的输入信号）。"""

    ACTION = "action"      # 执行类：退款申请、工单提交、转人工
    QUERY = "query"        # 查询类：订单状态、学习进度、课程信息
    GUIDE = "guide"        # 指南类：怎么操作/如何申请 → 走知识库，不启动流程
    CHAT = "chat"          # 闲聊兜底


class Decision(str, Enum):
    """代码做出的路由判决（四态，对应文章第 4~6 阶段的三态/四态判决）。"""

    CLEAR = "clear"             # 明确：直接执行
    AMBIGUOUS = "ambiguous"     # 模糊：多个候选接近 → 澄清
    INSUFFICIENT = "insufficient"  # 参数不足：启动流程由 collect 步骤追问缺失参数
    LOW = "low"                 # 置信度低：无匹配 → 兜底（闲聊 / 澄清）


class ToolKind(str, Enum):
    FLOW = "flow"
    KNOWLEDGE = "knowledge"
    CHITCHAT = "chitchat"


class ParameterSpec(BaseModel):
    """工具参数 schema：从 flow 配置的 collect 槽位自动生成。"""

    name: str
    type: str = "text"
    required: bool = False
    pattern: str | None = None
    enum: list[str] | None = None
    description: str = ""
    slot: str | None = None  # 对应 flow 配置中的槽位名


class ToolEntry(BaseModel):
    """统一工具定义（阶段七：用工具替代意图）。"""

    name: str
    kind: ToolKind
    description: str
    problem_types: list[ProblemType] = Field(default_factory=list)
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    embed_text: list[str] = Field(default_factory=list)
    tree_text: str | None = None
    executor: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """LLM 输出的单次工具调用。"""

    tool: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolReasoning(BaseModel):
    """LLM 语言理解结果：只包含"涉及哪些工具 + 参数"，不含路由决策。"""

    tool_calls: list[ToolCall] = Field(default_factory=list)


class ToolCandidate(BaseModel):
    """召回/排序阶段携带评分信息的候选工具。"""

    name: str
    kind: ToolKind = ToolKind.FLOW
    parameters: dict[str, Any] = Field(default_factory=dict)
    embedding_score: float = 0.0
    reasoning_score: float = 0.0
    structural_score: float = 0.0  # 参数覆盖率 / 关键词命中强度
    verb_score: float = 0.0
    final_score: float = 0.0
    source: str = ""


class RoutingResult(BaseModel):
    """路由层统一输出，由 RouterService 模板方法产出。"""

    problem_type: ProblemType | None = None
    decision: Decision = Decision.LOW
    selected_tools: list[ToolCandidate] = Field(default_factory=list)
    missing_parameters: list[str] = Field(default_factory=list)
    alternatives: list[ToolCandidate] = Field(default_factory=list)
    cache_hit: bool = False
    channel: str = ""  # cache / rule / keyword / embedding / llm
    skip_llm: bool = False
    cancel_flow: bool = False
    note: str = ""
