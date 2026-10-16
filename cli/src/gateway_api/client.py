import json
from collections.abc import Iterator
from typing import Any

from httpx import BaseTransport, Client, Timeout

from src.gateway_api.exceptions import GatewayAPIError


class GatewayAPIClient:
    """The CLI talks only to the backend gateway; identity travels in the X-User-Id header."""

    def __init__(self, base_url: str, user_id: str, transport: BaseTransport | None = None) -> None:
        self._client = Client(
            base_url=base_url,
            headers={"X-User-Id": user_id},
            timeout=Timeout(600.0, connect=5.0),
            transport=transport
        )

    def stream_chat(self, body: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Yields the NDJSON chunks of one turn. Raises ``GatewayAPIError`` on a non-200 response."""
        with self._client.stream("POST", "/api/chat/stream", json=body) as response:
            if response.status_code != 200:
                response.read()
                raise GatewayAPIError(response.status_code, self._detail(response.text))
            for line in response.iter_lines():
                if line.strip():
                    yield json.loads(line)

    def get_conversations(self) -> list[dict[str, Any]]:
        return self._get("/api/conversations")["conversations"]

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return self._get(f"/api/conversations/{conversation_id}/messages")["messages"]

    def get_artifacts(self) -> list[dict[str, Any]]:
        return self._get("/api/artifacts")["artifacts"]

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        return self._get(f"/api/artifacts/{artifact_id}")

    def _get(self, path: str) -> dict[str, Any]:
        response = self._client.get(path)
        if response.status_code != 200:
            raise GatewayAPIError(response.status_code, self._detail(response.text))
        return response.json()

    def post_feedback(self, conversation_id: str, turn_id: str, rating: str, comment: str | None) -> None:
        body: dict[str, Any] = {"conversationId": conversation_id, "turnId": turn_id, "rating": rating}
        if comment:
            body["comment"] = comment
        response = self._client.post("/api/feedbacks", json=body)
        if response.status_code != 204:
            raise GatewayAPIError(response.status_code, self._detail(response.text))

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _detail(text: str) -> str:
        try:
            detail = json.loads(text).get("detail")
        except (ValueError, AttributeError):
            return text[:200]
        if isinstance(detail, list):  # FastAPI validation errors
            return "; ".join(str(item.get("msg", item)) for item in detail)
        return str(detail)
