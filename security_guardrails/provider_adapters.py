from __future__ import annotations

import base64
import io
import json
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


class ProviderAdapterError(RuntimeError):
    pass


class MockProviderAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: dict[str, Any] = {}

    def set_response(self, task_type: str, response: Any) -> None:
        self.responses[task_type] = response

    def chat(self, *, task_type: str, model: str, messages: list[dict[str, str]], **_: Any) -> str:
        self.calls.append({"kind": "chat", "task_type": task_type, "model": model, "messages": messages})
        response = self.responses.get(task_type)
        if response is None and task_type == "soap_generation":
            response = {
                "subjective": "The patient provided a synthetic response during the consultation.",
                "objective": "Not documented.",
                "assessment": "Not documented.",
                "plan": "Not documented.",
                "visit_date": "2026-01-01",
                "generated_by": "AI Medical Scribe",
                "evidence": [{"utterance_id": "U1", "quote": "synthetic response"}],
            }
        if response is None and task_type == "coding_suggestions":
            response = {
                "suggestions": [
                    {
                        "system": "ICD-10",
                        "code": "R52",
                        "description": "Pain, unspecified",
                        "confidence": 0.7,
                        "evidence_ids": ["U1"],
                    },
                    {
                        "system": "CPT",
                        "code": "99213",
                        "description": "Office or other outpatient visit",
                        "confidence": 0.7,
                        "evidence_ids": ["U1"],
                    },
                ]
            }
        if response is None:
            response = {
                "conversation": [{"speaker": "Doctor", "text": "synthetic response"}],
                "subjective": "Patient reports synthetic fever.",
                "objective": "Not documented.",
                "assessment": "Viral syndrome supported by reported fever.",
                "plan": "Supportive care and clinician review.",
                "visit_date": "2026-01-01",
                "generated_by": "AI Medical Scribe",
                "evidence": [{"utterance_id": "U1", "quote": "synthetic fever"}],
                "status": "related",
                "summary": "Synthetic summary",
                "answer": "Synthetic answer from current patient context.",
                "sources": ["patient_record"],
                "suggestions": [],
            }
        return json.dumps(response) if isinstance(response, (dict, list)) else str(response)

    def transcribe(self, *, task_type: str, model: str, audio_bytes: bytes, **_: Any) -> str:
        self.calls.append(
            {"kind": "stt", "task_type": task_type, "model": model, "audio_size": len(audio_bytes)}
        )
        return str(self.responses.get(task_type, "synthetic Urdu transcript"))


class GroqProviderAdapter:
    def __init__(self, api_key: str) -> None:
        cleaned = str(api_key or "").strip().strip('"').strip("'")
        if not cleaned:
            raise ProviderAdapterError("Groq API key is not configured")
        from groq import Groq

        self._client = Groq(api_key=cleaned)

    def chat(
        self,
        *,
        task_type: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format
        response = self._client.chat.completions.create(**kwargs)
        return (response.choices[0].message.content or "").strip()

    def transcribe(
        self,
        *,
        task_type: str,
        model: str,
        audio_bytes: bytes,
        language: str | None = None,
        prompt: str | None = None,
        response_format: str = "text",
    ) -> str:
        request_kwargs: dict[str, Any] = {
            "model": model,
            "file": ("audio.wav", io.BytesIO(audio_bytes), "audio/wav"),
            "response_format": response_format,
        }
        if language:
            request_kwargs["language"] = language
        if prompt:
            request_kwargs["prompt"] = prompt
        result = self._client.audio.transcriptions.create(**request_kwargs)
        return result if isinstance(result, str) else getattr(result, "text", str(result))


class OpenAIProviderAdapter:
    def __init__(self, api_key: str) -> None:
        cleaned = str(api_key or "").strip().strip('"').strip("'")
        if not cleaned:
            raise ProviderAdapterError("OpenAI API key is not configured")
        self._api_key = cleaned

    def chat(
        self,
        *,
        task_type: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        request = urllib_request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
            return str(body["choices"][0]["message"]["content"]).strip()
        except urllib_error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:240]
            except Exception:
                detail = ""
            suffix = f": {detail}" if detail else ""
            raise ProviderAdapterError(f"OpenAI request failed with HTTP {exc.code}{suffix}") from exc
        except urllib_error.URLError as exc:
            raise ProviderAdapterError("OpenAI request failed") from exc

    def transcribe(
        self,
        *,
        task_type: str,
        model: str,
        audio_bytes: bytes,
        language: str | None = None,
        prompt: str | None = None,
        response_format: str = "text",
    ) -> str:
        boundary = "----MedflowSecureBoundary"
        fields = {"model": model, "response_format": response_format}
        if language:
            fields["language"] = language
        if prompt:
            fields["prompt"] = prompt
        body = bytearray()
        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n')
        body.extend(b"Content-Type: audio/wav\r\n\r\n")
        body.extend(audio_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        request = urllib_request.Request(
            "https://api.openai.com/v1/audio/transcriptions",
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=120) as response:
                return response.read().decode("utf-8", errors="ignore").strip()
        except urllib_error.HTTPError as exc:
            raise ProviderAdapterError(f"OpenAI STT failed with HTTP {exc.code}") from exc
        except urllib_error.URLError as exc:
            raise ProviderAdapterError("OpenAI STT failed") from exc


class OpenRouterProviderAdapter:
    """OpenRouter chat + dedicated speech-to-text adapter."""

    def __init__(self, api_key: str) -> None:
        cleaned = str(api_key or "").strip().strip('"').strip("'")
        if not cleaned:
            raise ProviderAdapterError("OpenRouter API key is not configured")
        self._api_key = cleaned

    def chat(
        self,
        *,
        task_type: str,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        return self._post_json(
            "https://openrouter.ai/api/v1/chat/completions",
            payload,
            timeout=90,
            error_prefix="OpenRouter chat",
        )["choices"][0]["message"]["content"].strip()

    def transcribe(
        self,
        *,
        task_type: str,
        model: str,
        audio_bytes: bytes,
        language: str | None = None,
        prompt: str | None = None,
        response_format: str = "text",
    ) -> str:
        # OpenRouter STT accepts OpenAI-style multipart; response_format must be json/verbose_json.
        requested_format = "json" if response_format in {"text", "json", ""} else response_format
        if requested_format not in {"json", "verbose_json"}:
            requested_format = "json"

        boundary = "----MedflowOpenRouterBoundary"
        fields: dict[str, str] = {
            "model": model,
            "response_format": requested_format,
            "temperature": "0",
        }
        if language:
            fields["language"] = language
        # Top-level prompt is ignored by some OpenRouter STT routes; also pass via Groq options
        # when Whisper is routed there.
        if prompt:
            fields["prompt"] = prompt

        body = bytearray()
        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        if prompt:
            # Provider-specific vocabulary hint for Whisper routes.
            provider_options = json.dumps(
                {"options": {"groq": {"prompt": prompt}, "deepinfra": {"prompt": prompt}}}
            )
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(b'Content-Disposition: form-data; name="provider"\r\n\r\n')
            body.extend(provider_options.encode("utf-8"))
            body.extend(b"\r\n")
        filename, content_type = self._audio_filename_and_mime(audio_bytes)
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(audio_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        request = urllib_request.Request(
            "https://openrouter.ai/api/v1/audio/transcriptions",
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "HTTP-Referer": "https://medflow.local",
                "X-Title": "MedFlowAI Module2 STT",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8", errors="ignore").strip()
        except urllib_error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:240]
            except Exception:
                detail = ""
            # Fallback to JSON/base64 body for hosts that reject multipart.
            if exc.code in {400, 413, 415, 422}:
                try:
                    return self._transcribe_json(
                        model=model,
                        audio_bytes=audio_bytes,
                        language=language,
                        prompt=prompt,
                        response_format=requested_format,
                    )
                except Exception:
                    pass
            suffix = f": {detail}" if detail else ""
            raise ProviderAdapterError(f"OpenRouter STT failed with HTTP {exc.code}{suffix}") from exc
        except urllib_error.URLError as exc:
            raise ProviderAdapterError("OpenRouter STT failed") from exc

        return self._extract_transcript_text(raw)

    @staticmethod
    def _audio_filename_and_mime(audio_bytes: bytes) -> tuple[str, str]:
        head = audio_bytes[:16] if audio_bytes else b""
        if head.startswith(b"RIFF") and b"WAVE" in audio_bytes[:12]:
            return "audio.wav", "audio/wav"
        if head.startswith(b"OggS"):
            return "audio.ogg", "audio/ogg"
        if head.startswith(b"\x1aE\xdf\xa3"):
            return "audio.webm", "audio/webm"
        if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
            return "audio.mp3", "audio/mpeg"
        if head.startswith(b"fLaC"):
            return "audio.flac", "audio/flac"
        return "audio.wav", "audio/wav"

    def _transcribe_json(
        self,
        *,
        model: str,
        audio_bytes: bytes,
        language: str | None,
        prompt: str | None,
        response_format: str,
    ) -> str:
        filename, _mime = self._audio_filename_and_mime(audio_bytes)
        audio_format = filename.rsplit(".", 1)[-1]
        payload: dict[str, Any] = {
            "model": model,
            "response_format": response_format,
            "temperature": 0,
            "input_audio": {
                "data": base64.b64encode(audio_bytes).decode("ascii"),
                "format": audio_format,
            },
        }
        if language:
            payload["language"] = language
        if prompt:
            payload["prompt"] = prompt
            payload["provider"] = {
                "options": {
                    "groq": {"prompt": prompt},
                    "deepinfra": {"prompt": prompt},
                }
            }
        body = self._post_json(
            "https://openrouter.ai/api/v1/audio/transcriptions",
            payload,
            timeout=120,
            error_prefix="OpenRouter STT",
        )
        text = body.get("text")
        if not text:
            raise ProviderAdapterError("OpenRouter STT returned empty transcript")
        return str(text).strip()

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout: int,
        error_prefix: str,
    ) -> dict[str, Any]:
        request = urllib_request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://medflow.local",
                "X-Title": "MedFlowAI",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:240]
            except Exception:
                detail = ""
            suffix = f": {detail}" if detail else ""
            raise ProviderAdapterError(f"{error_prefix} failed with HTTP {exc.code}{suffix}") from exc
        except urllib_error.URLError as exc:
            raise ProviderAdapterError(f"{error_prefix} failed") from exc

    @staticmethod
    def _extract_transcript_text(raw: str) -> str:
        if not raw:
            return ""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip()
        if isinstance(parsed, dict):
            text = parsed.get("text")
            if text:
                return str(text).strip()
        return raw.strip()
