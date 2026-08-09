"""RouterService：路由管道的外观（Facade）+ 模板方法（Template Method）。

固定管线：缓存 → 代码规则捷径 → 双通道召回 → LLM 语言理解 → 融合排序 →
结构化校验 → 四态判决 → 写缓存。每一步可替换/可插拔。
"""
import logging
from typing import Any

from agent.prompts.history_builder import HistoryBuilder

from .models import Decision, ProblemType, RoutingResult
from .orchestrator import RoutingOrchestrator
from .parameter_validator import ParameterValidator
from .route_cache import RouteCache
from .rule_router import RuleRouter
from .tool_ranker import ToolRanker
from .tool_reasoner import ToolReasoner
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class RouterService:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        selector,
        reasoner: ToolReasoner,
        ranker: ToolRanker,
        validator: ParameterValidator,
        orchestrator: RoutingOrchestrator,
        rules: RuleRouter,
        cache: RouteCache,
        top_k: int = 8,
    ):
        self._registry = registry
        self._selector = selector
        self._reasoner = reasoner
        self._ranker = ranker
        self._validator = validator
        self._orchestrator = orchestrator
        self._rules = rules
        self._cache = cache
        self._top_k = top_k

    # ---------- 模板方法：路由管线 ----------

    async def route(self, state, user_message) -> RoutingResult:
        text = (user_message.text or "").strip()

        cached = self._cache.get(text, state)
        if cached is not None:
            cached.cache_hit = True
            return cached

        shortcut = await self._orchestrator.shortcut_route(state, text)
        if shortcut is not None:
            self._cache.set(text, state, shortcut)
            return shortcut

        candidates = await self._selector.select(text)
        if not candidates:
            result = RoutingResult(
                problem_type=None,
                decision=Decision.LOW,
                channel="recall",
            )
            return result

        # 快路径：唯一候选且无参数 → 无需 LLM（转人工等）
        if len(candidates) == 1:
            tool = self._registry.get(candidates[0].name)
            if tool is not None and not tool.parameters:
                top = candidates[0]
                result = RoutingResult(
                    problem_type=(
                        tool.problem_types[0] if tool.problem_types else None
                    ),
                    decision=Decision.CLEAR,
                    selected_tools=[top],
                    channel="keyword",
                    skip_llm=True,
                )
                self._cache.set(text, state, result)
                return result

        reasoning = await self._reasoner.reason(
            user_message=text,
            candidates=candidates,
            active_task=self._dump(state.active_task),
            paused_tasks=self._dump_list(state.paused_tasks),
            focused_object=self._dump(state.focused_object),
            history=self._history(state),
        )
        problem_type = self._rules.detect_problem_type(text)
        result = self._orchestrator.decide(
            text=text,
            candidates=candidates,
            reasoning=reasoning,
            tools=self._registry.as_dict(),
            problem_type=problem_type,
            ranker=self._ranker,
            validator=self._validator,
        )
        if result.decision in (Decision.CLEAR, Decision.INSUFFICIENT):
            self._cache.set(text, state, result)
        return result

    async def warmup(self) -> None:
        """预热可预热组件（如 embedding 索引），幂等。"""
        selector_strategy = getattr(self._selector, "_strategy", None)
        for strategy in getattr(selector_strategy, "_strategies", []) or []:
            retriever = getattr(strategy, "_retriever", None)
            warmup = getattr(retriever, "warmup", None)
            if warmup is not None:
                await warmup()

    # ---------- 工具 ----------

    @staticmethod
    def _history(state, last_n: int = 8) -> str:
        if not state.current_session_id:
            return ""
        session = next(
            (
                item
                for item in state.sessions
                if item.session_id == state.current_session_id
            ),
            None,
        )
        if not session or not session.turns:
            return ""
        return HistoryBuilder.build(session.turns[-last_n:])

    @staticmethod
    def _dump(value: Any) -> dict | None:
        if value is None:
            return None
        return value.model_dump(mode="json")

    @staticmethod
    def _dump_list(values: list) -> list[dict]:
        return [item.model_dump(mode="json") for item in values]
