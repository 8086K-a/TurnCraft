"""ToolReasoner：LLM 只做语言理解（NLU）。

输入：候选工具紧凑描述 + 对话状态；输出：结构化 tool_calls（工具 + 参数）。
不再让 LLM 输出路由/置信度/编排判断——那是代码的职责（文章阶段三的核心改法）。
解析失败时返回空 ToolReasoning，由路由层走 LOW 兜底，保证可用性。
"""
import json
import logging
import re
from typing import Any

from jinja2 import Template

from agent.prompts.prompt_loader import load_prompt

from .models import ToolCall, ToolCandidate, ToolEntry, ToolReasoning

logger = logging.getLogger(__name__)


class ToolReasoner:
    def __init__(self, llm, tools: dict[str, ToolEntry], prompt_name: str = "tool_route"):
        self._llm = llm
        self._tools = tools
        self._template = Template(load_prompt(prompt_name))

    async def reason(
        self,
        *,
        user_message: str,
        candidates: list[ToolCandidate],
        active_task: dict[str, Any] | None = None,
        paused_tasks: list[dict[str, Any]] | None = None,
        focused_object: dict[str, Any] | None = None,
        history: str = "",
    ) -> ToolReasoning:
        prompt = self._template.render(
            tools=self._render_tools(candidates),
            active_task=self._render_active_task(active_task),
            paused_tasks=self._render_paused_tasks(paused_tasks),
            focused_object=self._render_focused_object(focused_object),
            history=(history or "").strip(),
            user_message=(user_message or "").strip(),
        )
        try:
            response = await self._llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            data = json.loads(self._extract_json(content))
        except Exception:
            logger.exception("tool reasoning failed; fallback to LOW decision")
            return ToolReasoning(tool_calls=[])

        allowed = {candidate.name for candidate in candidates}
        calls: list[ToolCall] = []
        for item in data.get("tool_calls") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("tool")
            if name not in allowed:
                continue
            parameters = item.get("parameters") or {}
            if not isinstance(parameters, dict):
                parameters = {}
            calls.append(ToolCall(tool=name, parameters=parameters))
        return ToolReasoning(tool_calls=calls)

    # ---------- prompt 渲染 ----------

    def _render_tools(self, candidates: list[ToolCandidate]) -> str:
        lines = []
        for candidate in candidates:
            tool = self._tools.get(candidate.name)
            params = tool.parameters if tool else {}
            param_text = "、".join(
                f"{name}({spec.type}{',必填' if spec.required else ''})"
                for name, spec in params.items()
            )
            line = f"- {candidate.name}: {tool.description if tool else ''}"
            if candidate.embedding_score > 0:
                line += f" [相似度{candidate.embedding_score:.2f}]"
            lines.append(line)
            if param_text:
                lines.append(f"    参数：{param_text}")
            if tool and tool.tree_text:
                lines.append(f"    提示：{tool.tree_text}")
        return "\n".join(lines) or "- （无）"

    @staticmethod
    def _render_active_task(active_task: dict[str, Any] | None) -> str:
        if not active_task:
            return "无"
        flow = active_task.get("flow_id", "")
        step = active_task.get("step_id", "")
        slots = active_task.get("slots") or {}
        filled = "、".join(f"{k}={v}" for k, v in slots.items()) or "无"
        return f"flow={flow}, step={step}, 已收集槽位={filled}"

    @staticmethod
    def _render_paused_tasks(paused_tasks: list[dict[str, Any]] | None) -> str:
        if not paused_tasks:
            return "无"
        return "、".join(task.get("flow_id", "") for task in paused_tasks)

    @staticmethod
    def _render_focused_object(focused_object: dict[str, Any] | None) -> str:
        if not focused_object:
            return "无"
        return (
            f"type={focused_object.get('type')}, "
            f"id={focused_object.get('id')}, "
            f"title={focused_object.get('title')}"
        )

    @staticmethod
    def _extract_json(content: Any) -> str:
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        text = str(content).strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("LLM did not return a JSON object")
        return text[start : end + 1]
