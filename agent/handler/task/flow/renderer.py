import re
from typing import Any


def _render_template(template_str: str, slots: dict, context: dict) -> str:
    def replacer(match):
        expr = match.group(1).strip()
        if expr.startswith("slots."):
            key = expr.split(".", 1)[1]
            return str(slots.get(key, ""))
        if expr.startswith("context."):
            key = expr.split(".", 1)[1]
            val = context.get(key)
            if isinstance(val, dict):
                return str(val)
            return str(val or "")
        return match.group(0)

    return re.sub(r"\{\{(.*?)\}\}", replacer, template_str)


def _resolve_direct_ref(key: str, slots: dict, context: dict) -> Any:
    if key.startswith("context."):
        return context.get(key.split(".", 1)[1])
    if key.startswith("slots."):
        return slots.get(key.split(".", 1)[1])
    return None


def render_value(value: Any, slots: dict, context: dict) -> Any:
    if isinstance(value, str):
        ref = _resolve_direct_ref(value, slots, context)
        if ref is not None:
            return ref
        return _render_template(value, slots, context)
    if isinstance(value, dict):
        return {k: render_value(v, slots, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, slots, context) for v in value]
    return value


def evaluate_condition(expr: str, slots: dict, context: dict) -> bool:
    expr = expr.strip()
    if expr.startswith("slots.get("):
        key = expr.split("'")[1] if "'" in expr else expr.split('"')[1]
        return key in slots and bool(slots[key])
    if "context.get(" in expr and "==" in expr:
        parts = expr.split("==", 1)
        var_part = parts[0].strip()
        val_part = parts[1].strip().strip("'\"").strip()
        key = var_part.split("'")[1] if "'" in var_part else var_part.split('"')[1]
        return context.get(key) == val_part
    return False
