"""依赖装配：工厂模式（Factory）。

build_dialogue_engine 装配整个引擎；build_router_service 装配新的分层工具路由
（召回 → LLM 理解 → 排序 → 校验 → 判决），并把 RoutingResult 适配回旧 TurnPlan，
因此 FlowEngine / CommandProcessor / 各 Handler 完全复用。
"""
from pathlib import Path

from agent.config.config_loader import settings
from agent.engine.dialogue_engine import DialogueEngine
from agent.engine.turn_plan_validator import TurnPlanValidator
from agent.handler.task import ActionExecutor, ActionRegistry, FlowManager, TaskHandler
from agent.handler.task.action.builtin import action_listen, action_response
from agent.handler.task.action.custom import register_custom_actions
from agent.handler.task.command.processor import CommandProcessor
from agent.handler.task.flow.models import FlowsList
from agent.handler.chitchat import ChitchatHandler
from agent.handler.clarify import ClarifyResponder
from agent.handler.knowledge import KnowledgeHandler
from agent.infrastructure.edu_api import EduApiClient
from agent.infrastructure.llm import get_llm
from agent.router import (
    CandidateSelector,
    EmbeddingRecallStrategy,
    EmbeddingRetriever,
    HybridRecallStrategy,
    KeywordRecallStrategy,
    ParameterValidator,
    RouteCache,
    RouterService,
    RuleRouter,
    RoutingOrchestrator,
    ToolRanker,
    ToolReasoner,
    ToolRegistry,
    ToolRouterPlanner,
    TurnPlanAdapter,
)


def build_router_service(llm, flow_manager: FlowManager, flows_list: FlowsList):
    """工厂：装配分层工具路由，返回 (RouterService, ToolRegistry)。"""
    registry = ToolRegistry(flow_manager)

    embedding = EmbeddingRetriever(
        api_key=settings.llm_api_key,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        enabled=settings.embedding_enabled,
        timeout=settings.embedding_timeout,
    )
    embedding.set_tools(registry.as_dict())

    selector = CandidateSelector(
        HybridRecallStrategy(
            [
                KeywordRecallStrategy(registry.as_dict()),
                EmbeddingRecallStrategy(embedding),
            ]
        ),
        top_k=settings.router_top_k,
    )
    reasoner = ToolReasoner(llm, tools=registry.as_dict())
    ranker = ToolRanker()
    validator = ParameterValidator()
    rules = RuleRouter()
    orchestrator = RoutingOrchestrator(
        registry,
        rules,
        flows_list,
        low_threshold=settings.router_low_threshold,
        ambiguity_delta=settings.router_ambiguity_delta,
    )
    router_service = RouterService(
        registry=registry,
        selector=selector,
        reasoner=reasoner,
        ranker=ranker,
        validator=validator,
        orchestrator=orchestrator,
        rules=rules,
        cache=RouteCache(maxsize=settings.router_cache_size),
        top_k=settings.router_top_k,
    )
    return router_service, registry


def build_dialogue_engine() -> DialogueEngine:
    flow_manager = FlowManager()
    config_dir = Path(__file__).resolve().parents[2] / "flow_config"
    flow_manager.load_from_dir(str(config_dir))
    flows_list = FlowsList(flow_manager)

    action_registry = ActionRegistry()
    action_registry.register("action_response", action_response)
    action_registry.register("action_listen", action_listen)
    register_custom_actions(action_registry)

    llm = get_llm()
    router_service, tool_registry = build_router_service(llm, flow_manager, flows_list)
    planner = ToolRouterPlanner(
        router_service,
        TurnPlanAdapter(tool_registry, flows_list),
    )
    return DialogueEngine(
        task_handler=TaskHandler(flow_manager, ActionExecutor(action_registry)),
        command_processor=CommandProcessor(),
        flows_list=flows_list,
        planner=planner,
        plan_validator=TurnPlanValidator(flow_manager),
        clarify_responder=ClarifyResponder(llm=llm),
        api=EduApiClient(settings.commerce_api_base_url),
        chitchat_handler=ChitchatHandler(llm),
        knowledge_handler=KnowledgeHandler(llm=llm),
    )
