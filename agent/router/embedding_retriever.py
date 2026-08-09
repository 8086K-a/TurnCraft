"""EmbeddingRetriever：千问（DashScope compatible-mode）文本向量召回通道。

- 使用 OpenAI 兼容端点 /embeddings，模型 text-embedding-v4（1024 维）。
- 懒加载：首次 retrieve 时异步构建工具索引，避免启动时阻塞。
- 优雅降级：任何网络/解析异常都返回空候选，由关键词通道兜底。
"""
import asyncio
import logging
import math

import httpx

from .models import ToolCandidate, ToolEntry, ToolKind

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"


class EmbeddingRetriever:
    # DashScope 兼容模式 embedding 单次请求 batch 上限
    DEFAULT_BATCH_SIZE = 10

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = "text-embedding-v4",
        enabled: bool = True,
        timeout: float = 10.0,
        top_k: int = 6,
        batch_size: int = 10,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._enabled = enabled
        self._timeout = timeout
        self._top_k = top_k
        self._batch_size = max(1, min(batch_size, self.DEFAULT_BATCH_SIZE))
        self._tools: dict[str, ToolEntry] = {}
        self._index: dict[str, list[list[float]]] | None = None
        self._lock = asyncio.Lock()

    # ---------- 配置 ----------

    def set_tools(self, tools: dict[str, ToolEntry] | list[ToolEntry]) -> None:
        if isinstance(tools, list):
            tools = {t.name: t for t in tools}
        self._tools = tools
        self._index = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def warmup(self) -> None:
        """预构建工具向量索引（幂等；部署时可在应用启动后调用）。"""
        try:
            await self._ensure_index()
        except Exception:
            logger.exception("embedding warmup failed; lazy fallback remains active")

    # ---------- 召回 ----------

    async def retrieve(self, text: str, top_k: int | None = None) -> list[ToolCandidate]:
        """返回带 embedding_score 的候选工具（降序），失败时返回空列表。"""
        if not self._enabled or not self._tools or not (text or "").strip():
            return []
        try:
            await self._ensure_index()
            if not self._index:
                return []
            query_vector = (await self._embed([text]))[0]
            scores: dict[str, float] = {}
            for name, vectors in self._index.items():
                scores[name] = max(self._cosine(query_vector, v) for v in vectors)
            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            limit = top_k or self._top_k
            return [
                ToolCandidate(
                    name=name,
                    kind=self._tools[name].kind,
                    embedding_score=round(score, 6),
                    source="embedding",
                )
                for name, score in ranked[:limit]
                if score > 0
            ]
        except Exception:
            logger.exception("embedding retrieval failed; fallback to keyword channel")
            return []

    # ---------- 内部 ----------

    async def _ensure_index(self) -> None:
        if self._index is not None:
            return
        async with self._lock:
            if self._index is not None:
                return
            self._index = await self._build_index()

    async def _build_index(self) -> dict[str, list[list[float]]]:
        seeds: list[tuple[str, str]] = []
        for tool in self._tools.values():
            texts = tool.embed_text or ([tool.description] if tool.description else [])
            for seed in texts:
                if seed:
                    seeds.append((tool.name, seed))
        if not seeds:
            return {}
        vectors = await self._embed([seed for _, seed in seeds])
        index: dict[str, list[list[float]]] = {}
        for (name, _), vector in zip(seeds, vectors):
            index.setdefault(name, []).append(vector)
        return index

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """分批调用（DashScope batch 上限 10），保持输入顺序返回。"""
        embeddings: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                response = await client.post(
                    self._base_url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self._model, "input": batch},
                )
                response.raise_for_status()
                data = response.json()
                items = sorted(data["data"], key=lambda item: item.get("index", 0))
                embeddings.extend(item["embedding"] for item in items)
        return embeddings

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
