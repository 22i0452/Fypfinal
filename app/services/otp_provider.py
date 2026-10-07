from __future__ import annotations

import secrets
from abc import ABC, abstractmethod

from app.config import Settings


class OTPProvider(ABC):
    @abstractmethod
    def generate_code(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def deliver(self, *, normalized_phone: str, code: str, challenge_id: str) -> None:
        raise NotImplementedError


class SMSOTPProvider(OTPProvider):
    """Production extension point; no SMS vendor is configured in this FYP."""

    def generate_code(self) -> str:
        return "".join(secrets.choice("0123456789") for _ in range(6))

    def deliver(self, *, normalized_phone: str, code: str, challenge_id: str) -> None:
        raise RuntimeError("No approved SMS OTP provider is configured")


class MockOTPProvider(OTPProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.mock_otp_enabled:
            raise RuntimeError("Mock OTP provider is disabled")
        self.settings = settings

    def generate_code(self) -> str:
        if self.settings.app_env == "test":
            return self.settings.test_otp_code
        return "".join(secrets.choice("0123456789") for _ in range(6))

    def deliver(self, *, normalized_phone: str, code: str, challenge_id: str) -> None:
        # Development delivery is represented only by the guarded response field.
        return None
