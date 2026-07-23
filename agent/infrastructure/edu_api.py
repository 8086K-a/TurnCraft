import httpx

API_BASE = "http://127.0.0.1:8000"


class EduApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 500):
        self.code = code
        self.api_message = message
        self.status = status
        super().__init__(f"[{code}] {message}")


class EduApiClient:
    def __init__(self, base_url: str = API_BASE, timeout: float = 10):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _headers(self, user_id: str | int | None = None) -> dict:
        h = {"Content-Type": "application/json"}
        if user_id is not None:
            h["X-User-Id"] = str(user_id)
        return h

    async def _request(self, method: str, path: str, user_id=None, **kwargs):
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method, url, headers=self._headers(user_id), **kwargs
            )
        resp.raise_for_status()
        body = resp.json()
        code = body.get("code")
        failed = (
            code is not None
            and (
                (isinstance(code, int) and code != 0)
                or (isinstance(code, str) and code != "ok")
            )
        )
        if failed:
            raise EduApiError(
                code=str(code),
                message=body.get("message", "unknown error"),
                status=resp.status_code,
            )
        return body.get("data")

    async def get_me(self, user_id: int | str) -> dict:
        return await self._request("GET", "/api/v1/me", user_id=user_id)

    async def list_orders(self, user_id: int | str, status: str | None = None, page=1, size=20) -> dict:
        params = {"pageNo": page, "pageSize": size}
        if status:
            params["status"] = status
        return await self._request("GET", "/api/v1/orders", user_id=user_id, params=params)

    async def get_order_detail(self, user_id: int | str, order_id: int) -> dict:
        return await self._request("GET", f"/api/v1/orders/{order_id}", user_id=user_id)

    async def find_order_by_no(self, user_id: int | str, order_no: str) -> dict | None:
        data = await self.list_orders(user_id, page=1, size=100)
        for o in data.get("list", []):
            if o.get("orderNo") == order_no:
                return await self.get_order_detail(user_id, o["orderId"])

        total = data.get("total", 0)
        page_size = data.get("pageSize", 20)
        total_pages = (total + page_size - 1) // page_size
        for p in range(2, total_pages + 1):
            data = await self.list_orders(user_id, page=p, size=page_size)
            for o in data.get("list", []):
                if o.get("orderNo") == order_no:
                    return await self.get_order_detail(user_id, o["orderId"])
        return None

    async def list_series(self, keyword: str | None = None, page=1, size=20) -> dict:
        params = {"pageNo": page, "pageSize": size}
        if keyword:
            params["keyword"] = keyword
        return await self._request("GET", "/api/v1/series", params=params)

    async def get_series_detail(self, series_id: int) -> dict:
        return await self._request("GET", f"/api/v1/series/{series_id}")

    async def list_series_cohorts(self, series_id: int) -> list[dict]:
        return await self._request("GET", f"/api/v1/series/{series_id}/cohorts")

    async def list_my_cohorts(self, user_id: int | str, status: str | None = None, page=1, size=20) -> dict:
        params = {"pageNo": page, "pageSize": size}
        if status:
            params["status"] = status
        return await self._request("GET", "/api/v1/me/cohorts", user_id=user_id, params=params)

    async def get_my_cohort_progress(self, user_id: int | str, cohort_id: int) -> dict:
        return await self._request("GET", f"/api/v1/me/cohorts/{cohort_id}/progress", user_id=user_id)

    async def create_refund_request(self, user_id: int | str, order_item_id: int, refund_type: str, reason: str, amount: float) -> dict:
        body = {
            "refundType": refund_type,
            "refundReason": reason,
            "applyAmount": amount,
        }
        return await self._request(
            "POST", f"/api/v1/order-items/{order_item_id}/refund-requests",
            user_id=user_id, json=body,
        )

    async def create_service_ticket(self, user_id: int | str, ticket_type: str, title: str, content: str, student_id: int | None = None, order_item_id: int | None = None) -> dict:
        body = {
            "ticketType": ticket_type,
            "priorityLevel": "medium",
            "ticketSource": "user_app",
            "title": title,
            "ticketContent": content,
        }
        if student_id is not None:
            body["studentId"] = student_id
        if order_item_id is not None:
            body["orderItemId"] = order_item_id
        return await self._request(
            "POST", "/api/v1/service-tickets",
            user_id=user_id, json=body,
        )

    async def get_my_student_profile(self, user_id: int | str) -> dict:
        return await self._request("GET", "/api/v1/me/student-profile", user_id=user_id)
