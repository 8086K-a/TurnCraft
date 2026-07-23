from typing import Awaitable

from .models import ActionResult
from .registry import ActionRegistry


class ActionExecutor:
    def __init__(self, registry: ActionRegistry):
        self._registry = registry

    def has(self, name: str) -> bool:
        return self._registry.has(name)

    async def execute(
        self, name: str, args: dict | None, slots: dict, context: dict, **kwargs
    ) -> ActionResult:
        fn = self._registry.get(name)
        if not fn:
            raise ValueError(f"Unknown action: {name}")
        result = fn(args=args or {}, slots=slots, context=context, **kwargs)
        if isinstance(result, Awaitable):
            result = await result
        return result
