from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from .audit import audit_event
from .telemetry import provider_event
from .authz import Actor, AuthorizationError, require_authorized
from .phi import contains_phi, minimize_payload
from .provider_adapters import (
    GroqProviderAdapter,
    MockProviderAdapter,
    OpenAIProviderAdapter,
    OpenRouterProviderAdapter,
    ProviderAdapterError,
)


class GatewaySecurityError(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskPolicy:
    action: str
    allowed: dict[str, set[str]]
    minimize_text: bool = True
    json_required: bool = False
    raw_audio: bool = False


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip().strip('"').strip("'")


def _has_openrouter() -> bool:
    return bool(_env("OPENROUTER_API_KEY"))


def _policies() -> dict[str, TaskPolicy]:
    # Default to a currently available Groq chat model; override via .env.
    groq_llm = _env("GROQ_LLM_MODEL", "qwen/qwen3.8-27b")
    groq_diar = _env("GROQ_DIARIZATION_MODEL", groq_llm)
    openai_llm = _env("OPENAI_LLM_MODEL", "gpt-4o-mini")
    openai_diar = _env("OPENAI_DIARIZATION_MODEL", openai_llm)
    openrouter_llm = _env("OPENROUTER_LLM_MODEL", "openai/gpt-4o-mini")
    groq_stt = _env("GROQ_STT_MODEL", "whisper-large-v3")
    # Prefer full Whisper for consultation accuracy; turbo remains allowlisted as fallback.
    module2_stt = _env("MODULE2_GROQ_STT_MODEL", "whisper-large-v3")
    openai_stt = _env("OPENAI_STT_MODEL", "whisper-1")
    openrouter_stt = _env("MODULE2_OPENROUTER_STT_MODEL", "openai/gpt-4o-transcribe")
    openrouter_whisper = _env("MODULE2_OPENROUTER_WHISPER_MODEL", "openai/whisper-large-v3")

    openai_chat = {
        "openrouter": {openrouter_llm, "openai/gpt-4o-mini", "openai/gpt-4o"},
        "openai": {openai_llm, openai_diar},
        "groq": {groq_llm, groq_diar},
        "mock": {"mock-chat"},
    }
    groq_chat = {
        "groq": {groq_llm, groq_diar},
        "openrouter": {openrouter_llm, "openai/gpt-4o-mini"},
        "openai": {openai_llm, openai_diar},
        "mock": {"mock-chat"},
    }
    return {
        "llm_receptionist": TaskPolicy("llm_receptionist", groq_chat),
        "intake_intent": TaskPolicy("llm_receptionist", groq_chat, json_required=True),
        "intake_extract": TaskPolicy("intake_extract", groq_chat, json_required=True),
        "intake_translate": TaskPolicy("intake_translate", groq_chat, json_required=True),
        "diarization": TaskPolicy("diarize", openai_chat, json_required=True),
        "translation": TaskPolicy("translate", openai_chat, json_required=True),
        "medicine_matching": TaskPolicy("translate", openai_chat, json_required=True),
        "medicine_context": TaskPolicy("translate", openai_chat, json_required=True),
        "medicine_lookup_query": TaskPolicy("translate", openai_chat, json_required=True),
        "medicine_translation_repair": TaskPolicy("translate", openai_chat, json_required=True),
        "after_visit_translation": TaskPolicy("translate", openai_chat, json_required=True),
        "transcript_cleanup": TaskPolicy("transcript_cleanup", openai_chat, json_required=True),
        "soap_generation": TaskPolicy("soap_generate", openai_chat, json_required=True),
        "clinical_suggestions": TaskPolicy("clinical_suggestions", openai_chat, json_required=True),
        "coding_suggestions": TaskPolicy("coding_suggestions", openai_chat, json_required=True),
        "patient_assistant": TaskPolicy("patient_assistant_answer", openai_chat, json_required=True),
        "stt_intake": TaskPolicy(
            "stt_intake",
            {
                "openrouter": {
                    openrouter_stt,
                    openrouter_whisper,
                    "openai/gpt-4o-transcribe",
                    "openai/whisper-large-v3",
                    "openai/gpt-4o-mini-transcribe",
                },
                "groq": {groq_stt, module2_stt, "whisper-large-v3-turbo"},
                "mock": {"mock-stt"},
            },
            minimize_text=False,
            raw_audio=True,
        ),
        "module2_stt": TaskPolicy(
            "module2_stt",
            {
                "openrouter": {
                    openrouter_stt,
                    openrouter_whisper,
                    "openai/gpt-4o-transcribe",
                    "openai/whisper-large-v3",
                    "openai/gpt-4o-mini-transcribe",
                },
                "groq": {module2_stt, groq_stt, "whisper-large-v3-turbo"},
                "openai": {openai_stt, "gpt-4o-transcribe", "whisper-1"},
                "mock": {"mock-stt"},
            },
            minimize_text=False,
            raw_audio=True,
        ),
    }


def _preferred_model(task_type: str, provider: str, allowed_models: set[str]) -> str:
    if task_type in {'medicine_matching','medicine_context','medicine_translation_repair','medicine_lookup_query'}:task_type='transcript_cleanup'
    preferred_by_task = {
        "module2_stt": {
            "openrouter": _env("MODULE2_OPENROUTER_STT_MODEL", "openai/gpt-4o-transcribe"),
            "groq": _env("MODULE2_GROQ_STT_MODEL", "whisper-large-v3"),
            "openai": _env("OPENAI_STT_MODEL", "whisper-1"),
        },
        "stt_intake": {
            "openrouter": _env("MODULE2_OPENROUTER_STT_MODEL", "openai/gpt-4o-transcribe"),
            "groq": _env("GROQ_STT_MODEL", "whisper-large-v3"),
        },
        "transcript_cleanup": {
            "openrouter": _env("OPENROUTER_LLM_MODEL", "openai/gpt-4o-mini"),
            "openai": _env("OPENAI_LLM_MODEL", "gpt-4o-mini"),
            "groq": _env("GROQ_LLM_MODEL", "qwen/qwen3.8-27b"),
        },
        "coding_suggestions": {
            "openrouter": _env("OPENROUTER_LLM_MODEL", "openai/gpt-4o-mini"),
            "openai": _env("OPENAI_LLM_MODEL", "gpt-4o-mini"),
            "groq": _env("GROQ_LLM_MODEL", "qwen/qwen3.8-27b"),
        },
        "diarization": {
            "openrouter": _env("OPENROUTER_LLM_MODEL", "openai/gpt-4o-mini"),
            "openai": _env("OPENAI_DIARIZATION_MODEL", _env("OPENAI_LLM_MODEL", "gpt-4o-mini")),
            "groq": _env("GROQ_DIARIZATION_MODEL", _env("GROQ_LLM_MODEL", "qwen/qwen3.8-27b")),
        },
    }
    preferred = preferred_by_task.get(task_type, {}).get(provider, "")
    if preferred and preferred in allowed_models:
        return preferred
    return sorted(allowed_models)[0]


def _default_provider_for_task(task_type: str, gateway_provider: str) -> str:
    # Keep mock gateways fully isolated from live .env provider preferences.
    if gateway_provider == "mock":
        return "mock"
    if task_type == "module2_stt":
        explicit = _env("MODULE2_STT_PROVIDER").lower()
        if explicit:
            return explicit
        if _has_openrouter():
            return "openrouter"
        return gateway_provider if gateway_provider in {"groq", "openai", "openrouter"} else "groq"
    if task_type == "transcript_cleanup":
        explicit = _env("TRANSCRIPT_CLEANUP_PROVIDER").lower()
        if explicit:
            return explicit
        if _has_openrouter():
            return "openrouter"
    return gateway_provider


class SecureLLMGateway:
    def __init__(
        self,
        *,
        provider: str | None = None,
        adapters: dict[str, Any] | None = None,
        policies: dict[str, TaskPolicy] | None = None,
    ) -> None:
        self.provider = (provider or _env("MEDFLOW_LLM_PROVIDER", "groq")).lower()
        self.policies = policies or _policies()
        self.adapters = adapters or {}
        self.last_outbound_payload: Any = None
        self.last_task_type = ""

    def _adapter(self, provider: str) -> Any:
        if provider in self.adapters:
            return self.adapters[provider]
        if provider == "mock":
            self.adapters[provider] = MockProviderAdapter()
        elif provider == "groq":
            self.adapters[provider] = GroqProviderAdapter(_env("GROQ_API_KEY"))
        elif provider == "openai":
            self.adapters[provider] = OpenAIProviderAdapter(_env("OPENAI_API_KEY"))
        elif provider == "openrouter":
            self.adapters[provider] = OpenRouterProviderAdapter(_env("OPENROUTER_API_KEY"))
        else:
            raise GatewaySecurityError("Provider is not configured")
        return self.adapters[provider]

    def _select_provider_model(self, task_type: str, provider: str | None, model: str | None) -> tuple[str, str]:
        if task_type not in self.policies:
            raise GatewaySecurityError("Task type is not allowlisted")
        policy = self.policies[task_type]
        selected_provider = (provider or _default_provider_for_task(task_type, self.provider)).lower()
        if selected_provider == "auto":
            selected_provider = _default_provider_for_task(task_type, self.provider)
        allowed_models = policy.allowed.get(selected_provider)
        if not allowed_models:
            raise GatewaySecurityError("Provider is not allowlisted for task")
        selected_model = model or _preferred_model(task_type, selected_provider, allowed_models)
        if selected_model not in allowed_models:
            raise GatewaySecurityError("Model is not allowlisted for task")
        return selected_provider, selected_model

    def prepare_messages(
        self,
        messages: list[dict[str, str]],
        *,
        patient_context: dict[str, Any] | None,
        minimize: bool,
    ) -> list[dict[str, str]]:
        payload = minimize_payload(messages, patient_context) if minimize else messages
        return [
            {"role": str(item.get("role", "user")), "content": str(item.get("content", ""))}
            for item in payload
        ]

    @staticmethod
    def _require_task_actor(actor: Actor | None, policy: TaskPolicy, patient_ref: str) -> Actor:
        if actor is None:
            raise GatewaySecurityError("Authenticated task actor is required")
        try:
            require_authorized(actor, policy.action, patient_ref)
        except AuthorizationError as exc:
            raise GatewaySecurityError("Actor is not authorized for task") from exc
        return actor

    def _fallback_attempts(
        self,
        *,
        task_type: str,
        provider_name: str,
        selected_model: str,
    ) -> list[tuple[str, str]]:
        policy = self.policies[task_type]
        attempts = [(provider_name, selected_model)]
        live_providers = ("openrouter", "openai", "groq")
        if provider_name not in live_providers:
            return attempts
        for fallback_provider in live_providers:
            if fallback_provider == provider_name:
                continue
            fallback_models = policy.allowed.get(fallback_provider) or set()
            if not fallback_models:
                continue
            attempts.append(
                (
                    fallback_provider,
                    _preferred_model(task_type, fallback_provider, fallback_models),
                )
            )
        # Extra OpenRouter Whisper fallback if primary OpenRouter model was gpt-transcribe.
        if provider_name == "openrouter":
            whisper = _env("MODULE2_OPENROUTER_WHISPER_MODEL", "openai/whisper-large-v3")
            if whisper in (policy.allowed.get("openrouter") or set()) and (provider_name, whisper) not in attempts:
                attempts.insert(1, ("openrouter", whisper))
        return attempts

    def chat(
        self,
        *,
        task_type: str,
        messages: list[dict[str, str]],
        actor: Actor | None = None,
        patient_ref: str = "",
        patient_context: dict[str, Any] | None = None,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        response_format: dict[str, str] | None = None,
        timeout_seconds: float = 90.0,
    ) -> str:
        policy = self.policies.get(task_type)
        if not policy:
            raise GatewaySecurityError("Task type is not allowlisted")
        provider_name, selected_model = self._select_provider_model(task_type, provider, model)
        authorized_actor = self._require_task_actor(actor, policy, patient_ref)
        actor_ref = authorized_actor.ref
        safe_messages = self.prepare_messages(
            messages,
            patient_context=patient_context,
            minimize=policy.minimize_text,
        )
        self.last_outbound_payload = safe_messages
        self.last_task_type = task_type
        if policy.minimize_text and contains_phi(safe_messages, patient_context):
            audit_event(
                "llm_request_blocked",
                actor_ref=actor_ref,
                action=policy.action,
                patient_ref=patient_ref,
                result="deny",
                metadata={"reason": "phi_after_minimization", "task_type": task_type},
            )
            raise GatewaySecurityError("PHI minimization failed")
        audit_event(
            "llm_request",
            actor_ref=actor_ref,
            action=policy.action,
            patient_ref=patient_ref,
            result="allow",
            metadata={"task_type": task_type, "provider": provider_name, "model": selected_model},
        )
        started = time.perf_counter()
        attempts = self._fallback_attempts(
            task_type=task_type,
            provider_name=provider_name,
            selected_model=selected_model,
        )

        last_error: Exception | None = None
        for attempt_provider, attempt_model in attempts:
            try:
                result = self._adapter(attempt_provider).chat(
                    task_type=task_type,
                    model=attempt_model,
                    messages=safe_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
                if attempt_provider != provider_name or attempt_model != selected_model:
                    audit_event(
                        "llm_provider_fallback",
                        actor_ref=actor_ref,
                        action=policy.action,
                        patient_ref=patient_ref,
                        result="allow",
                        metadata={
                            "task_type": task_type,
                            "from_provider": provider_name,
                            "to_provider": attempt_provider,
                            "model": attempt_model,
                        },
                    )
                if time.perf_counter() - started > timeout_seconds:
                    raise GatewaySecurityError("Provider request timed out")
                provider_event(task_type, attempt_provider, attempt_model, "complete", attempt_provider != provider_name or attempt_model != selected_model)
                return str(result)
            except GatewaySecurityError:
                raise
            except ProviderAdapterError as exc:
                provider_event(task_type, attempt_provider, attempt_model, "failed")
                last_error = exc
                print(f"[Gateway] {task_type} via {attempt_provider}/{attempt_model} failed: {exc}")
            except Exception as exc:
                provider_event(task_type, attempt_provider, attempt_model, "failed")
                last_error = exc
                print(f"[Gateway] {task_type} via {attempt_provider}/{attempt_model} failed: {type(exc).__name__}")
        raise GatewaySecurityError("Provider request failed safely") from last_error

    def chat_json(self, **kwargs: Any) -> dict[str, Any]:
        raw = self.chat(response_format={"type": "json_object"}, **kwargs)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GatewaySecurityError("Provider returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise GatewaySecurityError("Provider returned non-object JSON")
        return parsed

    def transcribe_audio(
        self,
        *,
        task_type: str,
        audio_bytes: bytes,
        actor: Actor | None = None,
        patient_ref: str = "",
        provider: str | None = None,
        model: str | None = None,
        language: str | None = None,
        prompt: str | None = None,
        response_format: str = "text",
    ) -> str:
        policy = self.policies.get(task_type)
        if not policy or not policy.raw_audio:
            raise GatewaySecurityError("Task is not approved for raw audio")
        provider_name, selected_model = self._select_provider_model(task_type, provider, model)
        authorized_actor = self._require_task_actor(actor, policy, patient_ref)
        actor_ref = authorized_actor.ref
        audit_event(
            "stt_request",
            actor_ref=actor_ref,
            action=policy.action,
            patient_ref=patient_ref,
            result="allow",
            metadata={
                "task_type": task_type,
                "provider": provider_name,
                "model": selected_model,
                "audio_size": len(audio_bytes),
            },
        )
        self.last_outbound_payload = {"kind": "audio", "audio_size": len(audio_bytes)}
        self.last_task_type = task_type

        attempts = self._fallback_attempts(
            task_type=task_type,
            provider_name=provider_name,
            selected_model=selected_model,
        )
        last_error: Exception | None = None
        for attempt_provider, attempt_model in attempts:
            try:
                # OpenRouter STT rejects response_format=text; adapters normalize as needed.
                result = self._adapter(attempt_provider).transcribe(
                    task_type=task_type,
                    model=attempt_model,
                    audio_bytes=audio_bytes,
                    language=language,
                    prompt=prompt,
                    response_format=response_format,
                )
                text = str(result).strip()
                if attempt_provider != provider_name or attempt_model != selected_model:
                    audit_event(
                        "stt_provider_fallback",
                        actor_ref=actor_ref,
                        action=policy.action,
                        patient_ref=patient_ref,
                        result="allow",
                        metadata={
                            "task_type": task_type,
                            "from_provider": provider_name,
                            "to_provider": attempt_provider,
                            "model": attempt_model,
                        },
                    )
                    print(f"[Gateway] {task_type} fallback -> {attempt_provider}/{attempt_model}")
                provider_event(task_type, attempt_provider, attempt_model, "complete", attempt_provider != provider_name or attempt_model != selected_model)
                return text
            except ProviderAdapterError as exc:
                provider_event(task_type, attempt_provider, attempt_model, "failed")
                last_error = exc
                print(f"[Gateway] {task_type} via {attempt_provider}/{attempt_model} failed: {exc}")
            except Exception as exc:
                provider_event(task_type, attempt_provider, attempt_model, "failed")
                last_error = exc
                print(f"[Gateway] {task_type} via {attempt_provider}/{attempt_model} failed: {type(exc).__name__}")
        raise GatewaySecurityError("Provider STT failed safely") from last_error


_GATEWAY: SecureLLMGateway | None = None


def get_gateway() -> SecureLLMGateway:
    global _GATEWAY
    if _GATEWAY is None:
        _GATEWAY = SecureLLMGateway()
    return _GATEWAY


def set_gateway(gateway: SecureLLMGateway | None) -> None:
    global _GATEWAY
    _GATEWAY = gateway
