"""ParameterValidator：结构化参数校验（方案B 的参数 schema 校验落地）。

校验 required / type / pattern；返回缺失参数与非法参数。
注意：槽位值（如退款类型的中文说法）不做 enum 硬校验——enum 校验是非阻塞提示，
真正的中文→枚举映射由 action 层负责。
"""
import re
from dataclasses import dataclass, field

from .models import ToolCall, ToolEntry


@dataclass
class ValidationResult:
    missing: list[str] = field(default_factory=list)
    invalid: dict[str, str] = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)


class ParameterValidator:
    def validate(self, call: ToolCall, tool: ToolEntry) -> ValidationResult:
        missing: list[str] = []
        invalid: dict[str, str] = {}
        cleaned: dict = {}
        for name, spec in tool.parameters.items():
            value = call.parameters.get(name)
            if value in (None, ""):
                if spec.required:
                    missing.append(name)
                continue
            cleaned[name] = value
            if spec.type == "text" and not isinstance(value, str):
                invalid[name] = "not_text"
            if spec.pattern and not re.fullmatch(spec.pattern, str(value)):
                invalid[name] = "pattern_mismatch"
            if spec.enum and str(value) not in spec.enum:
                invalid[name] = "not_in_enum"
        return ValidationResult(missing=missing, invalid=invalid, parameters=cleaned)

    def missing_required(self, call: ToolCall, tool: ToolEntry) -> list[str]:
        return self.validate(call, tool).missing
