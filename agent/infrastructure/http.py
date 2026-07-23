import httpx


class HttpClient:
    def __init__(self, timeout=10):
        self._client = httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._client.aclose()

    async def get(self, url, **kwargs):
        return await self._client.get(url, **kwargs)




