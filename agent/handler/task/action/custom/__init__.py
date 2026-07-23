import importlib
import pkgutil
import types


def _iter_action_fns():
    for _, module_name, _ in pkgutil.iter_modules(__path__):
        if module_name == "__init__":
            continue
        module = importlib.import_module(f".{module_name}", __package__)
        for name in dir(module):
            obj = getattr(module, name)
            if name.startswith("action_") and isinstance(obj, types.FunctionType):
                if hasattr(obj, "__module__") and obj.__module__ == module.__name__:
                    yield name, obj


def register_custom_actions(registry):
    for name, fn in _iter_action_fns():
        registry.register(name, fn)
