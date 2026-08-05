from pathlib import Path

from agent.config.config_loader import settings
from agent.engine.dialogue_engine import DialogueEngine
from agent.engine.turn_planner import TurnPlanner
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


def build_dialogue_engine() -> DialogueEngine:
    flow_manager = FlowManager()
    config_dir = Path(__file__).resolve().parents[2] / "flow_config"
    flow_manager.load_from_dir(str(config_dir))

    registry = ActionRegistry()
    registry.register("action_response", action_response)
    registry.register("action_listen", action_listen)
    register_custom_actions(registry)

    llm = get_llm()
    return DialogueEngine(
        task_handler=TaskHandler(flow_manager, ActionExecutor(registry)),
        command_processor=CommandProcessor(),
        flows_list=FlowsList(flow_manager),
        planner=TurnPlanner(llm, flow_manager),
        plan_validator=TurnPlanValidator(flow_manager),
        clarify_responder=ClarifyResponder(llm=llm),
        api=EduApiClient(settings.commerce_api_base_url),
        chitchat_handler=ChitchatHandler(llm),
        knowledge_handler=KnowledgeHandler(llm=llm),
    )
