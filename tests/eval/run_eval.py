"""真实评估：用真实 LLM + 千问 embedding 跑 golden set。

用法（在项目根目录）：
    .venv/bin/python -m tests.eval.run_eval

说明：会调用 dashscope（LLM + embedding），产生少量费用。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.domain.dialogue_state import DialogueState
from agent.domain.message import MessageType, UserMessage
from agent.engine.builder import build_router_service
from agent.handler.task.flow import FlowManager
from agent.handler.task.flow.models import FlowsList
from agent.infrastructure.llm import get_llm
from agent.router import ToolRouterPlanner, TurnPlanAdapter
from tests.eval.golden_set import GOLDEN_CASES, judge


async def main():
    flow_manager = FlowManager()
    flow_manager.load_from_dir(str(Path(__file__).resolve().parents[2] / "flow_config"))
    flows_list = FlowsList(flow_manager)
    router_service, registry = build_router_service(get_llm(), flow_manager, flows_list)
    planner = ToolRouterPlanner(router_service, TurnPlanAdapter(registry, flows_list))

    passed = 0
    for case in GOLDEN_CASES:
        state = DialogueState(sender_id="eval")
        plan = await planner.plan(
            state,
            UserMessage(
                sender_id="eval",
                message_id=case["text"],
                type=MessageType.TEXT,
                text=case["text"],
            ),
        )
        ok, detail = judge(plan, case)
        passed += int(ok)
        print(f"{'PASS' if ok else 'FAIL'} | {case['text']!r:24} -> {detail} | {plan.model_dump(mode='json')}")

    total = len(GOLDEN_CASES)
    print(f"\n准确率：{passed}/{total} = {passed / total:.1%}")


if __name__ == "__main__":
    asyncio.run(main())
