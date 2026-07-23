from .models import ActionFn


class ActionRegistry:
    def __init__(self):
        self._actions: dict[str, ActionFn] = {}

    def register(self, name: str, fn: ActionFn = None):
        if fn is not None:
            self._actions[name] = fn
            return fn
        def decorator(f: ActionFn):
            self._actions[name] = f
            return f
        return decorator

    def has(self, name: str) -> bool:
        return name in self._actions

    def get(self, name: str) -> ActionFn | None:
        return self._actions.get(name)
