from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class ReceptionistAPIError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 0) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class ReceptionistAPIClient:
    """Small authenticated client for the canonical MedFlowAI server."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        service_token: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("MEDFLOW_API_BASE_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        app_env = os.getenv("APP_ENV", os.getenv("MEDFLOW_ENV", "development")).strip().lower()
        default_token = "medflow-development-receptionist-token" if app_env == "development" else ""
        self.service_token = (
            service_token
            if service_token is not None
            else os.getenv("MEDFLOW_RECEPTIONIST_SERVICE_TOKEN", default_token)
        ).strip()
        self.timeout_seconds = timeout_seconds
        if not self.service_token:
            raise ReceptionistAPIError(
                "SERVICE_TOKEN_MISSING",
                "Receptionist service token is not configured",
            )

    def configuration(self) -> dict:
        return self._request("GET", "/api/receptionist/configuration")

    def create_intake(self, payload: dict) -> dict:
        result = self._request("POST", "/api/receptionist/intakes", payload)
        if result.get("requires_update"):
            return self.update_intake(result["patient_id"], {
                **payload, "workflow_id": result["workflow_id"],
                "expected_revision": result["revision"],
            })
        return result

    def update_intake(self, patient_id: str, payload: dict) -> dict:
        return self._request("PATCH", f"/api/receptionist/intakes/{patient_id}", payload)

    def availability(
        self,
        *,
        practitioner_id: str,
        visit_type_id: str,
        days: int = 14,
        limit: int = 12,
    ) -> dict:
        query = urlencode(
            {
                "practitioner_id": practitioner_id,
                "visit_type_id": visit_type_id,
                "days": days,
                "limit": limit,
            }
        )
        return self._request("GET", f"/api/receptionist/availability?{query}")

    def book(self, payload: dict) -> dict:
        return self._request("POST", "/api/receptionist/bookings", payload)

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        encoded = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        )
        request = Request(
            f"{self.base_url}{path}",
            data=encoded,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-MedFlow-Receptionist-Token": self.service_token,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                response_payload = json.loads(body)
            except json.JSONDecodeError:
                response_payload = {}
            detail = response_payload.get("detail", {})
            if isinstance(detail, dict):
                code = str(detail.get("code") or "REQUEST_REJECTED")
                message = str(detail.get("message") or "Receptionist request was rejected")
            elif isinstance(detail, str):
                code = "REQUEST_REJECTED"
                message = str(detail or "Receptionist request was rejected")
            else:
                code = "REQUEST_REJECTED"
                message = "Receptionist request was rejected"
            raise ReceptionistAPIError(code, message, status_code=exc.code) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise ReceptionistAPIError(
                "SERVER_UNAVAILABLE",
                "MedFlowAI server is unavailable; start the FastAPI server and try again",
            ) from None
