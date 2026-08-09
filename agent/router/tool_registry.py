"""ToolRegistry：从 flow_config + 知识库自动生成统一工具注册表。

工厂模式：工具定义由配置驱动自动构建，新增流程 = 改 YAML，工具自动出现；
注解文件（tool_annotations.yml）负责补充关键词 / embedding 种子 / 区分提示，
避免与 flow 配置双份维护导致的漂移。
"""
from pathlib import Path
from typing import Any

import yaml

from agent.handler.knowledge import KNOWLEDGE_INTENTS
from agent.handler.task.flow import FlowManager

from .models import ParameterSpec, ProblemType, ToolEntry, ToolKind

# 系统触发的欢迎流程不作为用户可见工具
EXCLUDED_FLOWS = {"onboarding"}

# 知识工具命名（保持 ASCII，executor 里记录原始中文 intent）
KNOWLEDGE_SLUGS = {
    "课程咨询": "kb_course",
    "报名流程": "kb_enrollment",
    "退款政策": "kb_refund_policy",
    "学习方式": "kb_learning_style",
}

# 知识工具描述：帮助 LLM 区分"静态知识问答" vs "具体业务流程"
KNOWLEDGE_DESCRIPTIONS = {
    "课程咨询": "回答课程体系的静态介绍（编程/数据分析/人工智能等方向与课程层次）。注意：用户要查某个具体课程的价格、班次、详情时应使用 course_consultation 流程。",
    "报名流程": "回答报名、缴费、开通学习账号的流程步骤。",
    "退款政策": "回答退款政策与规则（如开课 7 天内无理由退款、30 天内按比例等）。注意：用户明确要执行退款时应使用 refund_request 流程。",
    "学习方式": "回答学习方式（直播互动/录播回放/在线作业/模拟考试）。",
}

# 流程 → 问题类型
FLOW_PROBLEM_TYPES = {
    "order_status_query": [ProblemType.QUERY],
    "refund_request": [ProblemType.ACTION],
    "ticket_submission": [ProblemType.ACTION],
    "course_consultation": [ProblemType.QUERY],
    "learning_progress_query": [ProblemType.QUERY],
    "human_handoff": [ProblemType.ACTION],
}

DEFAULT_ANNOTATIONS_PATH = Path(__file__).resolve().parent / "tool_annotations.yml"


class ToolRegistry:
    def __init__(self, flow_manager: FlowManager, annotations_path: Path | str | None = None):
        self._fm = flow_manager
        self._annotations = self._load_annotations(annotations_path)
        self._tools: dict[str, ToolEntry] = {}
        self._build()

    # ---------- 构建 ----------

    @staticmethod
    def _load_annotations(path: Path | str | None) -> dict[str, Any]:
        if path is None:
            path = DEFAULT_ANNOTATIONS_PATH
        path = Path(path)
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("tools", {}) or {}

    def _build(self) -> None:
        slot_defs = self._fm.get_slot_definitions()
        for flow_id in self._fm.get_all_user_flow_ids():
            if flow_id in EXCLUDED_FLOWS:
                continue
            self._tools[flow_id] = self._build_flow_tool(flow_id, slot_defs)

        for intent in KNOWLEDGE_INTENTS:
            name = KNOWLEDGE_SLUGS.get(intent, f"kb_{intent}")
            self._tools[name] = self._build_knowledge_tool(name, intent)

        self._tools["chitchat"] = self._build_chitchat_tool()
        self._apply_annotations()

    def _build_flow_tool(self, flow_id: str, slot_defs: dict[str, dict]) -> ToolEntry:
        flow = self._fm.get_flow(flow_id) or {}
        name = flow.get("name", flow_id)
        description = flow.get("description", "")
        params: dict[str, ParameterSpec] = {}
        for step in flow.get("steps", []):
            if step.get("type") != "collect":
                continue
            slot = step.get("slot_name")
            if not slot or slot in params:
                continue
            definition = slot_defs.get(slot, {})
            params[slot] = ParameterSpec(
                name=slot,
                type="text",
                required=True,
                description=definition.get("description", ""),
                slot=slot,
            )
        return ToolEntry(
            name=flow_id,
            kind=ToolKind.FLOW,
            description=description,
            problem_types=FLOW_PROBLEM_TYPES.get(flow_id, [ProblemType.QUERY]),
            parameters=params,
            executor={"flow": flow_id},
            keywords=[name, description[:12]] if description else [name],
            embed_text=[name, description] if description else [name],
        )

    def _build_knowledge_tool(self, name: str, intent: str) -> ToolEntry:
        return ToolEntry(
            name=name,
            kind=ToolKind.KNOWLEDGE,
            description=KNOWLEDGE_DESCRIPTIONS.get(intent, f"回答知识库问题：{intent}"),
            problem_types=[ProblemType.QUERY, ProblemType.GUIDE],
            parameters={},
            executor={"intent": intent},
            keywords=[intent],
            embed_text=[intent],
        )

    @staticmethod
    def _build_chitchat_tool() -> ToolEntry:
        return ToolEntry(
            name="chitchat",
            kind=ToolKind.CHITCHAT,
            description="闲聊、打招呼、与业务无关的对话",
            problem_types=[ProblemType.CHAT],
            parameters={},
            executor={"kind": "chitchat"},
            keywords=["你好", "在吗", "谢谢"],
            embed_text=["你好呀", "在吗"],
        )

    def _apply_annotations(self) -> None:
        for name, annotation in self._annotations.items():
            tool = self._tools.get(name)
            if tool is None:
                continue
            if annotation.get("keywords"):
                tool.keywords = list(annotation["keywords"])
            if annotation.get("embed_text"):
                tool.embed_text = list(annotation["embed_text"])
            if annotation.get("tree_text"):
                tool.tree_text = annotation["tree_text"]

    # ---------- 查询 ----------

    def get(self, name: str) -> ToolEntry | None:
        return self._tools.get(name)

    def all(self) -> list[ToolEntry]:
        return list(self._tools.values())

    def as_dict(self) -> dict[str, ToolEntry]:
        return dict(self._tools)

    def flow_tools(self) -> list[ToolEntry]:
        return [t for t in self._tools.values() if t.kind == ToolKind.FLOW]

    def knowledge_tools(self) -> list[ToolEntry]:
        return [t for t in self._tools.values() if t.kind == ToolKind.KNOWLEDGE]

    def has(self, name: str) -> bool:
        return name in self._tools
