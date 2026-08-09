"""候选召回：策略模式（Strategy）。

- KeywordRecallStrategy：关键词/短语子串召回，快、0 延迟，负责"锚点"。
- EmbeddingRecallStrategy：千问向量语义召回，负责长尾口语。
- HybridRecallStrategy：组合（Composite）两个通道取并集去重。
- CandidateSelector：外观（Facade），对外只暴露 select(text)。
"""
from typing import Protocol

from .models import ToolCandidate, ToolEntry


class RecallStrategy(Protocol):
    async def recall(self, text: str, top_k: int) -> list[ToolCandidate]: ...


class KeywordRecallStrategy:
    """关键词通道：短语子串命中，命中数即强度。"""

    def __init__(self, tools: dict[str, ToolEntry]):
        self._tools = tools
        self._index: dict[str, set[str]] = self._build_index()

    def _build_index(self) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}
        for name, tool in self._tools.items():
            phrases = set(tool.keywords) | set(tool.embed_text)
            phrases.add(name)
            for phrase in phrases:
                phrase = (phrase or "").strip()
                if len(phrase) < 2:
                    continue
                index.setdefault(phrase, set()).add(name)
        return index

    async def recall(self, text: str, top_k: int) -> list[ToolCandidate]:
        text = (text or "").strip()
        if not text:
            return []
        matched: dict[str, int] = {}
        for phrase, names in self._index.items():
            if phrase not in text:
                continue
            for name in names:
                matched[name] = matched.get(name, 0) + 1
        ranked = sorted(matched.items(), key=lambda item: item[1], reverse=True)
        return [
            ToolCandidate(
                name=name,
                kind=self._tools[name].kind,
                structural_score=float(count),
                source="keyword",
            )
            for name, count in ranked[:top_k]
        ]


class EmbeddingRecallStrategy:
    """语义召回通道：封装 EmbeddingRetriever。"""

    def __init__(self, retriever):
        self._retriever = retriever

    async def recall(self, text: str, top_k: int) -> list[ToolCandidate]:
        return await self._retriever.retrieve(text, top_k)


class HybridRecallStrategy:
    """组合：多通道并集，按名称去重合并，取 top_k。"""

    def __init__(self, strategies: list[RecallStrategy]):
        self._strategies = strategies

    async def recall(self, text: str, top_k: int) -> list[ToolCandidate]:
        merged: dict[str, ToolCandidate] = {}
        for strategy in self._strategies:
            for candidate in await strategy.recall(text, top_k):
                current = merged.get(candidate.name)
                if current is None:
                    merged[candidate.name] = candidate
                    continue
                current.embedding_score = max(
                    current.embedding_score, candidate.embedding_score
                )
                current.structural_score = max(
                    current.structural_score, candidate.structural_score
                )
                current.source = "+".join(
                    dict.fromkeys(
                        filter(None, [current.source, candidate.source])
                    )
                )
        ranked = sorted(
            merged.values(),
            key=lambda c: c.embedding_score + c.structural_score,
            reverse=True,
        )
        return ranked[:top_k]


class CandidateSelector:
    """召回外观：屏蔽底层多通道细节。"""

    def __init__(self, strategy: RecallStrategy, top_k: int = 8):
        self._strategy = strategy
        self._top_k = top_k

    async def select(self, text: str) -> list[ToolCandidate]:
        return await self._strategy.recall(text, self._top_k)
