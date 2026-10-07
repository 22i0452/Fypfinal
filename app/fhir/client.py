from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol


class FHIRClientError(RuntimeError):
    pass


class FHIRClient(Protocol):
    def put(self, resource: dict[str, Any]) -> dict[str, Any]: ...
    def get(self, resource_type: str, resource_id: str) -> dict[str, Any] | None: ...


class MockFHIRClient:
    """In-memory development client; it does not represent a live EHR integration."""

    def __init__(self) -> None:
        self._resources: dict[tuple[str, str], dict[str, Any]] = {}

    def put(self, resource: dict[str, Any]) -> dict[str, Any]:
        resource_type = str(resource.get("resourceType") or "").strip()
        resource_id = str(resource.get("id") or "").strip()
        if not resource_type or not resource_id:
            raise FHIRClientError("FHIR resources require resourceType and id")
        self._resources[(resource_type, resource_id)] = deepcopy(resource)
        return deepcopy(resource)

    def get(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        resource = self._resources.get((str(resource_type), str(resource_id)))
        return deepcopy(resource) if resource else None
