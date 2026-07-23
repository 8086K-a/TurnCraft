import httpx

_client: httpx.AsyncClient | None = None


def init_http_client():
    global _client
    _client = httpx.AsyncClient(timeout=10)


async def close_http_client():
    global _client
    if _client:
        await _client.aclose()
        _client = None


def get_http_client() -> httpx.AsyncClient:
    return _client
