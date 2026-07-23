"""
End-to-end test for the task pipeline via HTTP API.
  CommandProcessor -> TaskHandler -> ActionExecutor -> EduApiClient

Usage:
  python test_full_pipeline.py
"""

# This is a manually invoked integration script and performs business writes.
__test__ = False

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.handler.task import (
    FlowManager,
    ActionRegistry,
    ActionExecutor,
    TaskHandler,
)
from agent.handler.task.action.builtin import action_response, action_listen
from agent.handler.task.action.custom import register_custom_actions
from agent.handler.task.command.models import Command
from agent.handler.task.command.processor import CommandProcessor
from agent.handler.task.flow.models import FlowsList
from agent.domain.dialogue_state import DialogueState
from agent.infrastructure.edu_api import EduApiClient

OK = "\u2713"
FAIL = "\u2717"
results = []

USER_ID = "56493"  # user with order ORD0000000001

api = EduApiClient()


def check(name, passed, detail=""):
    status = OK if passed else FAIL
    msg = f"  {status} {name}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    results.append(passed)


fm = FlowManager()
fm.load_from_dir("flow_config")

ar = ActionRegistry()
ar.register("action_response", action_response)
ar.register("action_listen", action_listen)
register_custom_actions(ar)
ae = ActionExecutor(ar)

handler = TaskHandler(fm, ae)
cp = CommandProcessor()
flows_list = FlowsList(fm)


def make_state(sender_id=USER_ID):
    return DialogueState(sender_id=sender_id)


def system_context_to_dict(ctx):
    return ctx.model_dump(exclude={"step_id", "flow_id"})


async def step_user_flow(state):
    if not state.active_task:
        return [], False
    messages = []
    task = state.active_task
    completed = False
    while True:
        result = await handler.step(
            task.flow_id,
            task.step_id,
            task.slots,
            context={"user_id": state.sender_id},
            api=api,
        )
        if result.messages:
            messages.extend(result.messages)
        if result.slots_updated:
            task.slots.update(result.slots_updated)
        if result.end_flow:
            completed = True
            break
        if result.need_listen and not result.next_step_id:
            break
        if result.next_step_id:
            task.step_id = result.next_step_id
        else:
            break
    return messages, completed


async def step_system_flow(state):
    if not state.active_system_flow:
        return []
    sysctx = state.active_system_flow
    ctx = system_context_to_dict(sysctx)
    messages = []
    while True:
        result = await handler.step(
            sysctx.flow_id,
            sysctx.step_id,
            slots={},
            context=ctx,
        )
        if result.messages:
            messages.extend(result.messages)
        if result.end_flow:
            break
        if result.next_step_id:
            sysctx.step_id = result.next_step_id
        else:
            break
    state.end_system_flow()
    return messages


async def process_turn(state, commands):
    cp.run(commands, state, flows_list)
    messages = []
    messages.extend(await step_system_flow(state))
    user_msgs, completed = await step_user_flow(state)
    messages.extend(user_msgs)
    return messages, completed


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_onboarding():
    print("\n[onboarding]")
    state = make_state()
    msgs, completed = await process_turn(state, [
        Command.from_dict({"command": "start_flow", "flow": "onboarding"}),
    ])
    resp = " ".join(m["content"] for m in msgs if m.get("content"))
    check("system greeting rendered", "教育智能助手" in resp, resp[:60])
    check("flow completed", completed)
    check("system flow cleared", state.active_system_flow is None)


async def test_order_status_query():
    print("\n[order_status_query]")
    state = make_state()
    msgs, completed = await process_turn(state, [
        Command.from_dict({"command": "start_flow", "flow": "order_status_query"}),
        Command.from_dict({"command": "set_slots", "slots": {"order_number": "ORD0000000001"}}),
    ])
    resp = " ".join(m["content"] for m in msgs if m.get("content"))
    check("order info returned", "待支付" in resp, resp[:80])
    check("order number in response", "ORD0000000001" in resp)
    check("flow completed", completed)


async def test_course_consultation():
    print("\n[course_consultation]")
    state = make_state()
    msgs, completed = await process_turn(state, [
        Command.from_dict({"command": "start_flow", "flow": "course_consultation"}),
        Command.from_dict({"command": "set_slots", "slots": {"course_name": "编程"}}),
    ])
    resp = " ".join(m["content"] for m in msgs if m.get("content"))
    check("course info returned", "编程" in resp, resp[:80])
    check("flow completed", completed)


async def test_refund_request():
    print("\n[refund_request]")
    state = make_state()
    msgs, completed = await process_turn(state, [
        Command.from_dict({"command": "start_flow", "flow": "refund_request"}),
        Command.from_dict({"command": "set_slots", "slots": {
            "order_number": "ORD0000000001",
            "refund_reason": "课程内容与描述不符",
            "refund_type": "course_unsatisfied",
        }}),
    ])
    resp = " ".join(m["content"] for m in msgs if m.get("content"))
    check("refund confirmed", "提交" in resp or "退款" in resp, resp[:80])
    check("flow completed", completed)


async def test_ticket_submission():
    print("\n[ticket_submission]")
    state = make_state()
    msgs, completed = await process_turn(state, [
        Command.from_dict({"command": "start_flow", "flow": "ticket_submission"}),
        Command.from_dict({"command": "set_slots", "slots": {
            "ticket_type": "投诉",
            "order_number": "ORD0000000001",
            "ticket_description": "测试工单-视频无法播放",
        }}),
    ])
    resp = " ".join(m["content"] for m in msgs if m.get("content"))
    check("ticket confirmed", "提交" in resp or "工单" in resp, resp[:80])
    check("flow completed", completed)


async def test_cancel_flow():
    print("\n[cancel_flow]")
    state = make_state()
    msgs1, completed1 = await process_turn(state, [
        Command.from_dict({"command": "start_flow", "flow": "order_status_query"}),
        Command.from_dict({"command": "set_slots", "slots": {"order_number": "ORD0000000001"}}),
    ])
    check("first flow completes", completed1)

    msgs2, completed2 = await process_turn(state, [
        Command.from_dict({"command": "start_flow", "flow": "refund_request"}),
        Command.from_dict({"command": "cancel_flow"}),
    ])
    text2 = " ".join(m["content"] for m in msgs2 if m.get("content"))
    check("cancel acknowledged", "取消" in text2, text2[:60])
    check("no active task after cancel", state.active_task is None)


async def test_interrupt_and_resume():
    print("\n[interrupt_and_resume]")
    state = make_state()

    msgs1, completed1 = await process_turn(state, [
        Command.from_dict({"command": "start_flow", "flow": "order_status_query"}),
        Command.from_dict({"command": "set_slots", "slots": {"order_number": "ORD0000000001"}}),
    ])
    check("flow A completes", completed1)

    msgs2, completed2 = await process_turn(state, [
        Command.from_dict({"command": "start_flow", "flow": "refund_request"}),
        Command.from_dict({"command": "set_slots", "slots": {
            "order_number": "ORD0000000001",
            "refund_reason": "测试中断恢复",
            "refund_type": "personal_reason",
        }}),
    ])

    msgs3, completed3 = await process_turn(state, [
        Command.from_dict({"command": "resume_flow", "flow": "order_status_query"}),
    ])
    text3 = " ".join(m["content"] for m in msgs3 if m.get("content"))
    check("resume via interruption msg", "放一放" in text3, text3[:60])
    check("resumed task is active",
          state.active_task is not None and state.active_task.flow_id == "order_status_query")


async def main():
    print("=" * 60)
    print("Task Pipeline E2E Test (API mode)")
    print("=" * 60)

    tests = [
        test_health_check,
        test_onboarding,
        test_order_status_query,
        test_course_consultation,
        test_refund_request,
        test_ticket_submission,
        test_cancel_flow,
        test_interrupt_and_resume,
    ]

    for test_fn in tests:
        try:
            await test_fn()
        except Exception as e:
            import traceback
            print(f"  {FAIL} {test_fn.__name__} CRASHED: {e}")
            traceback.print_exc()
            results.append(False)

    print()
    print("=" * 60)
    total = len(results)
    passed = sum(results)
    print(f"Result: {passed}/{total} passed")
    if passed < total:
        print(f"Failed: {[i for i, r in enumerate(results) if not r]}")
        sys.exit(1)
    else:
        print("ALL PASSED")


async def test_health_check():
    print("\n[health_check]")
    try:
        from agent.infrastructure.edu_api import EduApiClient
        c = EduApiClient()
        resp = await c._request("GET", "/health")
        check("API server reachable", True)
    except Exception as e:
        check(f"API server unreachable: {e}", False)


if __name__ == "__main__":
    asyncio.run(main())
