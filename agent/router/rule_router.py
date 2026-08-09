"""RuleRouter：规则优先的确定性路由（文章阶段二/三的"负向排除"思路）。

规则只处理高确定性的表达，其余交给双通道召回 + LLM 语义理解。
关键点：
- 负向排除：'怎么做'命中 guide，但 '怎么做才能/怎么才能' 排除；
- 不把宽泛的'怎么做'直接判成 GUIDE（避免把经营/策略问题误判）。
"""
import re
from dataclasses import dataclass

from .models import ProblemType

# 闲聊/寒暄（无论是否有活跃任务，都走 chitchat）
GREETING_PATTERNS = [
    re.compile(r"^(你好|您好|嗨|哈喽|hello|hi|hey|在吗|早上好|下午好|晚上好|早安|午安|晚安)"),
    re.compile(r"^(谢谢|多谢|感谢|辛苦了|谢谢啦|谢了)"),
    re.compile(r"^(再见|拜拜|886|下次聊)"),
    re.compile(r"^(哈哈|哈哈哈|嗯嗯|好的|好嘞|ok|OK|Ok|知道了|没事|随便|哦|嗯|行|可以)"),
    re.compile(r"^(你是谁|你能做什么|你会什么|介绍一下你自己|你是什么)"),
]

# 取消当前任务（只有存在活跃任务时生效）
CANCEL_PATTERNS = [
    re.compile(r"^(取消|不办了|算了|不要了|不用了|先算了|撤销|不弄了|不想办了|先不弄了|停一下|先停)"),
    re.compile(r"^取消.*(退款|订单|工单|投诉|任务)"),
]

# GUIDE：如何操作 / 如何申请（回答步骤，不启动流程）
GUIDE_PATTERNS = [
    re.compile(r"(怎么操作|如何操作|怎么弄|怎么办|怎么办理|如何办理|怎么申请|如何申请|在哪里设置|在哪设置|怎么退|如何退|怎么投诉|怎么查|怎么报名|怎么缴费|怎么提交|如何提交|操作步骤|流程是怎样的|步骤是什么)"),
    re.compile(r"^(怎么|如何).*(退款|退|报名|缴费|投诉|查订单|查进度|申请|开通|学习)"),
]

# 负向排除：这些表达不是 GUIDE（经营/策略/效率类）
GUIDE_NEGATIVE_PATTERNS = [
    re.compile(r"(怎么做能|怎么做才能|怎么才能|怎么办更好|如何提升|怎么提升|怎么提高|怎么改进|怎么优化|怎么才能更快|怎么才能更)"),
]

# 新意图信号：活跃任务处于 collect 步骤时，用于区分"补充槽位值" vs "发起新需求"
NEW_INTENT_PATTERNS = [
    re.compile(r"^(帮我|请帮我|给我|麻烦|帮我查|帮我退|帮我申请|帮我提交|帮我转|我要|我想|我要查|我要退|我要申请|我要投诉|我要咨询|我要了解|我想查|我想退|我想申请|我想投诉|我想咨询|我想了解|查一下|查查|查询|咨询下|咨询一下|了解一下|了解下|申请|投诉|退款|取消|继续|转人工|订|预约)"),
    re.compile(r"(转人工|人工客服|人工|多少钱|怎么退|怎么查|怎么报|怎么学|怎么申请|怎么缴费|我要|我想|帮我|退款|投诉|申请|查订单|查一下|查询|订)"),
]


@dataclass
class RuleMatch:
    problem_type: ProblemType | None = None
    confidence: float = 0.0


class RuleRouter:
    """规则路由：输入文本 → 高确定性问题类型（或 None）。"""

    def detect_problem_type(self, text: str) -> ProblemType | None:
        text = (text or "").strip()
        if not text:
            return ProblemType.CHAT
        # 纯寒暄才走 chitchat；"你好，我要退款" 这类带明确诉求的不算闲聊
        if self._matches_any(text, GREETING_PATTERNS) and not self.is_new_intent(text):
            return ProblemType.CHAT
        if self._matches_any(text, GUIDE_NEGATIVE_PATTERNS):
            return None
        if self._matches_any(text, GUIDE_PATTERNS):
            return ProblemType.GUIDE
        return None

    def is_cancel(self, text: str) -> bool:
        return self._matches_any(text, CANCEL_PATTERNS)

    def is_new_intent(self, text: str) -> bool:
        """活跃任务收集槽位时：true 表示用户发起了新需求，false 表示在补充槽位值。"""
        return self._matches_any(text, NEW_INTENT_PATTERNS)

    @staticmethod
    def _matches_any(text: str, patterns: list[re.Pattern]) -> bool:
        return any(p.search(text) for p in patterns)
