"""RouteCache：路由结果缓存（LRU）。

按"归一化文本 + 对话状态指纹"做 key：
- 同一句话在不同状态（有无活跃任务/暂停任务/焦点对象）下结果不同，必须区分；
- 无状态（全新会话）时直接命中缓存，跳过 LLM 实现秒回。
"""
import re
from collections import OrderedDict
from typing import Any

from .models import RoutingResult


def state_fingerprint(state: Any) -> str:
    active = state.active_task
    active_part = ""
    if active is not None:
        active_part = f"{active.flow_id}:{active.step_id or ''}"
    paused = ",".join(sorted(task.flow_id for task in state.paused_tasks))
    focused = state.focused_object
    focused_part = f"{focused.type}:{focused.id}" if focused is not None else ""
    return f"{active_part}|{paused}|{focused_part}"


class RouteCache:
    def __init__(self, maxsize: int = 512):
        self._maxsize = maxsize
        self._data: OrderedDict[str, RoutingResult] = OrderedDict()

    def get(self, text: str, state: Any) -> RoutingResult | None:
        key = self._key(text, state)
        result = self._data.get(key)
        if result is None:
            return None
        self._data.move_to_end(key)
        return result.model_copy(deep=True)

    def set(self, text: str, state: Any, result: RoutingResult) -> None:
        key = self._key(text, state)
        self._data[key] = result.model_copy(deep=True)
        self._data.move_to_end(key)
        while len(self._data) > self._maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    @staticmethod
    def _key(text: str, state: Any) -> str:
        normalized = re.sub(r"\s+", "", text or "").strip().lower()
        return f"{normalized}::{state_fingerprint(state)}"

    def __len__(self) -> int:
        return len(self._data)
